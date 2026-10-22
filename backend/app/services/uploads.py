"""Uploads that did not finish.

A candidate has 48 hours after the test to get the video up. When that has passed and chunks are
still missing, the record gets an `upload_incomplete` event, once. A reviewer sees it as context
("this recording is partial"); it never counts against the candidate.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.clock import Clock
from app.models import Event, TestSession
from app.services.video.chunks import manifest

# Server-made events use this negative sequence number: the page only ever sends 0 or more, so it
# cannot clash with one of its own, and the unique (session, seq) key is what makes it "once".
INCOMPLETE_MARKER_SEQ = -1
# Sessions older than the window plus this are not looked at again: they have been checked every
# hour for a week, and re-reading a growing history forever would only slow the job.
LOOK_BACK_AFTER_WINDOW = timedelta(days=7)


def mark_incomplete_uploads(db: Session, clock: Clock, window_s: int) -> list[str]:
    """Record `upload_incomplete` on every session whose window has closed with chunks missing.
    Returns the session ids newly marked."""
    now = clock.now()
    window = timedelta(seconds=window_s)
    marked = select(Event.session_id).where(Event.client_seq == INCOMPLETE_MARKER_SEQ)
    candidates = db.scalars(
        select(TestSession).where(
            TestSession.status == "finished",
            TestSession.video_deleted_at.is_(None),
            TestSession.finished_at <= now - window,
            TestSession.finished_at >= now - window - LOOK_BACK_AFTER_WINDOW,
            TestSession.id.not_in(marked),
        )
    ).all()

    newly: list[str] = []
    for session in candidates:
        result = manifest(db, session)
        if result.complete:
            continue
        inserted = db.execute(
            pg_insert(Event)
            .values(
                session_id=session.id,
                client_seq=INCOMPLETE_MARKER_SEQ,
                type="upload_incomplete",
                # the moment the window closed and the gap became final
                server_ts=session.finished_at + window,
                received_at=now,
                payload={"missing": result.missing},
            )
            .on_conflict_do_nothing(index_elements=["session_id", "client_seq"])
            .returning(Event.id)
        ).first()
        if inserted is not None:
            newly.append(session.id)
    db.commit()
    return newly
