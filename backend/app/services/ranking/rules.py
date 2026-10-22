"""The rule-based order: most evidence first, a gap in the record last. This is the order every
flagged candidate has with no AI at all, and the order the AI step falls back to when it fails.

Ranks and scores are worked out from the stored flags when asked for, so they cannot go stale after
a threshold or a flag changes. The order is a convenience for a person; nothing here sets anyone
aside.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Flag, TestSession
from app.services import evidence
from app.services.flags.config import DEFAULTS, FlagConfig
from app.services.flags.scoring import Line, ScoredFlag, is_flagged, is_logging_only, score_flags

# A rule score becomes a 1 to 5 strength (to stand in for the AI's) at these cut points: below
# the first is 1, from the last up is 5. Flagged means a score of 1.0 or more.
STRENGTH_CUTS = (2.0, 4.0, 6.0, 9.0)


@dataclass
class Ranked:
    session: TestSession
    flags: list[Flag]
    score: float
    lines: list[Line]
    logging_only: bool
    rank: int = 0
    kinds: list[str] = field(default_factory=list)

    @property
    def first_flag_at(self):
        return self.flags[0].server_ts


def strength_bucket(score: float, logging_only: bool = False) -> int:
    """A rule score as a 1 to 5 strength. A gap in the record alone is always 1."""
    if logging_only:
        return 1
    return 1 + sum(score >= cut for cut in STRENGTH_CUTS)


def priority_band(strength: int) -> str:
    """How soon a person might want to look, from the 1 to 5 strength (the AI's when it answered,
    else the rules'). A label for the queue only: it orders attention and sets no one aside."""
    if strength >= 4:
        return "high"
    return "moderate" if strength == 3 else "low"


def flags_by_session(db: Session, session_ids: list[str]) -> dict[str, list[Flag]]:
    out: dict[str, list[Flag]] = {sid: [] for sid in session_ids}
    if not session_ids:
        return out
    rows = db.scalars(
        select(Flag).where(Flag.session_id.in_(session_ids)).order_by(Flag.server_ts, Flag.id)
    )
    for flag in rows:
        out[flag.session_id].append(flag)
    return out


def score_session(
    session: TestSession, flags: list[Flag], cfg: FlagConfig = DEFAULTS
) -> tuple[float, list[Line]]:
    scored = [
        ScoredFlag(f"F{i}", f.kind, f.weight, evidence.elapsed(f.server_ts, session.started_at))
        for i, f in enumerate(flags, start=1)
    ]
    return score_flags(scored, cfg)


def rule_order(db: Session, sitting_id: int, cfg: FlagConfig = DEFAULTS) -> list[Ranked]:
    """The queue: finished sessions that are flagged (see `is_flagged`), most evidence first and
    a gap in the record last. A candidate with only a lone loss of focus is not in it."""
    sessions = list(
        db.scalars(
            select(TestSession).where(
                TestSession.sitting_id == sitting_id, TestSession.status == "finished"
            )
        )
    )
    flags = flags_by_session(db, [s.id for s in sessions])
    ranked: list[Ranked] = []
    for session in sessions:
        found = flags[session.id]
        if not found:
            continue
        total, lines = score_session(session, found, cfg)
        kinds = [f.kind for f in found]
        if not is_flagged(total, kinds, cfg):
            continue
        ranked.append(Ranked(session, found, total, lines, is_logging_only(kinds), kinds=kinds))
    # equal scores: whoever was flagged first, then by ID so the order is always the same
    ranked.sort(
        key=lambda r: (r.logging_only, -r.score, r.first_flag_at, r.session.candidate_id)
    )
    for position, item in enumerate(ranked, start=1):
        item.rank = position
    return ranked
