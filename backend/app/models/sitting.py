from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Sitting(Base):
    """A scheduled group sitting of the same test (the cohort for D9's checks)."""

    __tablename__ = "sittings"
    __table_args__ = (CheckConstraint("status in ('open', 'closed')", name="status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    question_count: Mapped[int] = mapped_column(Integer)
    # How many questions each section contributes to a paper, e.g. {"verbal": 4, "logical": 4}.
    # question_count is their sum. None means the total is spread evenly over the sections.
    blueprint: Mapped[dict[str, int] | None] = mapped_column(JSONB(none_as_null=True))
    duration_s: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
