"""The candidate's test: start, begin, one-way question flow, finish, self-report.

Rules (proposal): questions come one at a time, nobody can go back, the timer is the server's,
and a reload shows the same question with the same time left.

Session status: created (token issued, timer NOT running, integrity statement not accepted)
-> in_progress (timer running) -> finished. The timer starts at `begin`, not at `start`, so
reading the integrity statement and (from D6) the device pre-check never costs test time.
"""

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.core.security import hash_token, new_token, normalise_invite_code
from app.errors import ApiError
from app.models import Candidate, Option, Question, SessionQuestion, Sitting, TestSession
from app.services.shuffle import balanced_sample, session_rng, shuffle_options


@dataclass(frozen=True)
class StartResult:
    session: TestSession
    access_token: str


@dataclass(frozen=True)
class QuestionView:
    position: int
    total: int
    section: str
    text: str
    options: list[tuple[int, str]]  # (option id, text) in this candidate's order
    remaining_s: float


@dataclass(frozen=True)
class Summary:
    total: int
    answered: int
    skipped: int
    unanswered: int


# ---------------------------------------------------------------------------- paper building


def select_questions(db: Session, count: int, rng: random.Random) -> list[Question]:
    """Choose a paper. Kept behind this one function: the S1 blueprint generator replaces it."""
    rows = db.execute(select(Question.id, Question.section)).all()
    by_section: dict[str, list[str]] = {}
    for question_id, section in rows:
        by_section.setdefault(section, []).append(question_id)
    try:
        ids = balanced_sample(rng, by_section, count)
    except ValueError as exc:
        raise ApiError(503, "question_bank_too_small", detail=str(exc)) from exc
    by_id = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(ids)))}
    return [by_id[question_id] for question_id in ids]


def _build_paper(db: Session, session: TestSession, count: int) -> None:
    questions = select_questions(db, count, session_rng(session.id, "paper"))
    for position, question in enumerate(questions, start=1):
        option_ids = [o.id for o in sorted(question.options, key=lambda o: o.label)]
        db.add(
            SessionQuestion(
                session_id=session.id,
                position=position,
                question_id=question.id,
                option_order=shuffle_options(session.id, position, option_ids),
            )
        )


# ---------------------------------------------------------------------------- start / begin


def _find_open_sitting(db: Session, now: datetime) -> Sitting:
    open_sittings = db.scalars(
        select(Sitting).where(Sitting.status == "open").order_by(Sitting.id.desc())
    )
    for sitting in open_sittings:
        if sitting.opens_at and now < sitting.opens_at:
            continue
        if sitting.closes_at and now >= sitting.closes_at:
            continue
        return sitting
    raise ApiError(403, "no_open_sitting")


def start_session(db: Session, clock: Clock, invite_token: str) -> StartResult:
    """Exchange an invitation token for a session and a fresh bearer token.

    Calling it again with the same invitation returns the same session (a reload or a restart
    never begins a second attempt) and replaces the bearer token.
    """
    now = clock.now()
    candidate = db.scalar(
        select(Candidate).where(
            Candidate.invite_token_hash == hash_token(normalise_invite_code(invite_token))
        )
    )
    if candidate is None:
        raise ApiError(401, "invalid_invitation")

    session = db.scalar(
        select(TestSession)
        .where(TestSession.candidate_id == candidate.id)
        .order_by(TestSession.created_at.desc())
        .with_for_update()
    )
    if session is not None and session.status != "finished":
        _finish_if_expired(session, now)
    else:
        sitting = _find_open_sitting(db, now)
        same_sitting = db.scalar(
            select(TestSession)
            .where(TestSession.candidate_id == candidate.id, TestSession.sitting_id == sitting.id)
            .with_for_update()
        )
        if same_sitting is not None:
            session = same_sitting
        else:
            session = TestSession(
                id=uuid.uuid4().hex,
                candidate_id=candidate.id,
                sitting_id=sitting.id,
                status="created",
                created_at=now,
            )
            db.add(session)
            db.flush()
            _build_paper(db, session, sitting.question_count)

    access_token = new_token()
    session.access_token_hash = hash_token(access_token)
    db.commit()
    return StartResult(session, access_token)


def begin(db: Session, clock: Clock, session: TestSession, accepted: bool) -> TestSession:
    """Candidate accepted the integrity statement: the timer starts now. Idempotent."""
    if not accepted:
        raise ApiError(422, "integrity_not_accepted")
    if session.status == "finished":
        raise ApiError(409, "finished")
    if session.status == "created":
        now = clock.now()
        sitting = db.get(Sitting, session.sitting_id)
        session.integrity_accepted_at = now
        session.started_at = now
        session.ends_at = now + timedelta(seconds=sitting.duration_s)
        session.status = "in_progress"
        db.commit()
    return session


# ---------------------------------------------------------------------------- running a test


