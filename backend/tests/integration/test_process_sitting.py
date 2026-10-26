"""The admin's "Process sitting" button: the steps it runs (the same ones the command line runs),
the background run and what it reports, and the two routes."""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.core.staff_token import issue_staff_token
from app.main import app
from app.models import AuditLog, Ranking, Sitting
from app.services import processing
from app.services.processing import launch as real_launch  # conftest stubs the module's own
from app.services.ranking.base import RankerError
from app.services.ranking.rules import rule_order
from app.services.staff_auth import create_reviewer
from tests.integration.test_packets_and_ranking import Scripted, always

PASSWORD = "correct horse battery"
STEP_LABELS = ["compute flags", "assemble video", "scan audio", "build packets", "rank"]


@pytest.fixture(autouse=True)
def forget_runs():
    processing._runs.clear()
    yield
    processing._runs.clear()


@pytest.fixture
def admin_headers(db, clock, settings):
    account, _ = create_reviewer(
        db, clock, email="boss@example.com", password=PASSWORD, role="admin"
    )
    token = issue_staff_token(settings.session_secret, clock, account.id, account.password_hash)
    return {"Authorization": f"Bearer {token}"}


class Borrowed:
    """The test's own session, handed out the way SessionLocal() hands out a new one."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        return False


def audit_lines(db):
    return list(db.scalars(select(AuditLog.detail).where(AuditLog.detail.like("started proc%"))))


# ------------------------------------------------------------------------------------ the steps


def test_every_step_runs_in_order_and_everyone_flagged_is_ranked(db, sim, clock, settings):
    shown = []
    steps = processing.process_sitting(
        db, sim.sitting_id, settings, clock, None, use_video=False, on_step=shown.append
    )

    assert [s.label for s in steps] == STEP_LABELS
    assert shown == steps  # the callback sees each step as it finishes
    assert steps[1].note.startswith("skipped") and steps[2].note.startswith("skipped")
    queued = len(rule_order(db, sim.sitting_id))
    assert queued > 0
    assert db.scalar(select(func.count()).select_from(Ranking)) == queued
    assert f"{queued} ranked by rules only" in steps[-1].note


def test_with_a_model_the_answers_that_pass_the_fact_check_are_kept(db, sim, clock, settings):
    ranker = Scripted(always(4))
    steps = processing.process_sitting(db, sim.sitting_id, settings, clock, ranker, use_video=False)

    assert "scripted scripted-1" in steps[-1].note
    statuses = set(db.scalars(select(Ranking.ai_status)))
    assert statuses == {"ok"}


def test_running_it_twice_leaves_one_ranking_per_candidate(db, sim, clock, settings):
    for _ in range(2):
        processing.process_sitting(db, sim.sitting_id, settings, clock, None, use_video=False)
    queued = len(rule_order(db, sim.sitting_id))
    assert db.scalar(select(func.count()).select_from(Ranking)) == queued


# ------------------------------------------------------------------------- the background run


@pytest.fixture
def inline(db, sim, settings, monkeypatch):
    """What a thread would see, run in the test's own session and transaction."""
    monkeypatch.setattr("app.db.SessionLocal", lambda: Borrowed(db))
    monkeypatch.setattr(processing, "get_settings", lambda: settings)
    monkeypatch.setattr(processing.ffmpeg, "available", lambda: False)


def test_a_finished_run_says_done_with_its_steps_and_end_time(inline, sim, clock):
    run = processing.Run(started_at=clock.now())
    processing._work(sim.sitting_id, clock, run)

    assert run.state == "done" and run.error is None
    assert [s.label for s in run.steps] == STEP_LABELS
    assert run.finished_at is not None


def test_a_model_that_cannot_start_fails_the_run_and_says_why(inline, sim, clock, monkeypatch):
    def refuse(settings):
        raise RankerError("no Anthropic key is set")

    monkeypatch.setattr(processing, "get_ranker", refuse)
    run = processing.Run(started_at=clock.now())
    processing._work(sim.sitting_id, clock, run)

    assert run.state == "failed"
    assert "no Anthropic key is set" in run.error
    assert run.steps == [] and run.finished_at is not None


