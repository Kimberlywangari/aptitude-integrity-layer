"""What the reviewer screens read: the ranked queue, one candidate's page, and the few things a
reviewer can write (a decision, the shortlist, a note that they opened the video).

The order comes from the stored ranking when one exists for the sitting (the AI step's result, or
the rules-only run) and otherwise from the rules, worked out from the stored flags when asked for.
Either way it is a convenience for a person; nothing here sets anyone aside.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.core.video_url import issue_video_token
from app.errors import ApiError
from app.models import (
    AudioSilence,
    AuditLog,
    Complaint,
    Decision,
    Event,
    Flag,
    Ranking,
    Reviewer,
    SessionQuestion,
    Sitting,
    TestSession,
    VideoChunk,
    VideoSegment,
)
from app.schemas.review import MAX_REASON_CHARS, MIN_REASON_CHARS
from app.services import evidence
from app.services.evidence import rules_explanation  # noqa: F401  (the name other code imports)
from app.services.flags.config import DEFAULTS, FlagConfig
from app.services.flags.scoring import is_flagged
from app.services.ranking.rules import Ranked, flags_by_session, rule_order, score_session
from app.services.video import ffmpeg
from app.services.video.assemble import ensure_assembled, known_segments
from app.services.video.seek import SegmentSpan, seek_for
from app.services.video.store import VideoStore

OUTCOMES = ("no_concern", "concern_noted", "refer_for_follow_up")
VIDEO_VIEW_WINDOW = timedelta(minutes=5)  # one audit entry per reviewer, segment and window


@dataclass(frozen=True)
class VideoContext:
    """What building a candidate's page needs to show video: where it is kept, the clock, and who
    is looking (their links are made for them)."""

    store: VideoStore
    clock: Clock
    settings: Settings
    reviewer_id: int


@dataclass
class Entry:
    """One place in the queue: the rule result and, if the sitting was ranked, its ranking."""

    ranked: Ranked
    ranking: Ranking | None
    rank: int


# ------------------------------------------------------------------------------------ helpers


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


def rank_sitting(db: Session, sitting_id: int, cfg: FlagConfig = DEFAULTS) -> list[Ranked]:
    return rule_order(db, sitting_id, cfg)


# ---------------------------------------------------------------------------------- the queue


def ordered_queue(db: Session, sitting_id: int, cfg: FlagConfig = DEFAULTS) -> list[Entry]:
    """The queue in the order a reviewer works it.

    A stored ranking is used only while it still covers exactly the candidates the flags say
    are queued. If flags were recomputed since (someone gained or lost their last flag), the
    stored order is out of date, so the rules decide until the sitting is ranked again.
    """
    ranked = rule_order(db, sitting_id, cfg)
    rankings = {
        r.session_id: r for r in db.scalars(select(Ranking).where(Ranking.sitting_id == sitting_id))
    }
    stored = bool(ranked) and set(rankings) == {r.session.id for r in ranked}
    if stored:
        ranked.sort(key=lambda r: rankings[r.session.id].final_rank)
    return [
        Entry(item, rankings.get(item.session.id) if stored else None, position)
        for position, item in enumerate(ranked, start=1)
    ]


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


def _ai_strength(ranking: Ranking | None) -> int | None:
    if ranking and ranking.ai_status in ("ok", "retried") and ranking.ai_json:
        return int(ranking.ai_json["strength"])
    return None


def queue(db: Session, sitting_id: int | None, cfg: FlagConfig = DEFAULTS) -> dict[str, Any]:
    sittings = [
        {"id": s.id, "name": s.name} for s in db.scalars(select(Sitting).order_by(Sitting.id))
    ]
    known = {s["id"] for s in sittings}
    chosen = sitting_id if sitting_id in known else default_sitting_id(db)
    entries = ordered_queue(db, chosen, cfg) if chosen else []
    decisions = _latest_decisions(db, [e.ranked.session.id for e in entries])
    items = []
    for entry in entries:
        decision = decisions.get(entry.ranked.session.id)
        items.append(
            {
                "candidate_id": entry.ranked.session.candidate_id,
                "rank": entry.rank,
                "rule_score": entry.ranked.score,
                "ai_strength": _ai_strength(entry.ranking),
                "ai_status": entry.ranking.ai_status if entry.ranking else "not_run",
                "flag_kinds": entry.ranked.kinds,
                "decision": decision.outcome if decision else None,
                "shortlisted": entry.ranked.session.shortlisted,
                "logging_only": entry.ranked.logging_only,
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


def video_url(
    video: VideoContext, candidate_id: str, session_id: str, segment: int
) -> str:
    token = issue_video_token(
        video.settings.session_secret, video.clock, video.reviewer_id, session_id, segment
    )
    return f"/api/review/candidates/{candidate_id}/video?segment={segment}&t={token}"


def _segments(
    db: Session, session: TestSession, video: VideoContext | None
) -> list[VideoSegment]:
    """The recording's segments, assembling them the first time a reviewer opens the page.
    Without ffmpeg only what was assembled before can be shown; nothing is shown for video that
    has been deleted."""
    if video is None:
        return []
    if session.video_deleted_at is not None:
        return known_segments(db, session.id)
    has_chunks = db.scalar(
        select(
            exists().where(VideoChunk.session_id == session.id, VideoChunk.deleted_at.is_(None))
        )
    )
    if has_chunks:
        try:
            return ensure_assembled(
                db, video.store, video.clock, video.settings, session.id
            ).segments
        except ffmpeg.FfmpegMissing:
            pass
    return known_segments(db, session.id)


def _seek_to(spans: list[SegmentSpan], moment: datetime) -> dict[str, Any] | None:
    found = seek_for(spans, moment)
    return {"segment": found.segment, "seek_s": found.seek_s} if found else None


def candidate_detail(
    db: Session,
    candidate_id: str,
    sitting_id: int | None,
    cfg: FlagConfig = DEFAULTS,
    video: VideoContext | None = None,
    retention_days: int = 30,
) -> dict[str, Any]:
    session = _find_session(db, candidate_id, sitting_id)
    flags = flags_by_session(db, [session.id])[session.id]

    entries = {e.ranked.session.id: e for e in ordered_queue(db, session.sitting_id, cfg)}
    entry = entries.get(session.id)
    if entry is not None:
        score_total, lines, rank = entry.ranked.score, entry.ranked.lines, entry.rank
    else:
        score_total, lines = score_session(session, flags, cfg)
        rank = 0
    ranking = entry.ranking if entry else None

    segments = _segments(db, session, video)
    spans = [
        SegmentSpan(s.segment, s.started_at, s.duration_s)
        for s in segments
        if s.started_at is not None and s.path is not None
    ]

    flag_items = [
        {
            "id": f"F{i}",
            "kind": f.kind,
            "server_ts": f.server_ts,
            "elapsed_s": evidence.elapsed(f.server_ts, session.started_at),
            "question_number": f.position,
            "detail": f.detail,
            "video_seek": _seek_to(spans, f.server_ts),
        }
        for i, f in enumerate(flags, start=1)
    ]

    events = list(
        db.scalars(select(Event).where(Event.session_id == session.id).order_by(Event.server_ts))
    )
    silences = list(db.scalars(select(AudioSilence).where(AudioSilence.session_id == session.id)))
    last_answer = db.scalar(
        select(func.max(SessionQuestion.answered_at)).where(
            SessionQuestion.session_id == session.id
        )
    )
    end = session.finished_at or last_answer
    innocent, mic_silence = evidence.signals(events, session.started_at, end, cfg, silences)
    if session.started_at is not None:
        for stretch in mic_silence:
            moment = session.started_at + timedelta(seconds=stretch["start_s"])
            stretch["video_seek"] = _seek_to(spans, moment)

    report = session.self_report or None
    note_signal = evidence.self_report_signal(report, include_note=True)
    if note_signal:
        innocent.append({"id": f"I{len(innocent) + 1}", **note_signal})

    ctx = evidence.load_sitting_context(db, session.sitting_id)
    vs, pace, score = evidence.vs_sitting(ctx, session.id, cfg)

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
        purge_on = decisions[-1]["decided_at"] + timedelta(days=retention_days)

    anchor = session.recording_started_at or (spans[0].started_at if spans else None)
    segment_items = [
        {
            "segment": s.segment,
            "url": (
                video_url(video, session.candidate_id, session.id, s.segment)
                if video is not None and s.path is not None
                else None
            ),
            "start_s": (
                round((s.started_at - anchor).total_seconds(), 1)
                if anchor is not None and s.started_at is not None
                else 0.0
            ),
            "duration_s": s.duration_s,
        }
        for s in segments
    ]

    return {
        "session_id": session.id,
        "candidate_id": session.candidate_id,
        "rank": rank,
        "rule_score": score_total,
        "rule_breakdown": [{"label": ln.label, "points": ln.points} for ln in lines],
        "score": score,
        "pace_s_per_q": round(pace, 1),
        "history_source": evidence.history_source(db, session.id),
        "flags": flag_items,
        "vs_sitting": vs,
        "innocent_signals": innocent,
        "mic_silence": mic_silence,
        "self_report": (
            {
                "had_technical_issues": bool(report.get("had_technical_issues")),
                "note": report.get("note"),
            }
            if report
            else None
        ),
        "explanation": _explanation(ranking, flag_items, len(innocent)),
        "complaints": complaints,
        "decisions": decisions,
        "shortlisted": session.shortlisted,
        "segments": segment_items,
        "video_deleted_at": session.video_deleted_at,
        "video_purge_on": purge_on,
    }


def _explanation(
    ranking: Ranking | None, flag_items: list[dict[str, Any]], n_signals: int
) -> dict[str, Any]:
    """The AI's account when its answer passed the fact check; otherwise the plain account of what
    the rules found, with the status that says why."""
    if ranking is not None and ranking.ai_status in ("ok", "retried") and ranking.ai_json:
        ai = ranking.ai_json
        return {
            "source": "ai",
            "status": ranking.ai_status,
            "text": ai["explanation"],
            "strength": ai["strength"],
            "flags_support_each_other": ai["flags_support_each_other"],
        }
    if ranking is not None:
        text = ranking.explanation
        status = ranking.ai_status
    else:
        text = evidence.rules_explanation(flag_items, n_signals)
        status = "not_run"
    return {
        "source": "rules",
        "status": status,
        "text": text,
        "strength": None,
        "flags_support_each_other": None,
    }


# ------------------------------------------------------------------------------------ video


def can_view_video(db: Session, session: TestSession, cfg: FlagConfig = DEFAULTS) -> bool:
    """Video is for candidates who are in the queue (finished and flagged) or who a reviewer has
    shortlisted. Everyone else's recording stays unopened."""
    if session.shortlisted:
        return True
    if session.status != "finished":
        return False
    flags = flags_by_session(db, [session.id])[session.id]
    if not flags:
        return False
    score, _ = score_session(session, flags, cfg)
    return is_flagged(score, [f.kind for f in flags], cfg)


def note_video_playback(
    db: Session, clock: Clock, reviewer_id: int, session: TestSession, segment: int
) -> None:
    """Audit that this reviewer is watching, once per segment per five minutes: playing a video
    fetches it in many pieces, and a log line for every piece would bury the real entries."""
    now = clock.now()
    detail = f"playing part {segment + 1}"
    recent = db.scalar(
        select(
            exists().where(
                AuditLog.reviewer_id == reviewer_id,
                AuditLog.session_id == session.id,
                AuditLog.action == "video_view",
                AuditLog.detail == detail,
                AuditLog.ts >= now - VIDEO_VIEW_WINDOW,
            )
        )
    )
    if not recent:
        db.add(
            AuditLog(
                reviewer_id=reviewer_id,
                action="video_view",
                session_id=session.id,
                ts=now,
                detail=detail,
            )
        )
        db.commit()


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
