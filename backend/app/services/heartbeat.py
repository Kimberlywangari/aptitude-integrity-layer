"""The 10-second heartbeat. A long hole in it, with no dropped connection or reload to explain it,
becomes a LOGGING_PROBLEM (flags/rules.py); this module only writes the ticks and tells the page
what time the server thinks it is."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.clock import Clock
from app.models import Heartbeat, TestSession


@dataclass(frozen=True)
class Tick:
    server_time: datetime
    remaining_s: float
    status: str


def record(db: Session, clock: Clock, session: TestSession) -> Tick:
    """Store a tick while the test is running; otherwise just answer.

    Nothing is stored before the test begins, after it ends or once its time has run out: a tick
    outside the test would only make the table longer. The reply carries the server's remaining
    time so the page can quietly re-sync its countdown.
    """
    now = clock.now()
    running = (
        session.status == "in_progress" and session.ends_at is not None and now < session.ends_at
    )
    if not running:
        return Tick(now, 0.0, session.status)
    db.add(Heartbeat(session_id=session.id, server_ts=now))
    db.commit()
    return Tick(now, max(0.0, round((session.ends_at - now).total_seconds(), 1)), session.status)
