"""The action log: what the candidate's page saw, stored with the server's own idea of when.

Two rules from the proposal are enforced here rather than trusted to the page:

- Copy and cut events keep the length only, never the text. Each event type has a short list of
  payload fields it is allowed to carry; everything else the page sends is dropped on the way in.
- The server clock is the only clock that counts. The page says how long ago it saw something
  (`age_ms`) and the server subtracts that from its own receive time, so an event held back by a
  dropped connection keeps its true moment instead of the moment it finally got through.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.clock import Clock
from app.models import Event, TestSession
from app.schemas.recording import EventIn
from app.services.flags.refresh import refresh_session_flags

Cleaner = Callable[[Any], Any]


def _whole(low: int, high: int) -> Cleaner:
    def clean(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return max(low, min(high, int(value)))

    return clean


def _one_of(*allowed: str) -> Cleaner:
    def clean(value: Any) -> str | None:
        return value if value in allowed else None

    return clean


# The key combinations the page reports for a screenshot. The page cannot see the screenshot
# itself, only that these keys were pressed.
SCREENSHOT_COMBOS = ("PrintScreen", "Win+Shift+S", "Cmd+Shift+3", "Cmd+Shift+4", "Cmd+Shift+5")


def _seconds(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return round(max(0.0, min(172_800.0, float(value))), 1)


def _text(limit: int) -> Cleaner:
    def clean(value: Any) -> str | None:
        return value.strip()[:limit] if isinstance(value, str) else None

    return clean


_POSITION = {"position": _whole(1, 1000)}
_DURATION = {"duration_s": _seconds}

# Every event type the page may send, and the payload fields each may carry. A type that has no
# fields keeps no payload at all, so there is nowhere for a stray piece of text to hide.
PAYLOAD_RULES: dict[str, dict[str, Cleaner]] = {
    "page_load": {},
    "reload": {},
    "question_opened": _POSITION,
    "answered": _POSITION,
    "skipped": _POSITION,
    "focus_lost": {},
    "focus_returned": {},
    "visibility_hidden": {},
    "visibility_visible": {},
    "copy_attempt": {"length": _whole(0, 1_000_000)},
    "cut_attempt": {"length": _whole(0, 1_000_000)},
    "paste_attempt": {},
    "screenshot_attempt": {"combo": _one_of(*SCREENSHOT_COMBOS)},
    "contextmenu_attempt": {},
    "idle_start": {},
    "idle_end": _DURATION,
    "connection_lost": {},
    "connection_restored": {},
    "device_info": {"camera_label": _text(200), "mic_label": _text(200)},
    "mic_muted": {},
    "mic_unmuted": {},
    "mic_silent_start": {},
    "mic_silent_end": _DURATION,
    "camera_dropped": _DURATION,
    "track_ended": {"kind": _text(16), **_DURATION},
    "fullscreen_exited": {},
    "fullscreen_entered": {},
    "recording_started": {"segment": _whole(0, 1000)},
    "upload_incomplete": {"missing": _whole(0, 100_000)},
}
EVENT_TYPES = frozenset(PAYLOAD_RULES)


def clean_payload(event_type: str, payload: dict | None) -> dict[str, Any] | None:
    """Only the fields this type defines, each cleaned. None when nothing is left."""
    rules = PAYLOAD_RULES.get(event_type, {})
    if not payload or not rules:
        return None
    kept: dict[str, Any] = {}
    for key, clean in rules.items():
        if key in payload:
            value = clean(payload[key])
            if value is not None:
                kept[key] = value
    return kept or None


@dataclass(frozen=True)
class IngestResult:
    accepted: int
    duplicates: int
    rejected: int


def server_time_of(now: datetime, age_ms: int, floor: datetime) -> datetime:
    """When it really happened: now minus its age, and never before the session existed."""
    return max(now - timedelta(milliseconds=age_ms), floor)


def ingest(db: Session, clock: Clock, session: TestSession, items: list[EventIn]) -> IngestResult:
    """Store a batch. Safe to send again: an event the server already has (same session and
    `client_seq`) is counted as a duplicate and changes nothing."""
    now = clock.now()
    rows: dict[int, dict[str, Any]] = {}
    rejected = 0
    for item in items:
        if item.type not in EVENT_TYPES:
            rejected += 1
            continue
        if item.client_seq in rows:  # repeated inside one batch
            continue
        rows[item.client_seq] = {
            "session_id": session.id,
            "client_seq": item.client_seq,
            "type": item.type,
            "server_ts": server_time_of(now, item.age_ms, session.created_at),
            "received_at": now,
            "payload": clean_payload(item.type, item.payload),
        }

    stored: list[Any] = []
    if rows:
        statement = (
            pg_insert(Event)
            .values(list(rows.values()))
            .on_conflict_do_nothing(index_elements=["session_id", "client_seq"])
            .returning(Event.type, Event.server_ts, Event.payload)
        )
        stored = list(db.execute(statement).all())

    # The first recording is the anchor for "flag to video moment": the video offset is the
    # flag's server time minus the moment segment 0 started.
    for event_type, server_ts, payload in stored:
        if event_type == "recording_started" and (payload or {}).get("segment", 0) == 0:
            current = session.recording_started_at
            if current is None or server_ts < current:
                session.recording_started_at = server_ts

    db.commit()
    # Events that arrive after the test has ended (the page's last batch, an upload resumed within
    # the 48 hours) can change the session's flags, so they are worked out again.
    if stored and session.status == "finished":
        refresh_session_flags(db, session.id)
    return IngestResult(
        accepted=len(stored),
        duplicates=len(items) - rejected - len(stored),
        rejected=rejected,
    )
