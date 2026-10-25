"""The rule flags as pure functions: plain data in, flag drafts out.

Nothing here touches the database or the clock, so every rule is tested with a handful of values.
A rule returns drafts; engine.py stores them. A rule never decides anything about a candidate: a
draft is a fact a person can look at.
"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.services.flags.config import DEFAULTS, FlagConfig

FOCUS_LOSS = "FOCUS_LOSS"
COPY_ATTEMPT = "COPY_ATTEMPT"
SCREENSHOT_KEY = "SCREENSHOT_KEY"
LONG_HOLD_CORRECT = "LONG_HOLD_CORRECT"
CORRECT_RUN_AFTER_GAP = "CORRECT_RUN_AFTER_GAP"
PACE_OUTLIER = "PACE_OUTLIER"
SPREAD_OUTLIER = "SPREAD_OUTLIER"
LOGGING_PROBLEM = "LOGGING_PROBLEM"

# 0.6745 makes the median absolute deviation comparable with a standard deviation.
MAD_SCALE = 0.6745


@dataclass(frozen=True)
class Answer:
    """One question in a candidate's paper, as the rules need it."""

    position: int
    question_id: str
    difficulty: str | None
    opened_at: datetime | None
    answered_at: datetime | None
    correct: bool | None
    skipped: bool = False

    @property
    def time_s(self) -> float | None:
        if self.opened_at is None or self.answered_at is None:
            return None
        return (self.answered_at - self.opened_at).total_seconds()


