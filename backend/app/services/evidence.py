"""The facts about one candidate that a reviewer, and the evidence packet, are built from: how they
compare with the sitting, the signals with an ordinary explanation, the muted-microphone stretches,
and a plain account of what the rules found.

Everything here reads stored data and returns plain values. Nothing decides anything about a
candidate; it names what happened and leaves what it means to a person.
"""

import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AudioSilence, Event, SessionQuestion, TestSession
from app.services.flags import rules
from app.services.flags.config import DEFAULTS, FlagConfig

# ------------------------------------------------------------------------------------ helpers


def elapsed(ts: datetime, start: datetime | None) -> int:
    """Whole seconds from the start of the test; 0 when the test never started."""
    if start is None:
        return 0
    return round((ts - start).total_seconds())


def redact(text: str) -> str:
    """Take email addresses and phone numbers out of free text before it goes anywhere a person
    other than the candidate will read it."""
    text = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[email]", text)
    return re.sub(r"\+?\d[\d\s().-]{7,}\d", "[number]", text)


# ------------------------------------------------------------------------ against the sitting


@dataclass
class SittingContext:
    """Every finished candidate's pace, spread and score, read once for the whole sitting."""

    paces: dict[str, float] = field(default_factory=dict)
    spreads: dict[str, float] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)


def _answer_times(rows: list[Any]) -> list[float]:
    return [
        (r.answered_at - r.opened_at).total_seconds()
        for r in rows
        if r.opened_at is not None and r.answered_at is not None and not r.skipped
    ]


def load_sitting_context(db: Session, sitting_id: int) -> SittingContext:
    rows = db.execute(
        select(
            SessionQuestion.session_id,
            SessionQuestion.opened_at,
            SessionQuestion.answered_at,
            SessionQuestion.correct,
            SessionQuestion.skipped,
        )
        .join(TestSession, TestSession.id == SessionQuestion.session_id)
        .where(TestSession.sitting_id == sitting_id, TestSession.status == "finished")
    ).all()
    by_session: dict[str, list[Any]] = {}
    for row in rows:
        by_session.setdefault(row.session_id, []).append(row)

    ctx = SittingContext()
    for sid, items in by_session.items():
        times = _answer_times(items)
        ctx.scores[sid] = float(sum(1 for r in items if r.correct is True))
        if times:
            ctx.paces[sid] = statistics.fmean(times)
            ctx.spreads[sid] = statistics.pstdev(times) if len(times) > 1 else 0.0
    return ctx


def vs_sitting(
    ctx: SittingContext, session_id: str, cfg: FlagConfig = DEFAULTS
) -> tuple[dict[str, Any], float, int]:
    """Percentiles against the sitting, plus this candidate's pace and test score. Below the
    minimum group size the comparison means nothing, so it says so instead."""
    own_pace = ctx.paces.get(session_id, 0.0)
    own_score = int(ctx.scores.get(session_id, 0))
    if len(ctx.paces) < cfg.cohort_min_candidates:
        return {"cohort_skipped": "too_small"}, own_pace, own_score
    return (
        {
            "pace_percentile": rules.percentile_of(list(ctx.paces.values()), own_pace),
            "spread_percentile": rules.percentile_of(
                list(ctx.spreads.values()), ctx.spreads.get(session_id, 0.0)
            ),
            "score_percentile": rules.percentile_of(list(ctx.scores.values()), own_score),
        },
        own_pace,
        own_score,
    )


# ------------------------------------------------------------------------------------ signals


def _mic_stretches(
    events: list[rules.Ev],
    silences: list[AudioSilence],
    end: datetime | None,
    cfg: FlagConfig,
) -> list[tuple[datetime, datetime, set[str]]]:
    """Muted or silent stretches from both layers, joined where they overlap. Each says which
    layer saw it: the browser (the candidate was warned) and/or the server's scan of the audio."""
    seen: list[tuple[datetime, datetime, str]] = []
    spans = rules.pair_spans(events, "mic_silent_start", "mic_silent_end", end)
    spans += rules.pair_spans(events, "mic_muted", "mic_unmuted", end)
    for span in spans:
        if span.duration_s >= cfg.mic_silence_min_s:
            seen.append((span.start, span.end, "browser"))
    for row in silences:
        if (row.end_server_ts - row.start_server_ts).total_seconds() >= cfg.mic_silence_min_s:
            seen.append((row.start_server_ts, row.end_server_ts, "server"))

    merged: list[tuple[datetime, datetime, set[str]]] = []
    for start, stop, layer in sorted(seen, key=lambda s: (s[0], s[1])):
        if merged and start <= merged[-1][1]:
            previous = merged[-1]
            merged[-1] = (previous[0], max(previous[1], stop), previous[2] | {layer})
        else:
            merged.append((start, stop, {layer}))
    return merged


