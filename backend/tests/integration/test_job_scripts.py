"""The command-line jobs and the worker, run through their own main() against the test database.

The services under them are tested elsewhere; this checks the wiring: the arguments, what is
printed, the exit codes, that the video really goes, and that the worker survives a bad round.
These scripts were the least-tested code in the repository (the worker loop and the 30-day
deletion included).
"""

import contextlib
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.clock import SystemClock
from app.models import AuditLog, Event, TestSession
from app.services.ranking.base import RankerError
from app.services.ranking.rules import rule_order
from app.services.video.store import LocalVideoStore, chunk_key
from scripts import (
    build_packets,
    chunk_integrity,
    close_sitting,
    compute_flags,
    jobs,
    loop,
    mark_incomplete_uploads,
    process_sitting,
    purge_videos,
    rank,
)
from scripts.common import resolve_sitting
from scripts.simulate_cohort import SITTING_NAME
from tests.integration.test_retention import decide, files, give_video

DAY = timedelta(days=1)


@pytest.fixture
def wired(db, settings, monkeypatch):
    """Every job opens its own database session and reads the global settings: hand them the
    test's own, so a job runs in the test's transaction and never sees a developer's .env."""
    monkeypatch.setattr("app.db.SessionLocal", lambda: contextlib.nullcontext(db))
    for module in (
        purge_videos, loop, close_sitting, mark_incomplete_uploads, process_sitting, rank,
        chunk_integrity,
    ):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def sessions(db, sim):
    ids = sorted(db.scalars(select(TestSession.id).where(TestSession.sitting_id == sim.sitting_id)))
    return [db.get(TestSession, i) for i in ids]


# ------------------------------------------------------------------------------ the dispatcher


@pytest.mark.parametrize("argv", [[], ["no_such_job"]])
def test_the_dispatcher_lists_the_jobs_when_given_nothing_or_a_wrong_name(argv):
    with pytest.raises(SystemExit) as stop:
        jobs.main(argv)
    message = str(stop.value)
    assert "usage: python -m scripts.jobs <job>" in message
    assert "close_sitting" in message and "purge_videos" in message


def test_every_script_is_registered_as_a_job_so_none_can_be_forgotten():
    folder = Path(jobs.__file__).parent
    scripts = {p.stem for p in folder.glob("*.py")} - {"__init__", "jobs", "common"}
    registered = {job.__module__.rsplit(".", 1)[-1] for job in jobs.JOBS.values()}
    assert scripts <= registered, f"not registered in jobs.py: {sorted(scripts - registered)}"


def test_a_sitting_is_found_by_id_or_exact_name_or_the_job_exits_plainly(db, sim):
    assert resolve_sitting(db, str(sim.sitting_id)).id == sim.sitting_id
    assert resolve_sitting(db, SITTING_NAME).id == sim.sitting_id
    with pytest.raises(SystemExit, match="no sitting matches 'Nope'"):
        resolve_sitting(db, "Nope")


# ----------------------------------------------------------------------- flags, packets, ranking


def test_compute_flags_reports_the_counts_and_refuses_an_unknown_sitting(wired, sim, capsys):
    compute_flags.main(["--sitting", SITTING_NAME])
    out = capsys.readouterr().out
    assert "16 finished sessions" in out and "cohort rules applied" in out and "closed" in out

    with pytest.raises(SystemExit, match="no sitting matches"):
        compute_flags.main(["--sitting", "999999"])


def test_build_packets_builds_one_for_every_flagged_candidate(wired, db, sim, capsys):
    build_packets.main(["--sitting", str(sim.sitting_id)])
    flagged = len(rule_order(db, sim.sitting_id))
    assert flagged > 0
    assert f"{flagged} packets built" in capsys.readouterr().out


def test_rank_by_rules_lists_every_flagged_candidate_and_names_no_model(wired, db, sim, capsys):
    flagged = len(rule_order(db, sim.sitting_id))
    rank.main(["--sitting", SITTING_NAME, "--provider", "rules"])
    out = capsys.readouterr().out
    assert f"{flagged} flagged, ranked by rules only" in out
    assert f"statuses: not_run {flagged}" in out
    rows = [line for line in out.splitlines() if line.split() and line.split()[0].isdigit()]
    assert len(rows) == flagged  # nobody is dropped


def test_rank_with_a_model_that_cannot_start_stops_with_a_reason_not_a_traceback(
    wired, sim, monkeypatch
):
    def cannot_start(settings):
        raise RankerError("no Anthropic key is set")

    # a stand-in: the real Claude ranker would call the API if a key is in the environment
    monkeypatch.setattr(rank, "get_ranker", cannot_start)
    with pytest.raises(SystemExit, match="cannot use claude: no Anthropic key is set"):
        rank.main(["--sitting", SITTING_NAME, "--provider", "claude"])