@dataclass(frozen=True)
class Ev:
    type: str
    ts: datetime
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Span:
    start: datetime
    end: datetime

    @property
    def duration_s(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass(frozen=True)
class FlagDraft:
    kind: str
    weight: float
    ts: datetime
    position: int | None
    detail: dict[str, Any]


# ------------------------------------------------------------------------------------ helpers


def pair_spans(
    events: list[Ev], open_type: str, close_type: str, end: datetime | None
) -> list[Span]:
    """Each `open_type` event matched with the next `close_type`. A span still open at `end` runs
    to `end`; a close with nothing open is ignored."""
    spans: list[Span] = []
    opened: datetime | None = None
    for event in sorted(events, key=lambda e: e.ts):
        if event.type == open_type and opened is None:
            opened = event.ts
        elif event.type == close_type and opened is not None:
            spans.append(Span(opened, event.ts))
            opened = None
    if opened is not None and end is not None and end > opened:
        spans.append(Span(opened, end))
    return spans


def focus_losses(events: list[Ev], end: datetime | None) -> list[Span]:
    return pair_spans(events, "focus_lost", "focus_returned", end)


def connection_drops(events: list[Ev], end: datetime | None) -> list[Span]:
    return pair_spans(events, "connection_lost", "connection_restored", end)


def idle_spans(events: list[Ev]) -> list[Span]:
    """Idle stretches. `idle_end` carries `duration_s`, so the start is read back from it."""
    spans: list[Span] = []
    for event in events:
        if event.type == "idle_end":
            duration = float(event.payload.get("duration_s", 0) or 0)
            if duration > 0:
                spans.append(Span(event.ts - timedelta(seconds=duration), event.ts))
    return spans


def position_at(answers: list[Answer], ts: datetime) -> int | None:
    """The question that was open at `ts`, if any."""
    for answer in answers:
        if answer.opened_at is None or answer.opened_at > ts:
            continue
        if answer.answered_at is None or ts <= answer.answered_at:
            return answer.position
    return None


def _overlaps(span: Span, start: datetime, end: datetime) -> bool:
    return span.start < end and span.end > start


def counted_losses(losses: list[Span], cfg: FlagConfig = DEFAULTS) -> list[Span]:
    """The focus losses that count: a loss shorter than `focus_loss_min_s` is a blink (a
    notification, a click on the address bar) and no rule looks at it."""
    return [s for s in losses if s.duration_s >= cfg.focus_loss_min_s]


def lost_seconds(losses: list[Span], start: datetime, end: datetime) -> float:
    """How long, in total, focus was away between `start` and `end`."""
    return sum(
        (min(s.end, end) - max(s.start, start)).total_seconds()
        for s in losses
        if _overlaps(s, start, end)
    )


# -------------------------------------------------------------------------------------- rules


def focus_loss_flags(
    losses: list[Span], answers: list[Answer], cfg: FlagConfig = DEFAULTS
) -> list[FlagDraft]:
    """One flag per loss of focus of at least `focus_loss_min_s`. The cap on their total is
    applied when the score is worked out, so every loss still shows to a reviewer."""
    drafts = []
    for span in losses:
        if span.duration_s < cfg.focus_loss_min_s:
            continue
        drafts.append(
            FlagDraft(
                FOCUS_LOSS,
                cfg.focus_loss_weight,
                span.start,
                position_at(answers, span.start),
                {"focus_lost_s": round(span.duration_s)},
            )
        )
    return drafts


def copy_attempt_flags(
    events: list[Ev], answers: list[Answer], cfg: FlagConfig = DEFAULTS
) -> list[FlagDraft]:
    """One flag per copy or cut attempt. Only the length is kept, never the text."""
    drafts = []
    for event in sorted(events, key=lambda e: e.ts):
        if event.type not in ("copy_attempt", "cut_attempt"):
            continue
        drafts.append(
            FlagDraft(
                COPY_ATTEMPT,
                cfg.copy_weight,
                event.ts,
                position_at(answers, event.ts),
                {"target": "question_text", "length": int(event.payload.get("length", 0) or 0)},
            )
        )
    return drafts


def screenshot_key_flags(
    events: list[Ev], answers: list[Answer], cfg: FlagConfig = DEFAULTS
) -> list[FlagDraft]:
    """One flag per screenshot key press. Only the key combination is kept."""
    return [
        FlagDraft(
            SCREENSHOT_KEY,
            cfg.screenshot_weight,
            event.ts,
            position_at(answers, event.ts),
            {"combo": str(event.payload.get("combo", ""))},
        )
        for event in sorted(events, key=lambda e: e.ts)
        if event.type == "screenshot_attempt"
    ]


def long_hold_correct_flags(
    answers: list[Answer], losses: list[Span], cfg: FlagConfig = DEFAULTS
) -> list[FlagDraft]:
    """A correct answer after far longer than the candidate's own usual time, with focus lost for
    more than `hold_min_focus_lost_s` while the question was open.

    The candidate's own median comes from their other answered questions, and a candidate with
    fewer than `hold_min_other_answers` of those gets no flag at all: there is nothing fair to
    compare against. A slow answer with focus on the page the whole time is not flagged: the
    candidate was just thinking, and nothing suggests help.
    """
    answered = [a for a in answers if a.time_s is not None and not a.skipped]
    losses = counted_losses(losses, cfg)
    drafts = []
    for answer in answered:
        if answer.correct is not True or answer.opened_at is None or answer.answered_at is None:
            continue
        others = [o.time_s for o in answered if o is not answer and o.time_s is not None]
        if len(others) < cfg.hold_min_other_answers:
            continue
        median = statistics.median(others)
        limit = min(max(cfg.hold_factor * median, median + cfg.hold_extra_s), cfg.hold_cap_s)
        if limit <= median:  # usually uses the whole time, so a long hold is nothing unusual
            continue
        if answer.time_s is None or answer.time_s <= limit:
            continue
        away_s = lost_seconds(losses, answer.opened_at, answer.answered_at)
        if away_s <= cfg.hold_min_focus_lost_s:
            continue
        drafts.append(
            FlagDraft(
                LONG_HOLD_CORRECT,
                cfg.hold_weight,
                answer.opened_at,
                answer.position,
                {
                    "time_s": round(answer.time_s),
                    "own_median_s": round(median),
                    "focus_lost_s": round(away_s),
                },
            )
        )
    return drafts


def run_gaps(losses: list[Span], idles: list[Span], cfg: FlagConfig = DEFAULTS) -> list[Span]:
    """The focus losses and idle stretches long enough to count as a gap before a run."""
    gaps = [s for s in counted_losses(losses, cfg) if s.duration_s >= cfg.run_gap_focus_s]
    gaps += [s for s in idles if s.duration_s >= cfg.run_gap_idle_s]
    return sorted(gaps, key=lambda s: s.end)


def correct_run_after_gap_flags(
    answers: list[Answer], gaps: list[Span], cfg: FlagConfig = DEFAULTS
) -> list[FlagDraft]:
    """`run_length` or more correct answers in a row, straight after a gap, answered quickly.

    "Quickly" is the average time per question of the first `run_length` answers after the gap,
    counted from the end of the gap (the first question may have been open through it), against the
    candidate's own median on their other answers: under `run_fast_factor` of it. A run at the
    candidate's normal pace is just a good stretch. With fewer than `run_min_other_answers` other
    answers there is nothing fair to compare against, so there is no flag.
    """
    answered = sorted(
        (a for a in answers if a.answered_at is not None and not a.skipped),
        key=lambda a: a.answered_at,  # type: ignore[arg-type,return-value]
    )
    drafts = []
    used: set[int] = set()
    for gap in gaps:
        after = [a for a in answered if a.answered_at is not None and a.answered_at > gap.end]
        run = 0
        for answer in after:
            if answer.correct is not True:
                break
            run += 1
        if run < cfg.run_length or after[0].position in used:
            continue
        checked = after[: cfg.run_length]
        in_run = {a.position for a in checked}
        others = [
            a.time_s for a in answered if a.position not in in_run and a.time_s is not None
        ]
        if len(others) < cfg.run_min_other_answers:
            continue
        median = statistics.median(others)
        times = [
            (a.answered_at - max(a.opened_at or gap.end, gap.end)).total_seconds()  # type: ignore[operator]
            for a in checked
        ]
        mean = statistics.fmean(times)
        if mean >= cfg.run_fast_factor * median:
            continue
        used.add(after[0].position)
        drafts.append(
            FlagDraft(
                CORRECT_RUN_AFTER_GAP,
                cfg.run_weight,
                gap.end,
                after[0].position,
                {
                    "gap_s": round(gap.duration_s),
                    "run_length": run,
                    "mean_s": round(mean, 1),
                    "own_median_s": round(median),
                },
            )
        )
    return drafts


def heartbeat_gaps(
    beats: list[datetime], start: datetime | None, end: datetime | None, cfg: FlagConfig = DEFAULTS
) -> list[Span]:
    """Stretches longer than `heartbeat_gap_s` with no heartbeat, including before the first and
    after the last. A session with no heartbeat at all was never logged, so nothing is judged."""
    if not beats:
        return []
    marks = sorted(beats)
    if start is not None:
        marks = [start, *marks]
    if end is not None:
        marks = [*marks, end]
    return [
        Span(a, b)
        for a, b in zip(marks, marks[1:], strict=False)
        if (b - a).total_seconds() > cfg.heartbeat_gap_s
    ]


def logging_problem_flags(
    gaps: list[Span], drops: list[Span], events: list[Ev], cfg: FlagConfig = DEFAULTS
) -> list[FlagDraft]:
    """A heartbeat gap that no dropped connection, reload or page load accounts for. These sit in
    their own low lane: they say the record is incomplete, not that anyone did anything."""
    restarts = [e.ts for e in events if e.type in ("page_load", "reload")]
    drafts = []
    for gap in gaps:
        if any(_overlaps(d, gap.start, gap.end) for d in drops):
            continue
        if any(gap.start <= ts <= gap.end for ts in restarts):
            continue
        drafts.append(
            FlagDraft(
                LOGGING_PROBLEM,
                0.0,
                gap.start,
                None,
                {"heartbeat_gap_s": round(gap.duration_s)},
            )
        )
    return drafts


# ------------------------------------------------------------------------------------ cohort


@dataclass(frozen=True)
class CohortMember:
    key: str
    mean_s: float  # mean time per answered question
    spread_s: float  # standard deviation of those times
    ts: datetime  # where a flag on this member is placed


def baseline(values: list[float]) -> tuple[float, float]:
    """The median and the raw median absolute deviation of a group's values. (A z score divides
    by this MAD scaled by 1.4826, which is what `robust_z` does.)"""
    median = statistics.median(values)
    return median, statistics.median(abs(v - median) for v in values)


def robust_z(values: list[float], x: float) -> float | None:
    """Distance from the median in median-absolute-deviation units. Median and MAD, not mean and
    standard deviation: in a group of about 14, a few unusual people would drag a mean."""
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)
    if mad == 0:
        return None
    return MAD_SCALE * (x - median) / mad


