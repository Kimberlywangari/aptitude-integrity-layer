from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class TestSession(Base):
    """One candidate's attempt at one sitting.

    status: created (token issued, timer not running) -> in_progress (timer running)
    -> finished.
    """

    __test__ = False  # not a pytest class, despite the name
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("candidate_id", "sitting_id"),
        CheckConstraint("status in ('created', 'in_progress', 'finished')", name="status"),
        # the queue, the cohort checks and the sitting counts all look a sitting's sessions up
        Index("ix_sessions_sitting_id", "sitting_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"))
    sitting_id: Mapped[int] = mapped_column(ForeignKey("sittings.id"))
    status: Mapped[str] = mapped_column(String(12), default="created", server_default="created")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    integrity_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    precheck_passed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    precheck_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recording_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    self_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    shortlisted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    video_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    # Issued by POST /api/session/resume after the test is over. It opens the upload routes
    # (chunks, events, complaints) and nothing else, for as long as the resume window lasts.
    upload_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    # How many chunks the page says it produced, sent with `finish`. The upload is complete when
    # every number from 0 to this total has arrived.
    chunks_total: Mapped[int | None] = mapped_column(Integer)

    questions: Mapped[list["SessionQuestion"]] = relationship(
        back_populates="session", order_by="SessionQuestion.position", cascade="all, delete-orphan"
    )


class SessionQuestion(Base):
    """One question in a candidate's paper, in the order they see it."""

    __tablename__ = "session_questions"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)  # 1-based
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    option_order: Mapped[list[int]] = mapped_column(JSONB)  # option ids, as shown
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    selected_option: Mapped[int | None] = mapped_column(ForeignKey("options.id"))
    correct: Mapped[bool | None] = mapped_column(Boolean)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    session: Mapped[TestSession] = relationship(back_populates="questions")
