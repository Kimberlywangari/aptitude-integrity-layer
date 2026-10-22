"""The numbers on the overview page: where a sitting stands and which flagged candidates still need
a person to look. Read only, and lean: a handful of grouped queries, no per-candidate lookups.

Nothing here decides anything. "Flagged" is the review queue, "reviewed" is how many of those have a
written decision, and the checks say whether the parts the review depends on are in place.
"""

from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Decision, Flag, Sitting, TestSession, VideoChunk
from app.services import review
from app.services.flags.config import DEFAULTS, FlagConfig
from app.services.flags.rules import LOGGING_PROBLEM
from app.services.video import ffmpeg

NEXT_UP = 3
OLLAMA_PROBE_TIMEOUT_S = 1.0


def ollama_is_up(base_url: str) -> bool:
    """Whether the local model server answers. One short request, only when it is the provider."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=OLLAMA_PROBE_TIMEOUT_S)
    except httpx.HTTPError:
        return False
    return response.is_success


def _check(key: str, label: str, state: str, detail: str) -> dict[str, str]:
    return {"key": key, "label": label, "state": state, "detail": detail}


def _ai_check(settings: Settings, ollama_probe: Callable[[str], bool]) -> dict[str, str]:
    provider = settings.ai_provider
    if provider == "ollama":
        if ollama_probe(settings.ollama_base_url):
            text = f"The local model {settings.ollama_model} is running."
            return _check("ai", "AI ranking", "ok", text)
        text = "The local model does not answer; the order falls back to the rules."
        return _check("ai", "AI ranking", "warn", text)
    if provider == "claude":
        if settings.anthropic_api_key:
            return _check("ai", "AI ranking", "ok", f"Claude ({settings.claude_model}) is set up.")
        text = "No Anthropic key is set; the order falls back to the rules."
        return _check("ai", "AI ranking", "warn", text)
    return _check("ai", "AI ranking", "off", "Rules only: the order comes from the rule score.")


GATE_TEXT = {
    "recording": "A candidate cannot begin until a real recording has arrived.",
    "precheck": "A candidate needs a passing pre-check, but not yet a real recording.",
    "off": "The test starts without the camera and microphone check. Fine for development.",
}


def checks(
    settings: Settings, heartbeat_gaps: int, ollama_probe: Callable[[str], bool] = ollama_is_up
) -> list[dict[str, str]]:
    """Whether the parts a review depends on are in place. `ok` is fine, `warn` needs a look,
    `off` is a choice that was made, `note` is a count to know about."""
    gate = settings.precheck_gate
    has_ffmpeg = ffmpeg.available()
    return [
        _ai_check(settings, ollama_probe),
        _check(
            "factcheck",
            "Fact check on AI answers",
            "ok",
            "Every AI answer is checked against the stored log before a reviewer sees it.",
        ),
        _check("fallback", "Rule order fallback", "ok", "If the AI fails, the rule order is used."),
        _check(
            "gate",
            "Camera and microphone gate",
            "ok" if gate == "recording" else "warn",
            GATE_TEXT[gate],
        ),
        _check(
            "ffmpeg",
            "Video processing",
            "ok" if has_ffmpeg else "warn",
            "ffmpeg joins the recording so a reviewer can jump to a moment."
            if has_ffmpeg
            else "ffmpeg was not found, so a recording cannot be played back.",
        ),
        _check(
            "heartbeat",
            "Heartbeat gaps",
            "note" if heartbeat_gaps else "ok",
            f"{heartbeat_gaps} to look at." if heartbeat_gaps else "None in this sitting.",
        ),
    ]


def overview(
    db: Session,
    sitting_id: int | None,
    settings: Settings,
    cfg: FlagConfig = DEFAULTS,
    ollama_probe: Callable[[str], bool] = ollama_is_up,
) -> dict[str, Any]:
    sittings, chosen = review.sittings_and_choice(db, sitting_id)
    sitting = db.get(Sitting, chosen) if chosen else None

    by_status: dict[str, int] = {}
    flags_by_kind: list[dict[str, Any]] = []
    finished: list[tuple[str, int | None, Any]] = []  # (session id, chunks reported, video gone)
    entries: list[review.Entry] = []
    decided_ids: set[str] = set()
    chunk_counts: dict[str, int] = {}

    if chosen:
        by_status = dict(
            db.execute(
                select(TestSession.status, func.count())
                .where(TestSession.sitting_id == chosen)
                .group_by(TestSession.status)
            ).all()
        )
        flags_by_kind = [
            {"kind": kind, "count": n}
            for kind, n in db.execute(
                select(Flag.kind, func.count())
                .join(TestSession, TestSession.id == Flag.session_id)
                .where(TestSession.sitting_id == chosen, TestSession.status == "finished")
                .group_by(Flag.kind)
                .order_by(func.count().desc(), Flag.kind)
            )
        ]
        finished = [
            (sid, total, gone)
            for sid, total, gone in db.execute(
                select(
                    TestSession.id, TestSession.chunks_total, TestSession.video_deleted_at
                ).where(TestSession.sitting_id == chosen, TestSession.status == "finished")
            )
        ]
        entries = review.ordered_queue(db, chosen, cfg)
        decided_ids = set(
            db.scalars(
                select(Decision.session_id)
                .join(TestSession, TestSession.id == Decision.session_id)
                .where(TestSession.sitting_id == chosen)
                .distinct()
            )
        )
        if finished:
            chunk_counts = dict(
                db.execute(
                    select(VideoChunk.session_id, func.count())
                    .where(VideoChunk.session_id.in_([sid for sid, _, _ in finished]))
                    .group_by(VideoChunk.session_id)
                ).all()
            )

    reviewed = [e for e in entries if e.ranked.session.id in decided_ids]
    waiting = [e for e in entries if e.ranked.session.id not in decided_ids]
    next_up = []
    for entry in waiting[:NEXT_UP]:
        _, band = review.strength_and_band(entry)
        next_up.append(
            {
                "candidate_id": entry.ranked.session.candidate_id,
                "band": band,
                "flag_count": len(entry.ranked.flags),
                "first_kind": entry.ranked.kinds[0],
            }
        )

    heartbeat_gaps = next((f["count"] for f in flags_by_kind if f["kind"] == LOGGING_PROBLEM), 0)
    finished_n = by_status.get("finished", 0)
    return {
        "sittings": sittings,
        "sitting_id": chosen,
        "sitting_status": sitting.status if sitting else None,
        "tiles": {
            "sat": finished_n + by_status.get("in_progress", 0),
            "finished": finished_n,
            "flagged": len(entries),
            "reviewed": len(reviewed),
            # a recording is uploaded when every chunk the page said it made has arrived
            "videos_uploaded": sum(
                1
                for sid, total, _ in finished
                if total is not None and chunk_counts.get(sid, 0) >= total
            ),
            "videos_expected": finished_n,
            "videos_decided_not_deleted": sum(
                1 for sid, _, gone in finished if sid in decided_ids and gone is None
            ),
        },
        "flags_by_kind": flags_by_kind,
        "pending": len(waiting),
        "next_up": next_up,
        "checks": checks(settings, heartbeat_gaps, ollama_probe),
    }
