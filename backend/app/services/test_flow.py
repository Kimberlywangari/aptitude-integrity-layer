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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.core.security import hash_token, new_token
from app.errors import ApiError
from app.models import (
    Candidate,
    Heartbeat,
    Option,
    Question,
    QuestionImage,
    SessionQuestion,
    Sitting,
    TestSession,
)
from app.services import precheck
from app.services.flags.refresh import refresh_session_flags
from app.services.login import find_candidate
from app.services.qgen import jobs, paper
from app.services.question_modes import stored_questions
from app.services.shuffle import balanced_sample, blueprint_sample, session_rng, shuffle_options

# Every question gets 1.75 minutes. A sitting's whole time is its question count times this.
QUESTION_SECONDS = 105
# A test that is running cannot be taken over from another device unless its page has been silent
# this long (the heartbeat comes every 10 s), which also covers a crashed browser or a dead battery.
TAKEOVER_QUIET_S = 60


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
    question_remaining_s: float  # what is left of this question's QUESTION_SECONDS
    images: list[int]  # ids of the pictures the text's [[image N]] markers stand for, in order


@dataclass(frozen=True)
class Summary:
    total: int
    answered: int
    skipped: int
    unanswered: int


@dataclass(frozen=True)
class PaperView:
    status: str  # pending | ready | failed
    written: int
    total: int
    waited_s: int | None  # seconds since the paper was asked for; only while pending
    can_retry: bool  # failed, or pending for longer than the wait limit


# ---------------------------------------------------------------------------- paper building


def select_questions(
    db: Session,
    count: int,
    rng: random.Random,
    blueprint: dict[str, int] | None = None,
    mode: str = "bank",
) -> list[Question]:
    """Choose a paper: the blueprint's number from each section, or `count` spread evenly over the
    sections when the sitting has no blueprint. Only what the sitting's mode allows is drawn (a
    question written for one candidate is never drawn for another), and no more than two come from
    one reading passage. Kept behind this one function."""
    rows = db.execute(
        select(Question.id, Question.section, Question.passage_key).where(stored_questions(mode))
    ).all()
    by_section: dict[str, list[str]] = {}
    passages: dict[str, str] = {}
    for question_id, section, passage in rows:
        by_section.setdefault(section, []).append(question_id)
        if passage:
            passages[question_id] = passage
    try:
        if blueprint:
            ids = blueprint_sample(rng, by_section, blueprint, passages)
        else:
            ids = balanced_sample(rng, by_section, count, passages)
    except ValueError as exc:
        raise ApiError(503, "question_bank_too_small", detail=str(exc)) from exc
    by_id = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(ids)))}
    return [by_id[question_id] for question_id in ids]


def _build_paper(db: Session, session: TestSession, sitting: Sitting) -> None:
    questions = select_questions(
        db,
        sitting.question_count,
        session_rng(session.id, "paper"),
        sitting.blueprint,
        sitting.question_mode,
    )
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
    soonest: datetime | None = None
    for sitting in open_sittings:
        if sitting.opens_at and now < sitting.opens_at:
            soonest = min(soonest or sitting.opens_at, sitting.opens_at)
            continue
        if sitting.closes_at and now >= sitting.closes_at:
            continue
        return sitting
    if soonest is not None:  # one is on its way: say when, rather than "closed"
        raise ApiError(403, "sitting_not_open_yet", opens_at=soonest.isoformat())
    raise ApiError(403, "no_open_sitting")


def _sitting_for(db: Session, candidate: Candidate, now: datetime) -> Sitting:
    """The sitting this candidate's invitation opens. An invitation made for a sitting opens that
    one, whatever else is open; one made before sittings had their own opens the newest open one.
    Either way it must be open and inside its window."""
    if candidate.sitting_id is None:
        return _find_open_sitting(db, now)
    sitting = db.get(Sitting, candidate.sitting_id)
    if sitting is None or sitting.status != "open":
        raise ApiError(403, "no_open_sitting")
    if sitting.opens_at and now < sitting.opens_at:
        # not closed, just early: the candidate is told when to come back
        raise ApiError(403, "sitting_not_open_yet", opens_at=sitting.opens_at.isoformat())
    if sitting.closes_at and now >= sitting.closes_at:
        raise ApiError(403, "no_open_sitting")
    return sitting


