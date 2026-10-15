"""What the reviewer screens read: the ranked queue, one candidate's page, and the few things a
reviewer can write (a decision, the shortlist, a note that they opened the video).

Everything is derived from stored sessions and flags when it is asked for. Ranks and scores are
never stored, so they cannot go stale after a threshold or a flag changes. The order is a
convenience for a person; nothing here sets anyone aside.
"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.errors import ApiError
from app.models import (
    AuditLog,
    Complaint,
    Decision,
    Event,
    Flag,
    QuestionStats,
    Reviewer,
    SessionQuestion,
    Sitting,
    TestSession,
)
from app.schemas.review import MAX_REASON_CHARS, MIN_REASON_CHARS
from app.services.flags import rules
from app.services.flags.config import DEFAULTS, FlagConfig
from app.services.flags.scoring import Line, ScoredFlag, is_logging_only, score_flags

OUTCOMES = ("no_concern", "concern_noted", "refer_for_follow_up")
PURGE_AFTER = timedelta(days=30)  # video goes 30 days after a decision (the proposal's promise)


@dataclass
class Ranked:
    session: TestSession
    flags: list[Flag]
    score: float
    lines: list[Line]
    logging_only: bool
    rank: int = 0
    kinds: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------ helpers


def _elapsed(ts: datetime, start: datetime | None) -> int:
    if start is None:
        return 0
    return round((ts - start).total_seconds())


def seek_for(segments: list[dict[str, float]], elapsed_s: float) -> dict[str, float] | None:
    """Where a moment sits in the saved video: the segment holding it and 5 s before. None when
    nothing was recorded then (no video yet, or the moment falls in a gap between segments)."""
    for index, segment in enumerate(segments):
        start, length = segment["start_s"], segment["duration_s"]
        if start <= elapsed_s <= start + length:
            return {"segment": index, "seek_s": max(0.0, elapsed_s - start - 5)}
    return None


def _flags_for(db: Session, session_ids: list[str]) -> dict[str, list[Flag]]:
    out: dict[str, list[Flag]] = {sid: [] for sid in session_ids}
    if not session_ids:
        return out
    rows = db.scalars(
        select(Flag).where(Flag.session_id.in_(session_ids)).order_by(Flag.server_ts, Flag.id)
    )
    for flag in rows:
        out[flag.session_id].append(flag)
    return out


def _latest_decisions(db: Session, session_ids: list[str]) -> dict[str, Decision]:
    latest: dict[str, Decision] = {}
    if not session_ids:
        return latest
    rows = db.scalars(
        select(Decision)
        .where(Decision.session_id.in_(session_ids))
        .order_by(Decision.decided_at, Decision.id)
    )
    for decision in rows:
        latest[decision.session_id] = decision  # later rows replace earlier ones
    return latest


# ---------------------------------------------------------------------------------- the queue


def rank_sitting(db: Session, sitting_id: int, cfg: FlagConfig = DEFAULTS) -> list[Ranked]:
    """Flagged, finished sessions in order: most evidence first, a gap in the record last."""
    sessions = list(
        db.scalars(
            select(TestSession).where(
                TestSession.sitting_id == sitting_id, TestSession.status == "finished"
            )
        )
    )
    flags = _flags_for(db, [s.id for s in sessions])
    ranked: list[Ranked] = []
    for session in sessions:
        found = flags[session.id]
        if not found:
            continue
        scored = [
            ScoredFlag(f"F{i}", f.kind, f.weight, _elapsed(f.server_ts, session.started_at))
            for i, f in enumerate(found, start=1)
        ]
        total, lines = score_flags(scored, cfg)
        kinds = [f.kind for f in found]
        ranked.append(Ranked(session, found, total, lines, is_logging_only(kinds), kinds=kinds))
    ranked.sort(key=lambda r: (r.logging_only, -r.score, r.session.candidate_id))
    for position, item in enumerate(ranked, start=1):
        item.rank = position
    return ranked


def default_sitting_id(db: Session) -> int:
    """The newest sitting that has flagged candidates, else the first sitting, else 0."""
    flagged = db.scalar(
        select(func.max(TestSession.sitting_id))
        .join(Flag, Flag.session_id == TestSession.id)
        .where(TestSession.status == "finished")
    )
    if flagged is not None:
        return int(flagged)
    first = db.scalar(select(func.min(Sitting.id)))
    return int(first) if first is not None else 0


def queue(db: Session, sitting_id: int | None, cfg: FlagConfig = DEFAULTS) -> dict[str, Any]:
    sittings = [
        {"id": s.id, "name": s.name} for s in db.scalars(select(Sitting).order_by(Sitting.id))
    ]
    known = {s["id"] for s in sittings}
    chosen = sitting_id if sitting_id in known else default_sitting_id(db)
    ranked = rank_sitting(db, chosen, cfg) if chosen else []
    decisions = _latest_decisions(db, [r.session.id for r in ranked])
    items = []
    for item in ranked:
        decision = decisions.get(item.session.id)
        items.append(
            {
                "candidate_id": item.session.candidate_id,
                "rank": item.rank,
                "rule_score": item.score,
                "ai_strength": None,  # the AI step is not built; the order is rules only
                "ai_status": "not_run",
                "flag_kinds": item.kinds,
                "decision": decision.outcome if decision else None,
                "shortlisted": item.session.shortlisted,
                "logging_only": item.logging_only,
            }
        )
    return {"sittings": sittings, "sitting_id": chosen, "items": items}


# ------------------------------------------------------------------------- one candidate's page


def _find_session(db: Session, candidate_id: str, sitting_id: int | None) -> TestSession:
    query = select(TestSession).where(TestSession.candidate_id == candidate_id)
    if sitting_id is not None:
        query = query.where(TestSession.sitting_id == sitting_id)
    query = query.order_by(TestSession.created_at.desc())
    session = db.scalars(query).first()
    if session is None:
        raise ApiError(404, "candidate_not_found")
    return session


def _answer_times(rows: list[Any]) -> list[float]:
    return [
        (r.answered_at - r.opened_at).total_seconds()
        for r in rows
        if r.opened_at is not None and r.answered_at is not None and not r.skipped
    ]


def _vs_sitting(
    db: Session, session: TestSession, cfg: FlagConfig
) -> tuple[dict[str, Any], float, int]:
    """Percentiles against the sitting, plus this candidate's pace and score."""
    rows = db.execute(
        select(
            SessionQuestion.session_id,
            SessionQuestion.opened_at,
            SessionQuestion.answered_at,
            SessionQuestion.correct,
            SessionQuestion.skipped,
        )
        .join(TestSession, TestSession.id == SessionQuestion.session_id)
        .where(TestSession.sitting_id == session.sitting_id, TestSession.status == "finished")
    ).all()
    by_session: dict[str, list[Any]] = {}
    for row in rows:
        by_session.setdefault(row.session_id, []).append(row)

    paces: dict[str, float] = {}
    spreads: dict[str, float] = {}
    scores: dict[str, float] = {}
    for sid, items in by_session.items():
        times = _answer_times(items)
        scores[sid] = float(sum(1 for r in items if r.correct is True))
        if times:
            paces[sid] = statistics.fmean(times)
            spreads[sid] = statistics.pstdev(times) if len(times) > 1 else 0.0

    own_pace = paces.get(session.id, 0.0)
    own_score = int(scores.get(session.id, 0))
    if len(paces) < cfg.cohort_min_candidates:
        return {"cohort_skipped": "too_small"}, own_pace, own_score
    return (
        {
            "pace_percentile": rules.percentile_of(list(paces.values()), own_pace),
            "spread_percentile": rules.percentile_of(
                list(spreads.values()), spreads.get(session.id, 0.0)
            ),
            "score_percentile": rules.percentile_of(list(scores.values()), own_score),
        },
        own_pace,
        own_score,
    )


