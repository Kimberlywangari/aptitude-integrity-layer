"""A candidate's own account of a camera, upload or other problem. A person reads it next to the
candidate's record; it never changes a flag or a rank by itself."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.errors import ApiError
from app.models import Complaint, TestSession
from app.schemas.recording import MAX_COMPLAINT_CHARS

CATEGORIES = ("camera", "upload", "other")
MAX_PER_SESSION = 10  # a stuck retry loop or a mischievous page cannot fill the table


def file_complaint(
    db: Session, clock: Clock, session: TestSession, category: str, text: str
) -> None:
    body = text.strip()
    if category not in CATEGORIES or not body or len(body) > MAX_COMPLAINT_CHARS:
        raise ApiError(422, "invalid_complaint")
    filed = db.scalar(
        select(func.count()).select_from(Complaint).where(Complaint.session_id == session.id)
    )
    if filed >= MAX_PER_SESSION:
        raise ApiError(429, "too_many_complaints")
    db.add(
        Complaint(
            session_id=session.id,
            category=category,
            text=body,
            created_at=clock.now(),
            status="open",
        )
    )
    db.commit()
