from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            "difficulty is null or difficulty in ('easy', 'medium', 'hard')", name="difficulty"
        ),
        CheckConstraint("source in ('cytonn', 'synthetic', 'ai')", name="source"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # e.g. Q001, or C10 from Cytonn
    section: Mapped[str] = mapped_column(String(32))
    difficulty: Mapped[str | None] = mapped_column(String(10))
    correct_option: Mapped[str] = mapped_column(String(1))  # an option label: A, B, C...
    text: Mapped[str] = mapped_column(Text)
    # Where the question came from. `synthetic` is anything made up for the build (the seeded
    # practice questions); "retire practice questions" removes those. Not inferred from
    # the statistics, because a real question can have none. `ai` is a question written for one
    # candidate's paper: it is not part of the bank and every bank screen and count leaves it out.
    source: Mapped[str] = mapped_column(String(10), default="synthetic", server_default="synthetic")
    cytonn_id: Mapped[int | None] = mapped_column(Integer, unique=True)  # the aptitude API's id
    # Only for `ai` questions: the writer's working (shown to reviewers, never to candidates) and
    # which model wrote it, such as "ollama:qwen3:8b".
    explanation: Mapped[str | None] = mapped_column(Text)
    written_by: Mapped[str | None] = mapped_column(String(80))
    # Questions that hang off one reading passage share this key (the start of their text), so a
    # paper can take a few of them and not ten. None for a short question with no passage.
    passage_key: Mapped[str | None] = mapped_column(String(16), index=True)

    options: Mapped[list["Option"]] = relationship(
        back_populates="question", order_by="Option.label", cascade="all, delete-orphan"
    )
    stats: Mapped["QuestionStats | None"] = relationship(
        back_populates="question", uselist=False, cascade="all, delete-orphan"
    )
    images: Mapped[list["QuestionImage"]] = relationship(
        back_populates="question", order_by="QuestionImage.position", cascade="all, delete-orphan"
    )


class Option(Base):
    __tablename__ = "options"
    __table_args__ = (
        UniqueConstraint("question_id", "label"),
        # matched within a question only, so a repeated answer id elsewhere cannot break a load
        UniqueConstraint("question_id", "cytonn_id", name="uq_options_question_cytonn_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(1))
    text: Mapped[str] = mapped_column(Text)
    cytonn_id: Mapped[int | None] = mapped_column(Integer)  # the API's answer id

    question: Mapped[Question] = relationship(back_populates="options")


class QuestionImage(Base):
    """A picture a question depends on, kept as received from Cytonn. The text of the question
    says where it goes with a marker, `[[image 1]]`, whose number is the picture's position."""

    __tablename__ = "question_images"
    __table_args__ = (UniqueConstraint("question_id", "position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)  # 1-based, as in the marker
    content_type: Mapped[str] = mapped_column(String(40))
    sha256: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text)
    # Deferred: listing a question's pictures must not drag their bytes along.
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)

    question: Mapped[Question] = relationship(back_populates="images")


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