def test_process_sitting_runs_every_step_and_says_when_the_sitting_is_still_open(
    wired, db, sim, seeded, capsys
):
    process_sitting.main(["--sitting", SITTING_NAME, "--provider", "rules", "--skip-video"])
    out = capsys.readouterr().out
    for label in ("compute flags", "assemble video", "scan audio", "build packets", "rank"):
        assert label in out
    assert "still open" not in out  # the made-up sitting is closed

    open_sitting = ["--sitting", "Synthetic sitting 1", "--provider", "rules", "--skip-video"]
    process_sitting.main(open_sitting)
    still_open = "the sitting is still open, so the cohort checks will be skipped"
    assert still_open in capsys.readouterr().out


# ---------------------------------------------------------------------------------- closing


def test_close_sitting_refuses_unfinished_candidates_until_forced_and_audits_the_force(
    wired, db, seeded, capsys
):
    with pytest.raises(SystemExit, match=r"not closed: .*unfinished; --force to close anyway"):
        close_sitting.main(["--sitting", "Synthetic sitting 1"])

    close_sitting.main(["--sitting", "Synthetic sitting 1", "--force"])
    assert "closed [forced]" in capsys.readouterr().out
    audited = db.scalars(select(AuditLog.detail).where(AuditLog.detail.like("%command line%")))
    assert len(audited.all()) == 1


# ----------------------------------------------------------------- video: deletion and integrity


def test_purge_videos_deletes_video_thirty_days_after_the_decision_and_lists_the_undecided(
    wired, db, sim, sessions, settings, capsys
):
    now = SystemClock().now()
    store = LocalVideoStore(settings.video_root_path)
    decided, undecided = sessions[0], sessions[1]
    for session in (decided, undecided):
        give_video(db, store, SystemClock(), session)
    decide(db, decided, now - 31 * DAY)
    undecided.finished_at = now - 90 * DAY
    db.flush()

    purge_videos.main(["--report"])

    out = capsys.readouterr().out
    assert "purged 1 sessions" in out and "30 days after their latest decision" in out
    assert files(store, decided) == []  # gone
    assert files(store, undecided) != []  # a person has not decided: never deleted here
    assert "1 finished sessions have video, no decision and are over 60 days old" in out
    assert undecided.candidate_id in out


def test_mark_incomplete_uploads_notes_a_session_once_its_window_has_closed(
    wired, db, sim, sessions, capsys
):
    sessions[0].finished_at = SystemClock().now() - 3 * DAY  # 48 hours passed, no video arrived
    db.flush()

    mark_incomplete_uploads.main([])
    assert "1 sessions marked upload_incomplete" in capsys.readouterr().out
    marked = db.scalar(
        select(func.count()).select_from(Event).where(Event.type == "upload_incomplete")
    )
    assert marked == 1

    mark_incomplete_uploads.main([])  # once, however often it runs
    assert "0 sessions marked" in capsys.readouterr().out


def test_chunk_integrity_passes_intact_video_and_exits_1_when_a_chunk_has_changed(
    wired, db, sim, sessions, settings, capsys
):
    store = LocalVideoStore(settings.video_root_path)
    session = sessions[0]
    give_video(db, store, SystemClock(), session)

    chunk_integrity.main(["--session", session.id])
    assert "1 of 1 passed" in capsys.readouterr().out

    store.put(chunk_key(session.id, 0, 1), b"someone changed these bytes")
    with pytest.raises(SystemExit) as stop:
        chunk_integrity.main(["--session", session.id])
    assert stop.value.code == 1
    assert "FAIL" in capsys.readouterr().out

    with pytest.raises(SystemExit, match="no session 'nope'"):
        chunk_integrity.main(["--session", "nope"])


# ----------------------------------------------------------------------------------- the worker


def test_one_round_of_the_worker_purges_due_video_and_prints_what_it_did(
    wired, db, sim, sessions, settings, capsys
):
    store = LocalVideoStore(settings.video_root_path)
    give_video(db, store, SystemClock(), sessions[0])
    decide(db, sessions[0], SystemClock().now() - 31 * DAY)

    purged, marked = loop.run_round()

    assert purged == 1 and isinstance(marked, int)
    assert files(store, sessions[0]) == []
    assert "purged 1 sessions" in capsys.readouterr().out


def test_a_round_that_fails_is_reported_and_does_not_stop_the_worker(monkeypatch, capsys):
    """One bad afternoon must not stop deletions for good: the traceback goes to the log and the
    next round still runs."""

    class Stop(Exception):
        pass

    rounds, naps = [], []

    def flaky_round():
        rounds.append(1)
        if len(rounds) == 1:
            raise RuntimeError("the database went away")
        return 0, 0

    def nap(seconds):
        naps.append(seconds)
        if len(naps) == 2:
            raise Stop

    monkeypatch.setattr(loop, "run_round", flaky_round)
    monkeypatch.setattr(loop.time, "sleep", nap)

    with pytest.raises(Stop):
        loop.main(["--every", "7"])

    assert len(rounds) == 2 and naps == [7, 7]
    assert "the database went away" in capsys.readouterr().err


def test_once_runs_a_single_round_and_returns_even_when_it_fails(monkeypatch, capsys):
    def broken():
        raise RuntimeError("no database")

    monkeypatch.setattr(loop, "run_round", broken)
    loop.main(["--once"])  # returns; does not sleep, does not raise
    assert "no database" in capsys.readouterr().err
