"""The rule score and its breakdown (master plan 7.4).

Rule score = the flag weights, plus 1 for each extra distinct kind, plus 1 if any two flags fall
within 120 s of each other. The breakdown is always shown, so a reviewer can see exactly where a
number came from and nobody is ranked by a figure they cannot take apart.

The score only orders the queue. It decides nothing about a candidate.
"""

from dataclasses import dataclass

from app.services.flags.config import DEFAULTS, FlagConfig
from app.services.flags.rules import FOCUS_LOSS, LOGGING_PROBLEM


@dataclass(frozen=True)
class ScoredFlag:
    label: str  # how the flag is named on screen, e.g. F3
    kind: str
    weight: float
    at_s: float  # seconds from the start of the sitting


@dataclass(frozen=True)
class Line:
    label: str
    points: float


def is_logging_only(kinds: list[str]) -> bool:
    """Only a gap in the record: these sit in a lane of their own, below everyone with evidence."""
    return bool(kinds) and all(k == LOGGING_PROBLEM for k in kinds)


def is_flagged(score: float, kinds: list[str], cfg: FlagConfig = DEFAULTS) -> bool:
    """Whether a candidate enters the queue: enough evidence on the score, or a gap in the record
    (which goes in a lane of its own, below everyone with evidence)."""
    return score >= cfg.flagged_score or LOGGING_PROBLEM in kinds


def score_flags(flags: list[ScoredFlag], cfg: FlagConfig = DEFAULTS) -> tuple[float, list[Line]]:
    lines: list[Line] = []
    total = 0.0
    focus_used = 0.0

    for flag in sorted(flags, key=lambda f: f.at_s):
        points = flag.weight
        if flag.kind == FOCUS_LOSS:
            # losses all show, but together they stop counting once they reach the cap
            points = max(0.0, min(flag.weight, cfg.focus_loss_cap - focus_used))
            focus_used += points
        lines.append(Line(f"{flag.kind} ({flag.label})", points))
        total += points

    scoring = [f for f in flags if f.kind != LOGGING_PROBLEM]
    kinds = {f.kind for f in scoring}
    if len(kinds) > 1:
        extra = (len(kinds) - 1) * cfg.extra_kind_points
        lines.append(Line(f"Extra distinct kinds (+{cfg.extra_kind_points:g} each)", extra))
        total += extra

    times = sorted(f.at_s for f in scoring)
    if any(b - a <= cfg.near_flags_window_s for a, b in zip(times, times[1:], strict=False)):
        lines.append(
            Line(f"Two flags within {cfg.near_flags_window_s:g} s", cfg.near_flags_points)
        )
        total += cfg.near_flags_points

    return round(total, 2), lines
