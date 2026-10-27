"""Small pieces that run behind a request and must never take it down: the thread pool that writes
AI papers, the flag refresh that follows a finished test, and the database session helper."""

import contextlib
import logging

import pytest
from sqlalchemy import func, select

from app import db as database
from app.models import Flag, TestSession
from app.services.flags import refresh
from app.services.qgen import jobs

# ----------------------------------------------------------------------- writing papers in threads


@pytest.fixture
def empty_registry(monkeypatch):
    monkeypatch.setattr(jobs, "_running", {})
    return jobs._running


class FakePool:
    def __init__(self):
        self.submitted = []

    def submit(self, *call):
        self.submitted.append(call)


def test_a_paper_is_started_once_and_can_be_started_again_after_it_is_abandoned(
    empty_registry, monkeypatch
):
    pool = FakePool()
    monkeypatch.setattr(jobs, "_executor", lambda: pool)

    assert jobs.launch("s1") is True and jobs.is_running("s1")
    assert jobs.launch("s1") is False  # already being written
    assert len(pool.submitted) == 1 and pool.submitted[0][:2] == (jobs._work, "s1")

    jobs.abandon("s1")
    assert not jobs.is_running("s1")
    jobs.abandon("never-started")  # harmless
    assert jobs.launch("s1") is True and len(pool.submitted) == 2


def test_the_pool_is_as_wide_as_the_setting_says_and_is_made_once(monkeypatch, settings):
    three = settings.model_copy(update={"question_workers": 3})
    monkeypatch.setattr(jobs, "_pool", None)
    monkeypatch.setattr(jobs, "get_settings", lambda: three)

    first = jobs._executor()
    try:
        assert first._max_workers == 3
        assert jobs._executor() is first
    finally:
        first.shutdown(wait=True)


def test_a_finished_run_clears_itself_but_never_a_successor_that_replaced_it(
    empty_registry, monkeypatch, settings
):
    calls = []
    monkeypatch.setattr(jobs, "get_settings", lambda: settings)
    monkeypatch.setattr(jobs, "SessionLocal", lambda: contextlib.nullcontext("a-session"))
    monkeypatch.setattr(jobs, "get_writer", lambda s: "a-writer")
    monkeypatch.setattr(jobs.paper, "write_paper", lambda *args: calls.append(args))

    mine, successor = object(), object()
    empty_registry["s1"] = mine
    jobs._work("s1", mine)
    assert calls == [
        ("a-session", "s1", "a-writer", settings.question_solves, settings.question_paper_timeout_s)
    ]
    assert "s1" not in empty_registry

    empty_registry["s2"] = successor  # s2 was abandoned and started again by someone else
    jobs._work("s2", mine)
    assert empty_registry["s2"] is successor


def test_a_paper_that_crashes_is_logged_and_still_clears_its_place(
    empty_registry, monkeypatch, settings, caplog
):
    def crash(*args):
        raise RuntimeError("the model went away")

    monkeypatch.setattr(jobs, "get_settings", lambda: settings)
    monkeypatch.setattr(jobs, "SessionLocal", lambda: contextlib.nullcontext("a-session"))
    monkeypatch.setattr(jobs, "get_writer", lambda s: "a-writer")
    monkeypatch.setattr(jobs.paper, "write_paper", crash)
    run = object()
    empty_registry["s1"] = run

    with caplog.at_level(logging.ERROR):
        jobs._work("s1", run)  # a thread must not die with a traceback on stderr

    assert "writing the paper for session s1 stopped" in caplog.text
    assert "s1" not in empty_registry


# ------------------------------------------------------------------------------ flag refresh


def flag_count(db):
    return db.scalar(select(func.count()).select_from(Flag))


def test_refreshing_a_finished_session_recomputes_its_flags_and_leaves_the_rest_alone(db, sim):
    before = flag_count(db)
    finished = db.scalars(select(TestSession.id).where(TestSession.status == "finished")).first()

    refresh.refresh_session_flags(db, finished)

    assert flag_count(db) == before  # same rules over the same record: same flags


def test_a_session_that_is_not_finished_or_does_not_exist_is_skipped(db, sim, monkeypatch):
    calls = []
    monkeypatch.setattr(refresh, "compute_session_flags", lambda db, sid: calls.append(sid))
    session = db.scalars(select(TestSession)).first()
    session.status = "in_progress"
    db.flush()

    refresh.refresh_session_flags(db, session.id)
    refresh.refresh_session_flags(db, "no-such-session")

    assert calls == []


def test_a_failure_while_refreshing_is_logged_and_swallowed_so_it_cannot_fail_a_request(
    db, sim, monkeypatch, caplog
):
    def crash(db, session_id):
        raise RuntimeError("the rules hit something unexpected")

    monkeypatch.setattr(refresh, "compute_session_flags", crash)
    finished = db.scalars(select(TestSession.id).where(TestSession.status == "finished")).first()

    with caplog.at_level(logging.ERROR):
        refresh.refresh_session_flags(db, finished)  # does not raise

    assert f"could not refresh the flags for session {finished}" in caplog.text


# --------------------------------------------------------------------------------- db session


def test_the_request_session_is_always_closed_even_when_the_request_fails(monkeypatch):
    opened = []

    class Session:
        def __init__(self):
            self.closed = False
            opened.append(self)

        def close(self):
            self.closed = True

    monkeypatch.setattr(database, "SessionLocal", Session)

    quiet = database.get_db()
    assert next(quiet) is opened[0]
    with pytest.raises(StopIteration):
        next(quiet)
    assert opened[0].closed

    failing = database.get_db()
    next(failing)
    with pytest.raises(RuntimeError):
        failing.throw(RuntimeError("the request failed"))
    assert opened[1].closed
