"""What is worked out about a sitting once it is over: the cohort baselines, each flagged
candidate's evidence packet, and the order the reviewer sees. Candidate IDs only."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

AI_STATUSES = ("not_run", "ok", "retried", "fallback")


class SittingStat(Base):
    """The baseline a sitting's cohort checks measured against (median and MAD of a metric)."""

    __tablename__ = "sitting_stats"
    __table_args__ = (
        UniqueConstraint("sitting_id", "metric"),
        CheckConstraint("metric in ('pace', 'spread')", name="metric"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sitting_id: Mapped[int] = mapped_column(ForeignKey("sittings.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(String(10))
    median: Mapped[float] = mapped_column(Float)
    mad: Mapped[float] = mapped_column(Float)
    n: Mapped[int] = mapped_column(Integer)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Packet(Base):
    """The evidence packet for a flagged candidate: what a reviewer, and the AI, are shown."""

    __tablename__ = "packets"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Ranking(Base):
    """A flagged candidate's place in the queue. The AI can reorder; it can never remove anyone,
    so every flagged session has exactly one row."""

    __tablename__ = "rankings"
    __table_args__ = (
        CheckConstraint("ai_status in ('not_run', 'ok', 'retried', 'fallback')", name="ai_status"),
    )

    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    sitting_id: Mapped[int] = mapped_column(
        ForeignKey("sittings.id", ondelete="CASCADE"), index=True
    )
    rule_score: Mapped[float] = mapped_column(Float)
    rule_rank: Mapped[int] = mapped_column(Integer)
    # a record gap with no other evidence: kept in a lane of its own at the bottom of the queue
    logging_only: Mapped[bool] = mapped_column(default=False, server_default="false")
    ai_status: Mapped[str] = mapped_column(String(10), default="not_run", server_default="not_run")
    # none_as_null: no answer is a true SQL NULL, not the JSON value null, so `IS NULL` works
    ai_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # every attempt, with the raw output and what the fact check objected to, kept for audit
    ai_attempts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB(none_as_null=True))
    ai_seconds: Mapped[float | None] = mapped_column(Float)
    final_rank: Mapped[int] = mapped_column(Integer)
    # the plain account of what the rules found; shown when the AI step did not produce one
    explanation: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(16), default="rules", server_default="rules")
    model: Mapped[str | None] = mapped_column(String(64))
    ranked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