def test_an_unexpected_error_is_logged_not_shown(inline, sim, clock, monkeypatch, caplog):
    def explode(*args, **kwargs):
        raise RuntimeError("password=hunter2 in the connection string")

    monkeypatch.setattr(processing, "process_sitting", explode)
    run = processing.Run(started_at=clock.now())
    processing._work(sim.sitting_id, clock, run)

    assert run.state == "failed"
    assert "hunter2" not in run.error  # the page gets a plain sentence; the log has the rest
    assert "hunter2" in caplog.text


def test_a_second_launch_while_one_is_running_does_not_start_another(sim, clock, monkeypatch):
    started = []
    # only this module's view of `threading` is swapped; no other thread in the process is touched
    fake = SimpleNamespace(Thread=lambda **kw: _Recorder(started, kw))
    monkeypatch.setattr(processing, "threading", fake)

    assert real_launch(sim.sitting_id, clock) is True
    assert real_launch(sim.sitting_id, clock) is False
    assert len(started) == 1
    processing._runs[sim.sitting_id].state = "failed"
    assert real_launch(sim.sitting_id, clock) is True  # a run that ended can be repeated


class _Recorder:
    def __init__(self, started, kwargs):
        self.started, self.kwargs = started, kwargs

    def start(self):
        self.started.append(self.kwargs["name"])


# ------------------------------------------------------------------------------------ the routes


def fake_launch(monkeypatch, clock):
    calls = []

    def launch(sitting_id, clock_=None):
        calls.append(sitting_id)
        if len(calls) > 1:
            return False
        processing._runs[sitting_id] = processing.Run(started_at=clock.now())
        return True

    monkeypatch.setattr(processing, "launch", launch)
    return calls


def test_only_an_admin_can_start_or_read_a_run(client, sim, staff):
    url = f"/api/admin/sittings/{sim.sitting_id}/process"
    assert client.post(url).status_code == 401
    assert client.get(url).status_code == 401
    assert client.post(url, headers=staff).status_code == 403  # a reviewer, not an admin
    assert client.get(url, headers=staff).status_code == 403


def test_an_unknown_sitting_is_a_404_and_an_open_one_is_refused(client, db, sim, admin_headers):
    missing = "/api/admin/sittings/99999/process"
    assert client.post(missing, headers=admin_headers).status_code == 404
    assert client.get(missing, headers=admin_headers).status_code == 404

    db.get(Sitting, sim.sitting_id).status = "open"
    db.flush()
    refused = client.post(f"/api/admin/sittings/{sim.sitting_id}/process", headers=admin_headers)
    assert refused.status_code == 409 and refused.json()["code"] == "sitting_not_closed"


def test_starting_reports_running_and_is_written_to_the_audit_log_once(
    client, db, sim, clock, admin_headers, monkeypatch
):
    calls = fake_launch(monkeypatch, clock)
    url = f"/api/admin/sittings/{sim.sitting_id}/process"

    first = client.post(url, headers=admin_headers)
    assert first.status_code == 200
    assert first.json()["state"] == "running" and first.json()["steps"] == []
    again = client.post(url, headers=admin_headers)  # a second click while it runs
    assert again.json()["state"] == "running"

    assert calls == [sim.sitting_id, sim.sitting_id]
    lines = audit_lines(db)
    assert len(lines) == 1 and "(rules)" in lines[0]


def test_the_status_before_during_and_after_a_run(client, db, sim, clock, settings, admin_headers):
    url = f"/api/admin/sittings/{sim.sitting_id}/process"
    idle = client.get(url, headers=admin_headers).json()
    assert idle["state"] == "idle" and idle["last_ranked_at"] is None
    assert (idle["provider"], idle["model"]) == ("rules", None)

    run = processing.Run(started_at=clock.now())
    processing._runs[sim.sitting_id] = run
    processing.process_sitting(
        db, sim.sitting_id, settings, clock, None, use_video=False, on_step=run.steps.append
    )
    run.finished_at, run.state = clock.now(), "done"

    done = client.get(url, headers=admin_headers).json()
    assert done["state"] == "done" and done["error"] is None
    assert [s["label"] for s in done["steps"]] == STEP_LABELS
    assert done["finished_at"] is not None and done["last_ranked_at"] is not None


def test_the_status_names_the_model_a_new_run_would_use(client, sim, settings, admin_headers):
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={"ai_provider": "ollama", "ollama_model": "gemma-test"}
    )  # the client fixture clears its overrides afterwards
    body = client.get(f"/api/admin/sittings/{sim.sitting_id}/process", headers=admin_headers).json()
    assert (body["provider"], body["model"]) == ("ollama", "gemma-test")
