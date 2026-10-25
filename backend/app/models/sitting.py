from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Sitting(Base):
    """A scheduled group sitting of the same test (the cohort for D9's checks)."""

    __tablename__ = "sittings"
    __table_args__ = (
        CheckConstraint("status in ('open', 'closed')", name="status"),
        CheckConstraint(
            "question_mode in ('bank', 'practice', 'cytonn', 'ai')", name="question_mode"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    question_count: Mapped[int] = mapped_column(Integer)
    # How many questions each section contributes to a paper, e.g. {"verbal": 4, "logical": 4}.
    # question_count is their sum. None means the total is spread evenly over the sections.
    blueprint: Mapped[dict[str, int] | None] = mapped_column(JSONB(none_as_null=True))
    # Where a paper's questions come from. `cytonn`: Cytonn's own questions. `practice`: the
    # made-up bank, for trying things out. `bank`: any stored question (the original meaning, still
    # accepted). `ai`: written for each candidate when they open their invitation. Every mode but
    # `bank` needs a blueprint.
    question_mode: Mapped[str] = mapped_column(String(8), default="bank", server_default="bank")
    duration_s: Mapped[int] = mapped_column(Integer)
    # How many correct answers pass. None: no pass mark is set and nobody is turned down for a low
    # score. A person chooses it; changing it is previewed first (services/outcomes.py).
    pass_mark: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