def _signals(events: list[Event], start: datetime | None, end: datetime | None, cfg: FlagConfig):
    """Context a reviewer should weigh: drops, reloads, device trouble, and mic silences."""
    evs = [rules.Ev(e.type, e.server_ts, e.payload or {}) for e in events]
    innocent: list[dict[str, Any]] = []
    counter = 0

    def add(**fields: Any) -> None:
        nonlocal counter
        counter += 1
        innocent.append({"id": f"I{counter}", **fields})

    for span in rules.connection_drops(evs, end):
        add(
            kind="connection_lost",
            elapsed_s=_elapsed(span.start, start),
            duration_s=round(span.duration_s),
        )
    for event in evs:
        if event.type == "reload":
            add(kind="reload", elapsed_s=_elapsed(event.ts, start))
        elif event.type in ("camera_dropped", "track_ended"):
            add(
                kind=event.type,
                elapsed_s=_elapsed(event.ts, start),
                duration_s=round(float(event.payload.get("duration_s", 0) or 0)),
            )

    silences: list[dict[str, Any]] = []
    spans = rules.pair_spans(evs, "mic_silent_start", "mic_silent_end", end)
    spans += rules.pair_spans(evs, "mic_muted", "mic_unmuted", end)
    for span in sorted(spans, key=lambda s: s.start):
        if span.duration_s < cfg.mic_silence_min_s:
            continue
        silences.append(
            {
                "id": f"M{len(silences) + 1}",
                "start_s": _elapsed(span.start, start),
                "end_s": _elapsed(span.end, start),
                "duration_s": round(span.duration_s),
                "layers": ["browser"],
                "video_seek": None,
            }
        )
    innocent.sort(key=lambda s: s.get("elapsed_s", 0))
    return innocent, silences


