"""What the review screens are built from: the action log, heartbeats, flags, decisions and
complaints. Candidate IDs only; nothing here ever holds a name or the text of a question."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

OUTCOMES = ("no_concern", "concern_noted", "refer_for_follow_up")


class Event(Base):
    """One thing the page saw (focus lost, copy attempt, reload ...). `server_ts` is the server's
    receive time minus the event's age, so a late event keeps its true moment (master plan 7.3)."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("session_id", "client_seq"),
        Index("ix_events_session_id_server_ts", "session_id", "server_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    client_seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32))
    server_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Heartbeat(Base):
    """A tick every 10 s while the page is alive. A long hole with no explanation is a logging
    problem (master plan 7.4)."""

    __tablename__ = "heartbeats"
    __table_args__ = (Index("ix_heartbeats_session_id_server_ts", "session_id", "server_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    server_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Flag(Base):
    """Evidence for a reviewer, never a verdict. `source` is `rule` today; `ai` is reserved."""

    __tablename__ = "flags"
    __table_args__ = (CheckConstraint("source in ('rule', 'ai')", name="source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    weight: Mapped[float] = mapped_column(Float)
    server_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    position: Mapped[int | None] = mapped_column(Integer)  # question number, 1-based
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(10), default="rule", server_default="rule")


class Decision(Base):
    """A reviewer's written outcome. There can be several per session; the latest one counts."""

    __tablename__ = "decisions"
    __table_args__ = (
        CheckConstraint(
            "outcome in ('no_concern', 'concern_noted', 'refer_for_follow_up')", name="outcome"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    # kept (set to null) if the account is ever removed, so the decision outlives the person
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("reviewers.id", ondelete="SET NULL"))
    outcome: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Complaint(Base):
    """A candidate's own account of a camera, upload or other problem."""

    __tablename__ = "complaints"
    __table_args__ = (
        CheckConstraint("category in ('camera', 'upload', 'other')", name="category"),
        CheckConstraint("status in ('open', 'reviewed')", name="status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
