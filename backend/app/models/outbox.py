from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EmailOutbox(Base):
    """An email waiting to go, or already gone. One row per (candidate, kind), so a candidate is
    never sent the same email twice. `test` rows have no candidate.

    An `invite` body holds the live invitation code, which exists nowhere else in the clear, so a
    sent email's body is set to null the moment it is sent."""

    __tablename__ = "email_outbox"
    __table_args__ = (
        UniqueConstraint("candidate_id", "kind", name="uq_outbox_candidate_kind"),
        # the outcomes list and the sender both look rows up by kind and state
        Index("ix_email_outbox_kind_status", "kind", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(12))  # invite | passed | not_passed | test
    to_address: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(8), default="queued", server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
