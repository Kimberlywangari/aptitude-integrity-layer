"""A candidate's AI-written paper, written into the database.

The paper's shape is fixed by the sitting's blueprint before anything is written: categories in name
order (as a bank paper's sections are), each with its count, so question number 7 is always in the
same category. That is what makes writing resumable: after a restart, whatever positions already
hold a question are kept and only the empty ones are written.

Each batch is committed as it is accepted, so the candidate's page can show how far it has got, and
a failure part way loses nothing that was finished.
"""

import logging
import random
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Option, Question, SessionQuestion, Sitting, TestSession
from app.services.qgen import pipeline
from app.services.qgen.categories import CATEGORIES, difficulty_plan
from app.services.qgen.check import LABELS
from app.services.qgen.schema import Written
from app.services.qgen.writers import QuestionWriter, WriterError
from app.services.shuffle import session_rng, shuffle_options

log = logging.getLogger(__name__)

ERROR_MAX = 200


@dataclass(frozen=True)
class Slice:
    """Where one category sits in a paper."""

    category: str
    first: int  # position of its first question, 1-based
    count: int


def layout(blueprint: dict[str, int]) -> list[Slice]:
    """The paper, category by category, in name order."""
    slices: list[Slice] = []
    position = 1
    for key in sorted(blueprint):
        if blueprint[key] > 0:
            slices.append(Slice(key, position, blueprint[key]))
            position += blueprint[key]
    return slices


def progress(db: Session, session: TestSession) -> tuple[int, int]:
    """(questions written so far, questions the paper needs)."""
    sitting = db.get(Sitting, session.sitting_id)
    done = db.scalar(
        select(func.count())
        .select_from(SessionQuestion)
        .where(SessionQuestion.session_id == session.id)
    )
    return done or 0, sitting.question_count if sitting else 0


def _store(db: Session, session_id: str, position: int, item: Written, written_by: str) -> None:
    question = Question(
        id="G" + uuid.uuid4().hex[:15],
        section=item.category,
        difficulty=item.difficulty,
        correct_option=LABELS[item.correct_index],
        text=item.text,
        source="ai",
        explanation=item.explanation or None,
        written_by=written_by[:80],
    )
    question.options = [Option(label=LABELS[i], text=text) for i, text in enumerate(item.options)]
    db.add(question)
    db.flush()  # the options need their ids before the paper can point at them
    option_ids = [o.id for o in sorted(question.options, key=lambda o: o.label)]
    db.add(
        SessionQuestion(
            session_id=session_id,
            position=position,
            question_id=question.id,
            option_order=shuffle_options(session_id, position, option_ids),
        )
    )
    db.flush()


def _mark(db: Session, session_id: str, status: str, error: str | None = None) -> None:
    session = db.scalar(
        select(TestSession)
        .where(TestSession.id == session_id)
        .execution_options(populate_existing=True)
    )
    if session is not None:
        session.paper_status = status
        session.paper_error = error[:ERROR_MAX] if error else None
    db.commit()


def write_paper(
    db: Session,
    session_id: str,
    writer: QuestionWriter,
    solves: int = pipeline.SOLVES,
    timeout_s: float | None = None,
) -> str:
    """Write whatever is missing of a candidate's paper and mark it ready, or failed with the
    reason. Safe to run again after a stop; returns the status it left the session in."""
    session = db.get(TestSession, session_id)
    if session is None:
        return "missing"
    if session.paper_status == "ready":
        return "ready"
    sitting = db.get(Sitting, session.sitting_id)
    if sitting is None or sitting.question_mode != "ai" or not sitting.blueprint:
        _mark(db, session_id, "ready")  # nothing to write: a bank paper is built at once
        return "ready"

    written_by = f"{writer.name}:{writer.model}"
    deadline = time.monotonic() + timeout_s if timeout_s else None
    try:
        for part in layout(sitting.blueprint):
            have = (
                db.scalar(
                    select(func.count())
                    .select_from(SessionQuestion)
                    .where(
                        SessionQuestion.session_id == session_id,
                        SessionQuestion.position >= part.first,
                        SessionQuestion.position < part.first + part.count,
                    )
                )
                or 0
            )
            if have >= part.count:
                continue
            already = list(
                db.scalars(
                    select(Question.text)
                    .join(SessionQuestion, SessionQuestion.question_id == Question.id)
                    .where(SessionQuestion.session_id == session_id)
                    .order_by(SessionQuestion.position)
                )
            )
            plan = difficulty_plan(part.count)
            session_rng(session_id, f"qgen-mix:{part.category}").shuffle(plan)
            rng = random.Random(f"qgen:{session_id}:{part.category}:{have}")
            position = part.first + have
            for batch in pipeline.produce(
                writer,
                CATEGORIES[part.category],
                plan[have:],
                already,
                rng,
                solves=solves,
                deadline=deadline,
            ):
                for item in batch:
                    _store(db, session_id, position, item, written_by)
                    position += 1
                db.commit()  # this much is real now, and the page can say so
        _mark(db, session_id, "ready")
        return "ready"
    except IntegrityError:
        # another writer reached the same position first; it will finish the paper
        db.rollback()
        log.warning("paper for session %s is being written elsewhere", session_id)
        return "pending"
    except (pipeline.PaperFailed, WriterError) as problem:
        db.rollback()
        _mark(db, session_id, "failed", str(problem))
        log.warning("paper for session %s failed: %s", session_id, problem)
        return "failed"
    except Exception as problem:
        db.rollback()
        _mark(db, session_id, "failed", f"unexpected error: {type(problem).__name__}")
        log.exception("paper for session %s failed", session_id)
        return "failed"