_DESCRIBE = {
    "COPY_ATTEMPT": lambda d, q, on: f"a copy attempt{on} ({d.get('length', 0)} characters)",
    "FOCUS_LOSS": lambda d, q, on: f"a {d.get('focus_lost_s', 0)} s loss of focus{on}",
    "LONG_HOLD_CORRECT": lambda d, q, on: (
        f"question {q} took {d.get('time_s')} s against the candidate's own median of "
        f"{d.get('own_median_s')} s and was answered correctly"
    ),
    "CORRECT_RUN_AFTER_GAP": lambda d, q, on: (
        f"{d.get('run_length')} correct answers in a row straight after a {d.get('gap_s')} s gap"
    ),
    "FAST_CORRECT_VS_HISTORY": lambda d, q, on: (
        f"{len(d.get('questions', []))} correct answers much faster than the usual quick time "
        "for those questions"
    ),
    "PACE_OUTLIER": lambda d, q, on: (
        f"a mean time per question far {'faster' if d.get('direction') == 'fast' else 'slower'} "
        "than the rest of the sitting"
    ),
    "SPREAD_OUTLIER": lambda d, q, on: (
        f"answer times far {'narrower' if d.get('direction') == 'narrow' else 'wider'} "
        "than the rest of the sitting"
    ),
    "LOGGING_PROBLEM": lambda d, q, on: (
        f"no heartbeat for {d.get('heartbeat_gap_s')} s that a dropped connection or reload "
        "does not explain"
    ),
}


def rules_explanation(flags: list[dict[str, Any]], n_signals: int) -> str:
    """A plain account of what the rules found, built only from the flags' own numbers. It names
    what happened and never says what it means about the person."""
    parts = []
    for flag in flags:
        q = flag["question_number"]
        on = f" on question {q}" if q else ""
        describe = _DESCRIBE.get(flag["kind"])
        parts.append(describe(flag["detail"], q, on) if describe else flag["kind"].lower())
    text = "Rules only: " + "; ".join(parts) + "."
    if n_signals:
        noun = "signal" if n_signals == 1 else "signals"
        text += f" The record also shows {n_signals} {noun} with an ordinary explanation to weigh."
    return text


def candidate_detail(
    db: Session, candidate_id: str, sitting_id: int | None, cfg: FlagConfig = DEFAULTS
) -> dict[str, Any]:
    session = _find_session(db, candidate_id, sitting_id)
    flags = _flags_for(db, [session.id])[session.id]

    ranked = {r.session.id: r for r in rank_sitting(db, session.sitting_id, cfg)}
    this = ranked.get(session.id)
    if this is not None:
        score_total, lines, rank = this.score, this.lines, this.rank
    else:
        scored = [
            ScoredFlag(f"F{i}", f.kind, f.weight, _elapsed(f.server_ts, session.started_at))
            for i, f in enumerate(flags, start=1)
        ]
        score_total, lines = score_flags(scored, cfg)
        rank = 0

    flag_items = [
        {
            "id": f"F{i}",
            "kind": f.kind,
            "server_ts": f.server_ts,
            "elapsed_s": _elapsed(f.server_ts, session.started_at),
            "question_number": f.position,
            "detail": f.detail,
            "video_seek": None,  # no video is stored yet
        }
        for i, f in enumerate(flags, start=1)
    ]

    events = list(
        db.scalars(select(Event).where(Event.session_id == session.id).order_by(Event.server_ts))
    )
    last_answer = db.scalar(
        select(func.max(SessionQuestion.answered_at)).where(
            SessionQuestion.session_id == session.id
        )
    )
    end = session.finished_at or last_answer
    innocent, silences = _signals(events, session.started_at, end, cfg)

    report = session.self_report or None
    if report and report.get("had_technical_issues"):
        innocent.append(
            {
                "id": f"I{len(innocent) + 1}",
                "kind": "self_report",
                "category": "technical_issue",
                "note": (report.get("note") or "")[:120],
            }
        )

    vs, pace, score = _vs_sitting(db, session, cfg)

    sources = set(
        db.scalars(
            select(QuestionStats.source)
            .join(SessionQuestion, SessionQuestion.question_id == QuestionStats.question_id)
            .where(SessionQuestion.session_id == session.id)
        )
    )
    history = "cytonn" if sources == {"cytonn"} else "synthetic"

    complaints = [
        {
            "id": f"K{c.id}",
            "category": c.category,
            "text": c.text,
            "created_at": c.created_at,
            "status": c.status,
        }
        for c in db.scalars(
            select(Complaint).where(Complaint.session_id == session.id).order_by(Complaint.id)
        )
    ]

    decision_rows = db.execute(
        select(Decision, Reviewer.email)
        .outerjoin(Reviewer, Reviewer.id == Decision.reviewer_id)
        .where(Decision.session_id == session.id)
        .order_by(Decision.decided_at, Decision.id)
    ).all()
    decisions = [
        {
            "outcome": d.outcome,
            "reason": d.reason,
            "reviewer": email or "removed account",
            "decided_at": d.decided_at,
        }
        for d, email in decision_rows
    ]
    purge_on = None
    if decisions and session.video_deleted_at is None:
        purge_on = decisions[-1]["decided_at"] + PURGE_AFTER

    explanation = {
        "source": "rules",
        "status": "not_run",
        "text": rules_explanation(flag_items, len(innocent)) if flag_items else
        "Rules only: no flags were raised for this candidate.",
        "strength": None,
        "flags_support_each_other": None,
    }

    return {
        "session_id": session.id,
        "candidate_id": session.candidate_id,
        "rank": rank,
        "rule_score": score_total,
        "rule_breakdown": [{"label": ln.label, "points": ln.points} for ln in lines],
        "score": score,
        "pace_s_per_q": round(pace, 1),
        "history_source": history,
        "flags": flag_items,
        "vs_sitting": vs,
        "innocent_signals": innocent,
        "mic_silence": silences,
        "self_report": (
            {
                "had_technical_issues": bool(report.get("had_technical_issues")),
                "note": report.get("note"),
            }
            if report
            else None
        ),
        "explanation": explanation,
        "complaints": complaints,
        "decisions": decisions,
        "shortlisted": session.shortlisted,
        "segments": [],  # no video is stored yet
        "video_deleted_at": session.video_deleted_at,
        "video_purge_on": purge_on,
    }


