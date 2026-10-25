"""Keeps a finished session's flags current without anyone running a command.

A candidate's own flags are worked out the moment they finish, and again when late events for a
finished session arrive (the page's last batch, or an upload resumed within the 48 hours). The
group checks (pace, spread) need the whole closed sitting, so closing a sitting does those.

`compute_sitting_flags` stays the source of truth and can be run again at any time. A failure here
is logged and swallowed: it must never fail a candidate's request, and the recompute at close
repairs whatever it missed.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TestSession
from app.services.flags.engine import compute_session_flags

log = logging.getLogger(__name__)


def refresh_session_flags(db: Session, session_id: str) -> None:
    """Recompute one session's flags if it has finished. Commits, and so releases its row lock."""
    try:
        # The lock makes two refreshes of one session take turns instead of both inserting, and
        # populate_existing makes the rules read the session as it is now, not as this request
        # saw it.
        session = db.scalar(
            select(TestSession)
            .where(TestSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if session is not None and session.status == "finished":
            compute_session_flags(db, session_id)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("could not refresh the flags for session %s", session_id)
