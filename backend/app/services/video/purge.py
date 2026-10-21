"""Deleting video 30 days after a reviewer's decision: the proposal's promise, and the one that must
hold even if everything else is broken.

The 30 days run from a session's *latest* decision, so a later decision extends them. The record
stays: the chunk rows, the flags, the packet and the decision are all kept; only the video bytes
go, and `sessions.video_deleted_at` says when. A candidate with no decision is never deleted here
(nothing says they are done with); `undecided_report` lists them so a person can decide.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session

from app.clock import Clock
from app.models import AuditLog, Decision, TestSession, VideoChunk, VideoSegment
from app.services.video.store import VideoStore


@dataclass
class PurgeResult:
    purged: list[str] = field(default_factory=list)  # session ids
    files_removed: int = 0


@dataclass(frozen=True)
class Undecided:
    candidate_id: str
    session_id: str
    finished_at: datetime
    age_days: int


def purge_due(
    db: Session, store: VideoStore, clock: Clock, retention_days: int
) -> PurgeResult:
    """Delete the video of every session whose latest decision is at least `retention_days` old.
    Safe to run as often as you like: a session already purged is not touched again."""
    now = clock.now()
    cutoff = now - timedelta(days=retention_days)
    latest = (
        select(Decision.session_id, func.max(Decision.decided_at).label("decided_at"))
        .group_by(Decision.session_id)
        .subquery()
    )
    has_video = exists().where(
        VideoChunk.session_id == TestSession.id, VideoChunk.deleted_at.is_(None)
    )
    due = db.execute(
        select(TestSession.id, latest.c.decided_at)
        .join(latest, latest.c.session_id == TestSession.id)
        .where(
            TestSession.video_deleted_at.is_(None),
            latest.c.decided_at <= cutoff,
            has_video,
        )
        .order_by(TestSession.id)
    ).all()

    result = PurgeResult()
    for session_id, decided_at in due:
        removed = store.delete_session(session_id)
        db.execute(
            update(VideoChunk)
            .where(VideoChunk.session_id == session_id, VideoChunk.deleted_at.is_(None))
            .values(deleted_at=now)
        )
        db.execute(
            update(VideoSegment).where(VideoSegment.session_id == session_id).values(path=None)
        )
        db.execute(
            update(TestSession).where(TestSession.id == session_id).values(video_deleted_at=now)
        )
        db.add(
            AuditLog(
                reviewer_id=None,
                action="video_purged",
                session_id=session_id,
                ts=now,
                detail=(
                    f"video deleted ({removed} files), {retention_days} days after the "
                    f"decision of {decided_at.date().isoformat()}"
                ),
            )
        )
        result.purged.append(session_id)
        result.files_removed += removed
    db.commit()
    return result


def undecided_report(db: Session, clock: Clock, older_than_days: int) -> list[Undecided]:
    """Finished sessions that still hold video, have no decision at all, and finished more than
    `older_than_days` ago. Nothing deletes these on its own, so a person decides."""
    now = clock.now()
    cutoff = now - timedelta(days=older_than_days)
    decided = exists().where(Decision.session_id == TestSession.id)
    has_video = exists().where(
        VideoChunk.session_id == TestSession.id, VideoChunk.deleted_at.is_(None)
    )
    rows = db.execute(
        select(TestSession.candidate_id, TestSession.id, TestSession.finished_at)
        .where(
            TestSession.status == "finished",
            TestSession.video_deleted_at.is_(None),
            TestSession.finished_at <= cutoff,
            ~decided,
            has_video,
        )
        .order_by(TestSession.finished_at)
    ).all()
    return [
        Undecided(candidate, session_id, finished, (now - finished).days)
        for candidate, session_id, finished in rows
    ]
