"""Ranking a sitting: the AI step with its safety net.

For every flagged candidate: ask the ranker, fact-check the answer, ask once more if it was wrong
(telling it what was wrong), and if the second try fails too, keep the rule-based order and rule
explanation for that candidate. Nobody is ever dropped: the AI can move a candidate up or down, it
cannot remove them, and a sitting with N flagged candidates always ends with N rankings.

The final order is the AI's strength when its answer passed the fact check, otherwise a 1 to 5
strength mapped from the rule score; ties go to the higher rule score, then whoever was flagged
first. A gap in the record with nothing else always sits below everyone with evidence.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.clock import Clock
from app.models import Packet, Ranking
from app.services import evidence
from app.services.flags.config import DEFAULTS, FlagConfig
from app.services.packets import build_sitting_packets
from app.services.ranking.base import Ranker, RankerError, RankerResult
from app.services.ranking.factcheck import fact_check
from app.services.ranking.pricing import cost_usd, price_of
from app.services.ranking.rules import Ranked, rule_order, strength_bucket

MAX_ATTEMPTS = 2  # the first try and one retry
BUDGET_REACHED = "the AI budget for this run was reached, so this candidate keeps the rule order"


@dataclass
class RankRun:
    flagged: int = 0
    rankings: list[Ranking] = field(default_factory=list)
    statuses: Counter = field(default_factory=Counter)
    seconds: list[float] = field(default_factory=list)  # per candidate, where the AI ran
    spent_usd: float = 0.0  # at the published price, from the tokens each call reported
    over_budget: int = 0  # candidates left to the rule order because the budget was reached


def _spent(ranker: Ranker, attempts: list[dict[str, Any]]) -> float:
    """Dollars these attempts cost. A local model is free, and an attempt that reported no tokens
    adds nothing (a failed call's usage can be lost with it, so the budget is a close guide, not a
    guarantee)."""
    if ranker.name != "claude":
        return 0.0
    return sum(
        cost_usd(ranker.model, a["usage"]["input_tokens"], a["usage"]["output_tokens"])
        for a in attempts
        if a.get("usage")
    )


def _flag_dicts(item: Ranked) -> list[dict[str, Any]]:
    return [
        {"kind": f.kind, "detail": f.detail, "question_number": f.position} for f in item.flags
    ]


def _assess(
    ranker: Ranker, packet: dict[str, Any], clock: Clock
) -> tuple[RankerResult | None, list[dict[str, Any]], float]:
    """Up to two tries. Returns the accepted result (or None), every attempt for the audit
    trail, and the seconds spent."""
    attempts: list[dict[str, Any]] = []
    violations: list[str] | None = None
    accepted: RankerResult | None = None
    started = clock.now()
    for number in range(1, MAX_ATTEMPTS + 1):
        attempt_started = clock.now()
        record: dict[str, Any] = {
            "attempt": number,
            "raw": None,
            "violations": [],
            "error": None,
            "usage": None,
        }
        try:
            result = ranker.assess(packet, violations)
        except RankerError as problem:
            record["error"] = str(problem)
            record["raw"] = problem.raw
            record["usage"] = problem.usage
            violations = [f"the previous answer was unusable: {problem}"]
        else:
            record["raw"] = result.raw
            record["usage"] = result.usage
            found = [str(v) for v in fact_check(result.assessment, packet)]
            record["violations"] = found
            if not found:
                accepted = result
            else:
                violations = found
        record["seconds"] = round((clock.now() - attempt_started).total_seconds(), 2)
        attempts.append(record)
        if accepted is not None:
            break
    return accepted, attempts, (clock.now() - started).total_seconds()


def rank_sitting(
    db: Session,
    sitting_id: int,
    ranker: Ranker | None,
    clock: Clock,
    cfg: FlagConfig = DEFAULTS,
    budget_usd: float | None = None,
) -> RankRun:
    """Write one ranking per flagged candidate in the sitting, replacing any earlier run.
    `ranker=None` is the rules-only run: nobody is sent to an AI and the rule order stands.
    `budget_usd` stops sending candidates to a Claude model once this run has spent that much; the
    rest keep the rule order, so nobody is dropped. It is checked before each candidate, so a run
    can pass it by the cost of one candidate. A model with no recorded price is refused up front."""
    if budget_usd is not None and ranker is not None and ranker.name == "claude":
        price_of(ranker.model)  # raises UnknownModel rather than spend with no way to count it
    ordered = rule_order(db, sitting_id, cfg)
    build_sitting_packets(db, clock, sitting_id, cfg)  # fresh from the flags as they stand now
    packets = {
        p.session_id: p.json
        for p in db.query(Packet).filter(Packet.session_id.in_([r.session.id for r in ordered]))
    }
    now = clock.now()
    run = RankRun(flagged=len(ordered))

    rows: list[tuple[Ranked, int, Ranking]] = []
    for item in ordered:
        packet = packets[item.session.id]
        explanation = evidence.rules_explanation(_flag_dicts(item), len(packet["innocent_signals"]))
        ai_json = attempts = seconds = None
        status = "not_run"
        strength = strength_bucket(item.score, item.logging_only)
        if ranker is not None:
            if budget_usd is not None and run.spent_usd >= budget_usd:
                accepted = None
                attempts = [
                    {"attempt": 0, "raw": None, "violations": [], "error": BUDGET_REACHED,
                     "usage": None, "seconds": 0.0}
                ]
                run.over_budget += 1
            else:
                accepted, attempts, spent = _assess(ranker, packet, clock)
                run.spent_usd += _spent(ranker, attempts)
                seconds = round(spent, 2)
                run.seconds.append(seconds)
            if accepted is None:
                status = "fallback"
            else:
                status = "ok" if len(attempts) == 1 else "retried"
                ai_json = accepted.assessment.model_dump()
                strength = accepted.assessment.strength
        run.statuses[status] += 1
        rows.append(
            (
                item,
                strength,
                Ranking(
                    session_id=item.session.id,
                    sitting_id=sitting_id,
                    rule_score=item.score,
                    rule_rank=item.rank,
                    logging_only=item.logging_only,
                    ai_status=status,
                    ai_json=ai_json,
                    ai_attempts=attempts,
                    ai_seconds=seconds,
                    final_rank=0,
                    explanation=explanation,
                    provider=ranker.name if ranker else "rules",
                    model=ranker.model if ranker else None,
                    ranked_at=now,
                ),
            )
        )

    rows.sort(
        key=lambda r: (
            r[0].logging_only,
            -r[1],
            -r[0].score,
            r[0].first_flag_at,
            r[0].session.candidate_id,
        )
    )
    for position, (_, _, ranking) in enumerate(rows, start=1):
        ranking.final_rank = position

    db.execute(delete(Ranking).where(Ranking.sitting_id == sitting_id))
    db.add_all(ranking for _, _, ranking in rows)
    db.flush()
    run.rankings = [ranking for _, _, ranking in rows]

    if len(run.rankings) != run.flagged:  # the guarantee: the AI can reorder, never drop
        raise RuntimeError(f"ranking lost a candidate: {len(run.rankings)} of {run.flagged}")
    return run