def _refuse_takeover(db: Session, session: TestSession, now: datetime) -> None:
    """A test that is running, with a page that was heard from in the last TAKEOVER_QUIET_S, is
    open on some device: a second device does not get to replace its token and cut it off."""
    if session.status != "in_progress":
        return
    last = db.scalar(
        select(func.max(Heartbeat.server_ts)).where(Heartbeat.session_id == session.id)
    )
    last = max(filter(None, (last, session.started_at)), default=None)
    if last is not None and (now - last).total_seconds() < TAKEOVER_QUIET_S:
        wait = TAKEOVER_QUIET_S - int((now - last).total_seconds())
        raise ApiError(409, "test_open_elsewhere", retry_after_s=max(1, wait))


def start_session(
    db: Session,
    clock: Clock,
    invite_token: str | None,
    email: str | None = None,
    password: str | None = None,
    new_password: str | None = None,
) -> StartResult:
    """Exchange the sign-in (what it takes is in services/login.py) for a session and a fresh
    bearer token.

    Calling it again with the same invitation returns the same session (a reload or a restart
    never begins a second attempt) and replaces the bearer token, unless that session is running
    on a device that is still being heard from.
    """
    now = clock.now()
    candidate = find_candidate(db, invite_token, email, password, new_password)

    session = db.scalar(
        select(TestSession)
        .where(TestSession.candidate_id == candidate.id)
        .order_by(TestSession.created_at.desc())
        .with_for_update()
    )
    expired = False
    if session is not None and session.status != "finished":
        expired = _finish_if_expired(session, now)
        if not expired:
            _refuse_takeover(db, session, now)
    else:
        sitting = _sitting_for(db, candidate, now)
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
            if sitting.question_mode == "ai":
                # written in the background while the candidate reads and does the device check
                session.paper_status = "pending"
                session.paper_requested_at = now
            else:
                _build_paper(db, session, sitting)

    access_token = new_token()
    session.access_token_hash = hash_token(access_token)
    db.commit()
    if expired:
        refresh_session_flags(db, session.id)
    if session.paper_status == "pending":
        jobs.launch(session.id)  # a no-op if it is already being written
    return StartResult(session, access_token)


# ---------------------------------------------------------------------------- an AI-written paper


def waited_s(session: TestSession, now: datetime) -> int | None:
    """Seconds a pending paper has been waited for; None for a paper that is not pending."""
    if session.paper_status != "pending":
        return None
    since = session.paper_requested_at or session.created_at
    return max(0, int((now - since).total_seconds()))


def paper_view(
    db: Session, clock: Clock, session: TestSession, wait_limit_s: int = 600
) -> PaperView:
    """How far a candidate's paper has got. A paper still pending with nobody writing it (the
    server restarted) is picked up again here, so the candidate's page keeps it moving. After
    `wait_limit_s` of waiting the candidate may ask for the questions again."""
    written, total = paper.progress(db, session)
    if session.paper_status == "pending":
        jobs.launch(session.id)
    waited = waited_s(session, clock.now())
    stale = waited is not None and waited >= wait_limit_s
    can_retry = session.paper_status == "failed" or stale
    return PaperView(session.paper_status, written, total, waited, can_retry)


def retry_paper(
    db: Session, clock: Clock, session: TestSession, wait_limit_s: int = 600
) -> PaperView:
    """Ask for the questions again: after a failure, or after waiting longer than the limit. What
    was already written is kept and only the rest is written. Asking too early does nothing, so
    a tap on the button cannot restart work that is going well."""
    now = clock.now()
    waited = waited_s(session, now)
    if session.paper_status == "failed":
        session.paper_status = "pending"
        session.paper_error = None
        session.paper_requested_at = now
        db.commit()
    elif waited is not None and waited >= wait_limit_s:
        session.paper_requested_at = now
        db.commit()
        jobs.abandon(session.id)
    return paper_view(db, clock, session, wait_limit_s)


