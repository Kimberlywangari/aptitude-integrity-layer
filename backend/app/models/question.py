from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            "difficulty is null or difficulty in ('easy', 'medium', 'hard')", name="difficulty"
        ),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # e.g. Q001
    section: Mapped[str] = mapped_column(String(32))
    difficulty: Mapped[str | None] = mapped_column(String(10))
    correct_option: Mapped[str] = mapped_column(String(1))  # an option label: A, B, C, D
    text: Mapped[str] = mapped_column(Text)

    options: Mapped[list["Option"]] = relationship(
        back_populates="question", order_by="Option.label", cascade="all, delete-orphan"
    )
    stats: Mapped["QuestionStats | None"] = relationship(
        back_populates="question", uselist=False, cascade="all, delete-orphan"
    )


class Option(Base):
    __tablename__ = "options"
    __table_args__ = (UniqueConstraint("question_id", "label"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(1))
    text: Mapped[str] = mapped_column(Text)

    question: Mapped[Question] = relationship(back_populates="options")


class QuestionStats(Base):
    """Past-sitting statistics per question. `source` says where they came from."""

    __tablename__ = "question_stats"
    __table_args__ = (CheckConstraint("source in ('cytonn', 'synthetic')", name="source"),)

    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    n: Mapped[int] = mapped_column(Integer)
    pct_correct: Mapped[float] = mapped_column(Float)
    median_s: Mapped[float] = mapped_column(Float)
    p25_s: Mapped[float] = mapped_column(Float)
    p75_s: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(10))

    question: Mapped[Question] = relationship(back_populates="stats")
