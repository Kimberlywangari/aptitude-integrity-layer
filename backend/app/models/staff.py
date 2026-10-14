from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Reviewer(Base):
    """A staff account: a reviewer, or an admin who can also set up sittings and invites."""

    __tablename__ = "reviewers"
    __table_args__ = (CheckConstraint("role in ('reviewer', 'admin')", name="role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # stored lower-case
    password_hash: Mapped[str] = mapped_column(String(100))  # bcrypt, 60 characters
    role: Mapped[str] = mapped_column(String(10), default="reviewer", server_default="reviewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """What staff did: sign-ins now, decisions and video views from D13."""

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(
            "action in ('login', 'decision', 'video_view', 'video_purged')", name="action"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # kept (set to null) if the account is ever removed, so the trail outlives the person
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("reviewers.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(20))
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"))
    # indexed: the audit view lists newest first
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    detail: Mapped[str | None] = mapped_column(Text)