def begin(
    db: Session, clock: Clock, session: TestSession, accepted: bool, gate: str = "off"
) -> TestSession:
    """Candidate accepted the integrity statement: the timer starts now. Idempotent.

    `gate` is the camera and microphone gate (Settings.precheck_gate): with it on, the test cannot
    start until the pre-check has passed and, at `recording`, a real recording has arrived.
    """
    if not accepted:
        raise ApiError(422, "integrity_not_accepted")
    if session.status == "finished":
        raise ApiError(409, "finished")
    if session.status == "created":
        if session.paper_status != "ready":
            raise ApiError(409, "paper_not_ready", paper_status=session.paper_status)
        precheck.require_ready(db, session, gate)
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


def finish_expired(db: Session, clock: Clock, sitting_id: int | None = None) -> list[str]:
    """Finish every session whose time has run out but that nobody has touched since (a closed
    tab, a dead battery). Each finishes at the moment its time ran out. Flushes, never commits:
    the caller commits, then refreshes each returned session's flags. A session a candidate is
    using this very second is left to that request."""
    now = clock.now()
    query = select(TestSession).where(
        TestSession.status == "in_progress", TestSession.ends_at <= now
    )
    if sitting_id is not None:
        query = query.where(TestSession.sitting_id == sitting_id)
    expired = list(db.scalars(query.with_for_update(skip_locked=True)))
    for session in expired:
        _finish(session, session.ends_at)
    db.flush()
    return [session.id for session in expired]


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
        refresh_session_flags(db, session.id)
        raise ApiError(410, "time_up")
    if _close_timed_out(session, now):
        db.commit()
    return now


def _close_timed_out(session: TestSession, now: datetime) -> bool:
    """Close every question that stayed open for QUESTION_SECONDS. It is closed at the moment its
    time ran out, as skipped (no answer, so the timing rules leave it out), and the next question
    opens at that same moment, so a candidate who walks away loses questions as the time passes."""
    changed = False
    opened: datetime | None = None
    for sq in session.questions:
        if sq.answered_at is not None:
            continue
        if sq.opened_at is None:
            sq.opened_at = opened
        if sq.opened_at is None:
            break
        deadline = sq.opened_at + timedelta(seconds=QUESTION_SECONDS)
        if now < deadline:
            break
        sq.answered_at = deadline
        sq.skipped = True
        opened = deadline
        changed = True
    return changed


def _question_remaining(sq: SessionQuestion, session: TestSession, now: datetime) -> float:
    deadline = min(sq.opened_at + timedelta(seconds=QUESTION_SECONDS), session.ends_at)
    return max(0.0, round((deadline - now).total_seconds(), 1))


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
        refresh_session_flags(db, session.id)
        raise ApiError(409, "finished")
    if sq.opened_at is None:  # first view only; a reload must not restart the question clock
        sq.opened_at = now
        db.commit()
    question = db.get(Question, sq.question_id)
    options = {o.id: o for o in question.options}
    pictures: list[int] = []
    if question.source == "cytonn":  # the only questions that have any
        pictures = list(
            db.scalars(
                select(QuestionImage.id)
                .where(QuestionImage.question_id == question.id)
                .order_by(QuestionImage.position)
            )
        )
    return QuestionView(
        position=sq.position,
        total=len(session.questions),
        section=question.section,
        text=question.text,
        options=[(oid, options[oid].text) for oid in sq.option_order],
        remaining_s=_remaining(session, now),
        question_remaining_s=_question_remaining(sq, session, now),
        images=pictures,
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
    if done:
        refresh_session_flags(db, session.id)
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


def finish(
    db: Session, clock: Clock, session: TestSession, chunks_total: int | None = None
) -> Summary:
    """End the test (idempotent). Works after time-up too, so the page can collect its summary.

    `chunks_total` is how many video chunks the page made. The upload is complete when every
    chunk from 0 up to it has arrived, so it is kept (the latest value wins: the page may send it
    again once the recorder has flushed its last chunk).
    """
    if session.status == "created":
        raise ApiError(409, "not_started")
    just_finished = session.status == "in_progress"
    if just_finished:
        now = clock.now()
        _finish(session, min(now, session.ends_at))
    if chunks_total is not None:
        session.chunks_total = chunks_total
    db.commit()
    if just_finished:
        refresh_session_flags(db, session.id)
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
