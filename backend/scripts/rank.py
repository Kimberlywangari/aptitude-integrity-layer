"""Rank a sitting's flagged candidates and print the order.

    python -m scripts.jobs rank --sitting <id or name> [--provider rules|ollama|claude]

`rules` (the default unless AI_PROVIDER says otherwise) uses the rule order only. `ollama` and
`claude` ask a model to assess each packet, fact-check the answer, retry once, and fall back to the
rule order for a candidate whose answer cannot be trusted. Nobody is ever dropped: the number of
rows printed always equals the number of flagged candidates.
"""

import argparse
import statistics

from sqlalchemy import select

from app.clock import SystemClock
from app.config import get_settings
from app.models import TestSession
from app.services.ranking.base import RankerError, get_ranker
from app.services.ranking.runner import rank_sitting
from scripts.common import add_sitting_argument, resolve_sitting


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_sitting_argument(parser)
    parser.add_argument("--provider", choices=("rules", "ollama", "claude"), default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.provider:
        settings = settings.model_copy(update={"ai_provider": args.provider})
    try:
        ranker = get_ranker(settings)
    except RankerError as problem:
        raise SystemExit(f"cannot use {settings.ai_provider}: {problem}") from problem

    with SessionLocal() as db:
        sitting = resolve_sitting(db, args.sitting)
        run = rank_sitting(db, sitting.id, ranker, SystemClock())
        db.commit()
        rows = [
            (r.final_rank, r.session_id, r.rule_score, r.ai_status, r.ai_seconds, r.ai_json)
            for r in run.rankings
        ]
        candidates = dict(
            db.execute(
                select(TestSession.id, TestSession.candidate_id).where(
                    TestSession.id.in_([row[1] for row in rows])
                )
            ).all()
        )

    provider = f"{ranker.name} {ranker.model}" if ranker else "rules only"
    print(f"sitting {sitting.id} ({sitting.name}): {run.flagged} flagged, ranked by {provider}")
    print(f"{'rank':>4}  {'candidate':<12} {'rule score':>10}  {'status':<9} {'AI':>3}  seconds")
    for rank, session_id, score, status, seconds, ai in rows:
        strength = ai["strength"] if ai else "-"
        took = f"{seconds:.1f}" if seconds is not None else "-"
        who = candidates[session_id]
        print(f"{rank:>4}  {who:<12} {score:>10.2f}  {status:<9} {strength:>3}  {took}")
    if run.seconds:
        print(
            f"AI time per candidate: median {statistics.median(run.seconds):.1f} s, "
            f"max {max(run.seconds):.1f} s (target: under 120 s)"
        )
    print("statuses: " + ", ".join(f"{k} {v}" for k, v in sorted(run.statuses.items())))


if __name__ == "__main__":
    main()
