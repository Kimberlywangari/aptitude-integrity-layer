"""Runs the paper writing in the background, a few candidates at a time.

A request that creates a session must answer at once, and writing a paper can take minutes, so the
work goes to a small pool of threads inside the API process. The database holds all the state
(`sessions.paper_status` and the questions written so far), so nothing here needs to survive a
restart: a candidate's page asks again, finds a `pending` paper with nobody working on it, and
`ensure_running` starts the writing again where it stopped.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings
from app.db import SessionLocal
from app.services.qgen import paper
from app.services.qgen.writers import get_writer

log = logging.getLogger(__name__)

_lock = threading.Lock()
# session id -> the run that owns it. A run that was abandoned must not clear its successor.
_running: dict[str, object] = {}
_pool: ThreadPoolExecutor | None = None


def _executor() -> ThreadPoolExecutor:
    global _pool
    with _lock:
        if _pool is None:
            workers = max(1, get_settings().question_workers)
            _pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="qgen")
        return _pool


def is_running(session_id: str) -> bool:
    with _lock:
        return session_id in _running


def _work(session_id: str, run: object) -> None:
    try:
        settings = get_settings()
        with SessionLocal() as db:
            paper.write_paper(
                db,
                session_id,
                get_writer(settings),
                settings.question_solves,
                settings.question_paper_timeout_s,
            )
    except Exception:
        log.exception("writing the paper for session %s stopped", session_id)
    finally:
        with _lock:
            if _running.get(session_id) is run:
                del _running[session_id]


def abandon(session_id: str) -> None:
    """Stop counting a paper as being written, so it can be started again. A thread cannot be
    stopped from outside, and a stuck one is the reason to ask again. If it ever wakes it meets
    positions the new run filled, gets an IntegrityError and leaves (see paper.write_paper)."""
    with _lock:
        _running.pop(session_id, None)


def launch(session_id: str) -> bool:
    """Start writing a session's paper unless it is already being written. Returns whether it
    started. Tests replace this to run the writing inline."""
    with _lock:
        if session_id in _running:
            return False
        run = object()
        _running[session_id] = run
    _executor().submit(_work, session_id, run)
    return True