def cohort_flags(
    members: list[CohortMember], cfg: FlagConfig = DEFAULTS
) -> dict[str, list[FlagDraft]]:
    """Pace and spread outliers across a sitting. Skipped below `cohort_min_candidates`, where a
    comparison with the group means nothing."""
    if len(members) < cfg.cohort_min_candidates:
        return {}
    means = [m.mean_s for m in members]
    spreads = [m.spread_s for m in members]
    out: dict[str, list[FlagDraft]] = {}
    for member in members:
        found: list[FlagDraft] = []
        z = robust_z(means, member.mean_s)
        if z is not None and abs(z) >= cfg.cohort_z:
            found.append(
                FlagDraft(
                    PACE_OUTLIER,
                    cfg.pace_weight,
                    member.ts,
                    None,
                    {"direction": "fast" if z < 0 else "slow", "robust_z": round(z, 1)},
                )
            )
        z = robust_z(spreads, member.spread_s)
        if z is not None and abs(z) >= cfg.cohort_z:
            found.append(
                FlagDraft(
                    SPREAD_OUTLIER,
                    cfg.spread_weight,
                    member.ts,
                    None,
                    {"direction": "narrow" if z < 0 else "wide", "robust_z": round(z, 1)},
                )
            )
        if found:
            out[member.key] = found
    return out


def percentile_of(values: list[float], x: float) -> int:
    """The share of the group at or below `x`, as a whole percent."""
    if not values:
        return 0
    return round(100 * sum(1 for v in values if v <= x) / len(values))
