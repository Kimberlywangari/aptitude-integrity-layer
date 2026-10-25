"""Finishing an upload after the test is over.

The test is over once it is finished, but the video may not be all on the server: a tab was
closed, the connection was poor. For 48 hours the candidate can open their invitation again and
get a token that does one thing, upload. It cannot read a question or change an answer.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.core.security import hash_token, new_token
from app.errors import ApiError
from app.models import TestSession
from app.services.login import find_candidate


@dataclass(frozen=True)
class ResumeResult:
    session: TestSession
    upload_token: str
    expires_at: datetime


def issue_upload_token(
    db: Session,
    clock: Clock,
    invite_code: str | None,
    window_s: int,
    email: str | None = None,
    password: str | None = None,
    new_password: str | None = None,
) -> ResumeResult:
    candidate = find_candidate(db, invite_code, email, password, new_password)

    session = db.scalar(
        select(TestSession)
        .where(TestSession.candidate_id == candidate.id, TestSession.status == "finished")
        .order_by(TestSession.finished_at.desc())
        .limit(1)
        .with_for_update()
    )
    if session is None or session.finished_at is None:
        # nothing has finished yet: the ordinary start page is the right place
        raise ApiError(409, "nothing_to_resume")

    expires_at = session.finished_at + timedelta(seconds=window_s)
    now = clock.now()
    if now > expires_at:
        raise ApiError(410, "resume_window_closed")

    token = new_token()
    session.upload_token_hash = hash_token(token)
    db.commit()
    return ResumeResult(session, token, expires_at)