# ------------------------------------------------------------------------------------ writing


def _audit(
    db: Session, clock: Clock, reviewer: Reviewer, action: str, session_id: str | None, detail: str
) -> None:
    db.add(
        AuditLog(
            reviewer_id=reviewer.id,
            action=action,
            session_id=session_id,
            ts=clock.now(),
            detail=detail,
        )
    )


def record_decision(
    db: Session, clock: Clock, reviewer: Reviewer, session_id: str, outcome: str, reason: str
) -> datetime:
    """A reviewer's written outcome. It needs a real reason, and it is kept with who and when."""
    if outcome not in OUTCOMES:
        raise ApiError(422, "invalid_outcome")
    reason = reason.strip()
    if len(reason) < MIN_REASON_CHARS:
        raise ApiError(422, "reason_too_short", min=MIN_REASON_CHARS)
    if len(reason) > MAX_REASON_CHARS:
        raise ApiError(422, "reason_too_long", max=MAX_REASON_CHARS)
    if db.get(TestSession, session_id) is None:
        raise ApiError(404, "candidate_not_found")

    now = clock.now()
    db.add(
        Decision(
            session_id=session_id,
            reviewer_id=reviewer.id,
            outcome=outcome,
            reason=reason,
            decided_at=now,
        )
    )
    _audit(db, clock, reviewer, "decision", session_id, outcome)
    db.flush()
    return now


def toggle_shortlist(
    db: Session, clock: Clock, reviewer: Reviewer, candidate_id: str, sitting_id: int | None
) -> bool:
    session = _find_session(db, candidate_id, sitting_id)
    session.shortlisted = not session.shortlisted
    _audit(
        db,
        clock,
        reviewer,
        "decision",
        session.id,
        "shortlisted" if session.shortlisted else "removed from shortlist",
    )
    db.flush()
    return session.shortlisted


def record_video_view(
    db: Session,
    clock: Clock,
    reviewer: Reviewer,
    candidate_id: str,
    flag_id: str | None,
    sitting_id: int | None,
) -> None:
    session = _find_session(db, candidate_id, sitting_id)
    detail = f"jumped to {flag_id}" if flag_id else "opened video"
    _audit(db, clock, reviewer, "video_view", session.id, detail)
    db.flush()


def audit_entries(db: Session, limit: int = 500) -> list[dict[str, Any]]:
    rows = db.execute(
        select(AuditLog, Reviewer.email, TestSession.candidate_id)
        .outerjoin(Reviewer, Reviewer.id == AuditLog.reviewer_id)
        .outerjoin(TestSession, TestSession.id == AuditLog.session_id)
        .order_by(AuditLog.ts.desc(), AuditLog.id.desc())
        .limit(limit)
    ).all()
    entries = []
    for log, email, candidate_id in rows:
        entries.append(
            {
                "id": f"A{log.id}",
                "ts": log.ts,
                "reviewer": email or "system",
                "action": log.action,
                "candidate_id": candidate_id,
                "detail": log.detail or ("signed in" if log.action == "login" else ""),
            }
        )
    return entries