def self_report_signal(
    report: dict[str, Any] | None, *, include_note: bool
) -> dict[str, Any] | None:
    """The candidate's own technical-issue report as a signal. The free text is shown to a
    reviewer but never put in a packet: it is the one piece of candidate-written text the AI
    would read, and it can say anything, including instructions."""
    if not report or not report.get("had_technical_issues"):
        return None
    signal: dict[str, Any] = {"kind": "self_report", "category": "technical_issue"}
    if include_note:
        signal["note"] = redact(report.get("note") or "")[:120]
    return signal


def signals(
    events: list[Event],
    start: datetime | None,
    end: datetime | None,
    cfg: FlagConfig = DEFAULTS,
    silences: list[AudioSilence] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Context a reviewer should weigh: drops, reloads, device trouble (innocent signals, with
    ids I1, I2 ...) and the muted or silent microphone stretches (ids M1, M2 ...)."""
    evs = [rules.Ev(e.type, e.server_ts, e.payload or {}) for e in events]
    innocent: list[dict[str, Any]] = []

    def add(**fields: Any) -> None:
        innocent.append({"id": f"I{len(innocent) + 1}", **fields})

    for span in rules.connection_drops(evs, end):
        add(
            kind="connection_lost",
            elapsed_s=elapsed(span.start, start),
            duration_s=round(span.duration_s),
        )
    for event in evs:
        if event.type == "reload":
            add(kind="reload", elapsed_s=elapsed(event.ts, start))
        elif event.type in ("camera_dropped", "track_ended"):
            add(
                kind=event.type,
                elapsed_s=elapsed(event.ts, start),
                duration_s=round(float(event.payload.get("duration_s", 0) or 0)),
            )
        elif event.type == "upload_incomplete":
            add(kind="upload_incomplete", elapsed_s=elapsed(event.ts, start))
    innocent.sort(key=lambda s: s.get("elapsed_s", 0))
    # ids follow the order a reviewer reads them in
    for index, item in enumerate(innocent, start=1):
        item["id"] = f"I{index}"

    stretches = [
        {
            "id": f"M{index}",
            "start_s": elapsed(begin, start),
            "end_s": elapsed(stop, start),
            "duration_s": round((stop - begin).total_seconds()),
            "layers": sorted(layers),
            "video_seek": None,
        }
        for index, (begin, stop, layers) in enumerate(
            _mic_stretches(evs, silences or [], end, cfg), start=1
        )
    ]
    return innocent, stretches


def fullscreen_exits(
    events: list[Event], start: datetime | None, end: datetime | None
) -> list[dict[str, int]]:
    """Each time the candidate left full screen and how long they were out. Context only: a page
    cannot stop it, and an honest candidate can leave by accident."""
    evs = [rules.Ev(e.type, e.server_ts, e.payload or {}) for e in events]
    return [
        {
            "start_s": elapsed(span.start, start),
            "end_s": elapsed(span.end, start),
            "duration_s": round(span.duration_s),
        }
        for span in rules.pair_spans(evs, "fullscreen_exited", "fullscreen_entered", end)
    ]


def precheck_view(report: dict[str, Any] | None) -> dict[str, Any]:
    """What the pre-check recorded that a reviewer may weigh. Context, never a flag."""
    report = report or {}
    browser = report.get("browser") or {}
    return {
        "notifications_off_confirmed": report.get("notifications_off_confirmed"),
        "fullscreen_ok": report.get("fullscreen_ok"),
        "browser": f"{browser.get('name', '')} {browser.get('version', '')}".strip() or None,
    }


# --------------------------------------------------------------------------------- explanation

_DESCRIBE = {
    "COPY_ATTEMPT": lambda d, q, on: f"a copy attempt{on} ({d.get('length', 0)} characters)",
    "SCREENSHOT_KEY": lambda d, q, on: f"a screenshot key pressed{on} ({d.get('combo', '')})",
    "FOCUS_LOSS": lambda d, q, on: f"a {d.get('focus_lost_s', 0)} s loss of focus{on}",
    "LONG_HOLD_CORRECT": lambda d, q, on: (
        f"question {q} took {d.get('time_s')} s against the candidate's own median of "
        f"{d.get('own_median_s')} s, with focus away for {d.get('focus_lost_s')} s of it, "
        "and was answered correctly"
    ),
    "CORRECT_RUN_AFTER_GAP": lambda d, q, on: (
        f"{d.get('run_length')} correct answers in a row straight after a {d.get('gap_s')} s gap, "
        f"averaging {d.get('mean_s')} s each against the candidate's own median of "
        f"{d.get('own_median_s')} s"
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
    if not flags:
        return "Rules only: no flags were raised for this candidate."
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