def _remaining(session: TestSession, now: datetime) -> float:
    return max(0.0, round((session.ends_at - now).total_seconds(), 1))


def _finish(session: TestSession, at: datetime) -> None:
    session.status = "finished"
    session.finished_at = at


def _finish_if_expired(session: TestSession, now: datetime) -> bool:
    if session.status == "in_progress" and now >= session.ends_at:
        _finish(session, session.ends_at)
        return True
    return False


def _ensure_running(db: Session, clock: Clock, session: TestSession) -> datetime:
    """Raise unless the test is running and inside its time; finish it if time has run out."""
    now = clock.now()
    if session.status == "created":
        raise ApiError(409, "not_started")
    if session.status == "finished":
        if session.ends_at and session.finished_at >= session.ends_at:
            raise ApiError(410, "time_up")
        raise ApiError(409, "finished")
    if _finish_if_expired(session, now):
        db.commit()
        raise ApiError(410, "time_up")
    return now


def _current(session: TestSession) -> SessionQuestion | None:
    """The first question not yet answered or skipped (questions are ordered by position)."""
    for sq in session.questions:
        if sq.answered_at is None:
            return sq
    return None


def get_question(db: Session, clock: Clock, session: TestSession) -> QuestionView:
    now = _ensure_running(db, clock, session)
    sq = _current(session)
    if sq is None:  # everything resolved but still marked in progress
        _finish(session, now)
        db.commit()
        raise ApiError(409, "finished")
    if sq.opened_at is None:  # first view only; a reload must not restart the question clock
        sq.opened_at = now
        db.commit()
    question = db.get(Question, sq.question_id)
    options = {o.id: o for o in question.options}
    return QuestionView(
        position=sq.position,
        total=len(session.questions),
        section=question.section,
        text=question.text,
        options=[(oid, options[oid].text) for oid in sq.option_order],
        remaining_s=_remaining(session, now),
    )


def _open_for(
    db: Session, clock: Clock, session: TestSession, position: int
) -> tuple[SessionQuestion, datetime]:
    """The current question, if `position` is it and the test is still running."""
    now = _ensure_running(db, clock, session)
    sq = _current(session)
    if sq is None or sq.position != position:
        raise ApiError(409, "not_current", current_position=sq.position if sq else None)
    return sq, now


def _mark_resolved(sq: SessionQuestion, now: datetime) -> None:
    if sq.opened_at is None:
        sq.opened_at = now
    sq.answered_at = now


def _after_resolve(db: Session, session: TestSession, now: datetime) -> tuple[bool, float]:
    """Finish the test when the last question is resolved. Returns (finished, remaining_s)."""
    done = all(sq.answered_at is not None for sq in session.questions)
    if done:
        _finish(session, now)
    db.commit()
    return done, 0.0 if done else _remaining(session, now)


def answer(
    db: Session,
    clock: Clock,
    session: TestSession,
    position: int,
    option_id: int,
) -> tuple[bool, float]:
    """Record an answer for the current question. Returns (test_finished, remaining_s)."""
    sq, now = _open_for(db, clock, session, position)
    if option_id not in sq.option_order:
        raise ApiError(422, "invalid_option")
    option = db.get(Option, option_id)
    question = db.get(Question, sq.question_id)
    _mark_resolved(sq, now)
    sq.selected_option = option_id
    sq.correct = option.label == question.correct_option
    return _after_resolve(db, session, now)


def skip(db: Session, clock: Clock, session: TestSession, position: int) -> tuple[bool, float]:
    sq, now = _open_for(db, clock, session, position)
    _mark_resolved(sq, now)
    sq.skipped = True
    return _after_resolve(db, session, now)


def summarise(session: TestSession) -> Summary:
    total = len(session.questions)
    skipped = sum(1 for sq in session.questions if sq.skipped)
    answered = sum(1 for sq in session.questions if sq.selected_option is not None)
    return Summary(total, answered, skipped, total - answered - skipped)


def score(session: TestSession) -> int:
    """Number of correct answers. Context for reviewers only, never shown to the candidate."""
    return sum(1 for sq in session.questions if sq.correct is True)


def finish(db: Session, clock: Clock, session: TestSession) -> Summary:
    """End the test (idempotent). Works after time-up too, so the page can collect its summary."""
    if session.status == "created":
        raise ApiError(409, "not_started")
    if session.status == "in_progress":
        now = clock.now()
        _finish(session, min(now, session.ends_at))
        db.commit()
    return summarise(session)


def save_self_report(
    db: Session, session: TestSession, had_technical_issues: bool, note: str | None
) -> None:
    if session.status != "finished":
        raise ApiError(409, "not_finished")
    session.self_report = {
        "had_technical_issues": had_technical_issues,
        "note": (note or "").strip()[:300],
    }
    db.commit()
