"""Building the evidence packet for each flagged candidate.

A packet exists only for a candidate with at least one flag. Reloads, dropped connections, a quiet
microphone and a pre-check note appear in it as context for a reviewer, but none of them can cause
a packet on its own.

Hard rules kept here: the candidate ID and nothing that names a person (no invitation token, no
camera or microphone label, none of the free text the candidate wrote), and a `facts` block that
lists every number the packet contains.
"""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.models import (
    AudioSilence,
    Event,
    Flag,
    Packet,
    Question,
    SessionQuestion,
    TestSession,
)
from app.schemas.packet import Packet as PacketSchema
from app.services import evidence
from app.services.flags.config import DEFAULTS, FlagConfig
from app.services.ranking.rules import rule_order


def _ints(value: Any) -> list[int]:
    """Every whole number inside a value, however deeply nested. Booleans are not numbers here."""
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _ints(v)]
    if isinstance(value, list):
        return [n for v in value for n in _ints(v)]
    return []


def build_facts(packet: dict[str, Any]) -> dict[str, Any]:
    """The numbers a reader of this packet may legitimately cite, in three groups."""
    questions = {q["number"] for q in packet["questions"]}
    times: set[int] = {packet["pace_s_per_q"]}
    kinds: dict[str, int] = {}
    for flag in packet["flags"]:
        if flag["question_number"] is not None:
            questions.add(flag["question_number"])
        questions.update(flag["detail"].get("questions", []))
        times.add(flag["elapsed_s"])
        times.update(_ints({k: v for k, v in flag["detail"].items() if k != "questions"}))
        kinds[flag["kind"]] = kinds.get(flag["kind"], 0) + 1
    times.update(_ints(packet["innocent_signals"]))
    times.update(_ints(packet["mic_silence"]))
    times.update(_ints(packet["fullscreen_exits"]))

    counts: dict[str, int] = {
        "flags": len(packet["flags"]),
        "innocent_signals": len(packet["innocent_signals"]),
        "mic_silence": len(packet["mic_silence"]),
        "fullscreen_exits": len(packet["fullscreen_exits"]),
        "score": packet["score"],
        **kinds,
    }
    if "cohort_skipped" not in packet["vs_sitting"]:
        counts.update(packet["vs_sitting"])
    return {"question_numbers": sorted(questions), "times_s": sorted(times), "counts": counts}


def _referenced_questions(flags: list[Flag]) -> set[int]:
    wanted: set[int] = set()
    for flag in flags:
        if flag.position is not None:
            wanted.add(flag.position)
        wanted.update(int(n) for n in flag.detail.get("questions", []))
    return wanted


def build_packet(
    db: Session,
    session: TestSession,
    ctx: evidence.SittingContext | None = None,
    cfg: FlagConfig = DEFAULTS,
) -> dict[str, Any] | None:
    """The packet for one session as plain JSON, or None when it has no flags."""
    flags = list(
        db.scalars(
            select(Flag).where(Flag.session_id == session.id).order_by(Flag.server_ts, Flag.id)
        )
    )
    if not flags:
        return None

    events = list(
        db.scalars(select(Event).where(Event.session_id == session.id).order_by(Event.server_ts))
    )
    silences = list(db.scalars(select(AudioSilence).where(AudioSilence.session_id == session.id)))
    last_answered = max(
        (
            t
            for t in db.scalars(
                select(SessionQuestion.answered_at).where(SessionQuestion.session_id == session.id)
            )
            if t is not None
        ),
        default=None,
    )
    end = session.finished_at or last_answered
    innocent, mic = evidence.signals(events, session.started_at, end, cfg, silences)
    signal = evidence.self_report_signal(session.self_report, include_note=False)
    if signal:
        innocent.append({"id": f"I{len(innocent) + 1}", **signal})

    wanted = _referenced_questions(flags)
    questions = []
    if wanted:
        rows = db.execute(
            select(SessionQuestion.position, Question.section, Question.difficulty)
            .join(Question, Question.id == SessionQuestion.question_id)
            .where(SessionQuestion.session_id == session.id, SessionQuestion.position.in_(wanted))
            .order_by(SessionQuestion.position)
        )
        questions = [
            {"number": number, "section": section, "difficulty": difficulty}
            for number, section, difficulty in rows
        ]

    ctx = ctx or evidence.load_sitting_context(db, session.sitting_id)
    vs, pace, score = evidence.vs_sitting(ctx, session.id, cfg)

    packet: dict[str, Any] = {
        "candidate_id": session.candidate_id,
        "flags": [
            {
                "id": f"F{index}",
                "kind": flag.kind,
                "server_ts": flag.server_ts,
                "elapsed_s": evidence.elapsed(flag.server_ts, session.started_at),
                "question_number": flag.position,
                "detail": flag.detail,
            }
            for index, flag in enumerate(flags, start=1)
        ],
        "questions": questions,
        "vs_sitting": vs,
        "score": score,
        "pace_s_per_q": round(pace),
        "history_source": evidence.history_source(db, session.id),
        "fullscreen_exits": evidence.fullscreen_exits(events, session.started_at, end),
        "precheck": evidence.precheck_view(session.precheck_report),
        "innocent_signals": innocent,
        "mic_silence": [{k: v for k, v in m.items() if k != "video_seek"} for m in mic],
        "video_anchor": session.recording_started_at.isoformat()
        if session.recording_started_at
        else None,
    }
    validated = PacketSchema.model_validate({**packet, "facts": build_facts(packet)})
    return validated.model_dump(mode="json")


def build_sitting_packets(
    db: Session, clock: Clock, sitting_id: int, cfg: FlagConfig = DEFAULTS
) -> int:
    """Rebuild the packet of every candidate in the sitting's queue (flagged: a rule score at or
    above the threshold, or a gap in the record), and remove the packet of anyone who is no longer
    in it. Returns how many packets now exist."""
    queued = rule_order(db, sitting_id, cfg)
    ctx = evidence.load_sitting_context(db, sitting_id)
    now = clock.now()
    built = 0
    for item in queued:
        packet = build_packet(db, item.session, ctx, cfg)
        db.merge(Packet(session_id=item.session.id, json=packet, built_at=now))
        built += 1
    keep = {item.session.id for item in queued}
    in_sitting = select(TestSession.id).where(TestSession.sitting_id == sitting_id)
    db.execute(
        delete(Packet).where(Packet.session_id.in_(in_sitting), Packet.session_id.not_in(keep))
        if keep
        else delete(Packet).where(Packet.session_id.in_(in_sitting))
    )
    db.flush()
    return built
