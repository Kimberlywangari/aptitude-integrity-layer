"""Reads each session's record from the database, runs the rules and stores the flags.

Computing is idempotent: a run replaces that session's earlier `rule` flags, so it can be repeated
after a threshold changes or more data arrives. Flags are evidence, nothing more. This module
never writes a decision, a rank or a score into the database; those are worked out when read.
"""

import statistics
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clock import Clock, SystemClock
from app.models import (
    Event,
    Flag,
    Heartbeat,
    Question,
    QuestionStats,
    SessionQuestion,
    Sitting,
    SittingStat,
    TestSession,
)
from app.services.flags import rules
from app.services.flags.config import DEFAULTS, FlagConfig


@dataclass
class SessionRecord:
    session: TestSession
    answers: list[rules.Answer]
    events: list[rules.Ev]
    beats: list[datetime]
    start: datetime | None
    end: datetime | None


@dataclass
class FlagRun:
    sessions: int = 0
    flags: int = 0
    flagged: int = 0
    cohort_applied: bool = False


def load_record(db: Session, session: TestSession) -> SessionRecord:
    rows = db.execute(
        select(
            SessionQuestion,
            Question.difficulty,
            QuestionStats.p25_s,
            QuestionStats.n,
            QuestionStats.source,
        )
        .join(Question, Question.id == SessionQuestion.question_id)
        .outerjoin(QuestionStats, QuestionStats.question_id == SessionQuestion.question_id)
        .where(SessionQuestion.session_id == session.id)
        .order_by(SessionQuestion.position)
    ).all()
    answers = [
        rules.Answer(
            position=sq.position,
            question_id=sq.question_id,
            difficulty=difficulty,
            opened_at=sq.opened_at,
            answered_at=sq.answered_at,
            correct=sq.correct,
            skipped=sq.skipped,
            p25_s=p25,
            stats_n=n,
            stats_source=source,
        )
        for sq, difficulty, p25, n, source in rows
    ]
    events = [
        rules.Ev(e.type, e.server_ts, e.payload or {})
        for e in db.scalars(
            select(Event).where(Event.session_id == session.id).order_by(Event.server_ts)
        )
    ]
    beats = list(
        db.scalars(
            select(Heartbeat.server_ts)
            .where(Heartbeat.session_id == session.id)
            .order_by(Heartbeat.server_ts)
        )
    )
    last_answer = max((a.answered_at for a in answers if a.answered_at), default=None)
    return SessionRecord(
        session=session,
        answers=answers,
        events=events,
        beats=beats,
        start=session.started_at,
        end=session.finished_at or last_answer,
    )


def session_drafts(record: SessionRecord, cfg: FlagConfig = DEFAULTS) -> list[rules.FlagDraft]:
    """Every per-session rule, in time order. Cohort rules need the whole sitting."""
    losses = rules.focus_losses(record.events, record.end)
    idles = rules.idle_spans(record.events)
    drops = rules.connection_drops(record.events, record.end)
    gaps = rules.heartbeat_gaps(record.beats, record.start, record.end, cfg)

    drafts: list[rules.FlagDraft] = []
    drafts += rules.focus_loss_flags(losses, record.answers, cfg)
    drafts += rules.copy_attempt_flags(record.events, record.answers, cfg)
    drafts += rules.long_hold_correct_flags(record.answers, losses, cfg)
    drafts += rules.correct_run_after_gap_flags(
        record.answers, rules.run_gaps(losses, idles, cfg), cfg
    )
    drafts += rules.fast_correct_flags(record.answers, cfg)
    drafts += rules.logging_problem_flags(gaps, drops, record.events, cfg)
    return sorted(drafts, key=lambda d: d.ts)


def answer_times(record: SessionRecord) -> list[float]:
    return [
        a.time_s for a in record.answers if a.time_s is not None and not a.skipped
    ]


def cohort_member(record: SessionRecord) -> rules.CohortMember | None:
    times = answer_times(record)
    if len(times) < 2:
        return None
    return rules.CohortMember(
        key=record.session.id,
        mean_s=statistics.fmean(times),
        spread_s=statistics.pstdev(times),
        ts=record.end or record.start or record.session.created_at,
    )


def _store(db: Session, session_id: str, drafts: list[rules.FlagDraft]) -> None:
    db.execute(delete(Flag).where(Flag.session_id == session_id, Flag.source == "rule"))
    for draft in drafts:
        db.add(
            Flag(
                session_id=session_id,
                kind=draft.kind,
                weight=draft.weight,
                server_ts=draft.ts,
                position=draft.position,
                detail=draft.detail,
                source="rule",
            )
        )


def _store_baselines(
    db: Session, sitting_id: int, members: list[rules.CohortMember], now: datetime, cfg: FlagConfig
) -> None:
    """Keep the median and MAD each cohort check measured against, so a flag can be traced back to
    the baseline it was judged on. Cleared when the group is too small to have one."""
    db.execute(delete(SittingStat).where(SittingStat.sitting_id == sitting_id))
    if len(members) < cfg.cohort_min_candidates:
        return
    for metric, values in (
        ("pace", [m.mean_s for m in members]),
        ("spread", [m.spread_s for m in members]),
    ):
        median, mad = rules.baseline(values)
        db.add(
            SittingStat(
                sitting_id=sitting_id,
                metric=metric,
                median=median,
                mad=mad,
                n=len(values),
                computed_at=now,
            )
        )


def compute_sitting_flags(
    db: Session, sitting_id: int, cfg: FlagConfig = DEFAULTS, clock: Clock | None = None
) -> FlagRun:
    """Recompute every finished session's flags in a sitting. The cohort rules (pace, spread)
    only run once the sitting is closed and has enough candidates, because a comparison with an
    unfinished or tiny group is not a fair one."""
    sitting = db.get(Sitting, sitting_id)
    if sitting is None:
        raise ValueError(f"no sitting {sitting_id}")
    now = (clock or SystemClock()).now()

    sessions = list(
        db.scalars(
            select(TestSession)
            .where(TestSession.sitting_id == sitting_id, TestSession.status == "finished")
            .order_by(TestSession.id)
        )
    )
    records = [load_record(db, s) for s in sessions]
    drafts = {r.session.id: session_drafts(r, cfg) for r in records}

    run = FlagRun(sessions=len(records))
    if sitting.status == "closed":
        members = [m for m in (cohort_member(r) for r in records) if m is not None]
        extra = rules.cohort_flags(members, cfg)
        run.cohort_applied = len(members) >= cfg.cohort_min_candidates
        _store_baselines(db, sitting_id, members, now, cfg)
        for session_id, more in extra.items():
            drafts[session_id] = sorted([*drafts[session_id], *more], key=lambda d: d.ts)

    for session_id, found in drafts.items():
        _store(db, session_id, found)
        run.flags += len(found)
        run.flagged += 1 if found else 0
    db.flush()
    return run


def compute_session_flags(
    db: Session, session_id: str, cfg: FlagConfig = DEFAULTS
) -> list[rules.FlagDraft]:
    """One session's own flags (no cohort rules). Replaces its earlier rule flags."""
    session = db.get(TestSession, session_id)
    if session is None:
        raise ValueError(f"no session {session_id}")
    found = session_drafts(load_record(db, session), cfg)
    _store(db, session_id, found)
    db.flush()
    return found
