"""Measure the pilot against the proposal's criteria, from the ranked sitting and the truth file.

    python -m scripts.jobs pilot_metrics --sitting <id or name> --truth eval/pilot/truth.csv

The truth file has one row per volunteer: candidate_id, role (`honest`, or anything else for a
planted cheater such as C1 to C6) and planted_actions (free text). Definitions, as the master plan
fixes them (A10): "flagged" means a rule score of 1.0 or more; "top third" is the top third of the
candidates who were queued, not of everyone. Run `rank` first. Small numbers are indicative, not
proof, and the report must say so.
"""

import argparse
import csv
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ranking, TestSession
from scripts.common import add_sitting_argument, resolve_sitting

FLAGGED_AT = 1.0


@dataclass
class Metrics:
    honest: int = 0
    honest_flagged: list[str] = field(default_factory=list)
    cheaters: int = 0
    caught: list[str] = field(default_factory=list)  # planted cheaters who were flagged
    top_third: list[str] = field(default_factory=list)  # ...and in the top third of the queue
    missed: list[str] = field(default_factory=list)
    queued: int = 0
    unknown: list[str] = field(default_factory=list)  # in the truth file but not in the sitting
    ai_seconds: list[float] = field(default_factory=list)
    statuses: dict[str, int] = field(default_factory=dict)


def read_truth(path: Path) -> dict[str, str]:
    """candidate_id -> role, lower-cased. `honest` is the one role that is not a cheater."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or not {"candidate_id", "role"} <= set(rows[0]):
        raise SystemExit("the truth file needs the columns candidate_id and role")
    return {r["candidate_id"].strip(): r["role"].strip().lower() for r in rows if r["candidate_id"]}


def measure(db: Session, sitting_id: int, truth: dict[str, str]) -> Metrics:
    ranked = db.execute(
        select(Ranking, TestSession.candidate_id)
        .join(TestSession, TestSession.id == Ranking.session_id)
        .where(Ranking.sitting_id == sitting_id)
        .order_by(Ranking.final_rank)
    ).all()
    by_candidate = {candidate: ranking for ranking, candidate in ranked}
    in_sitting = set(
        db.scalars(select(TestSession.candidate_id).where(TestSession.sitting_id == sitting_id))
    )

    result = Metrics()
    # the queue is everyone flagged, in the order a reviewer would work it; "top third" is the top
    # third of that queue, not of everyone who sat
    queued = [(ranking, candidate) for ranking, candidate in ranked]
    result.queued = len(queued)
    third = math.ceil(len(queued) / 3) if queued else 0
    top = {candidate for _, candidate in queued[:third]}

    for ranking, _ in queued:
        result.statuses[ranking.ai_status] = result.statuses.get(ranking.ai_status, 0) + 1
        if ranking.ai_seconds is not None:
            result.ai_seconds.append(ranking.ai_seconds)

    for candidate, role in sorted(truth.items()):
        if candidate not in in_sitting:
            result.unknown.append(candidate)
            continue
        ranking = by_candidate.get(candidate)
        flagged = ranking is not None and (ranking.rule_score >= FLAGGED_AT or ranking.logging_only)
        if role == "honest":
            result.honest += 1
            if ranking is not None and ranking.rule_score >= FLAGGED_AT:
                result.honest_flagged.append(candidate)
        else:
            result.cheaters += 1
            if flagged:
                result.caught.append(candidate)
                if candidate in top:
                    result.top_third.append(candidate)
            else:
                result.missed.append(candidate)
    return result


def render(metrics: Metrics) -> str:
    def rate(count: int, total: int) -> str:
        return f"{count} of {total}" + (f" ({100 * count / total:.0f}%)" if total else "")

    seconds = (
        f"median {statistics.median(metrics.ai_seconds):.1f} s, max {max(metrics.ai_seconds):.1f} s"
        if metrics.ai_seconds
        else "the AI step did not run"
    )
    lines = [
        "| Criterion | Target | Result |",
        "|---|---|---|",
        f"| Honest volunteers wrongly flagged | at most 1 in 10 | "
        f"{rate(len(metrics.honest_flagged), metrics.honest)} |",
        f"| Planted cheating caught | 8 in 10 | {rate(len(metrics.caught), metrics.cheaters)} |",
        f"| Planted cheaters in the top third of the queue | 8 in 10 | "
        f"{rate(len(metrics.top_third), metrics.cheaters)} |",
        f"| AI seconds per flagged candidate | under 120 | {seconds} |",
        "",
        f"Queued candidates: {metrics.queued}. Statuses: "
        + (", ".join(f"{k} {v}" for k, v in sorted(metrics.statuses.items())) or "none")
        + ".",
    ]
    if metrics.honest_flagged:
        lines.append("Honest but flagged: " + ", ".join(metrics.honest_flagged))
    if metrics.missed:
        lines.append("Planted but not flagged: " + ", ".join(metrics.missed))
    if metrics.unknown:
        lines.append("In the truth file but not in this sitting: " + ", ".join(metrics.unknown))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_sitting_argument(parser)
    parser.add_argument("--truth", type=Path, required=True)
    args = parser.parse_args(argv)
    truth = read_truth(args.truth)

    with SessionLocal() as db:
        sitting = resolve_sitting(db, args.sitting)
        metrics = measure(db, sitting.id, truth)
    print(f"sitting {sitting.id} ({sitting.name})\n")
    print(render(metrics))


if __name__ == "__main__":
    main()
