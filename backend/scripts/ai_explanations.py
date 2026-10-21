"""Check every stored AI explanation against its packet, and write a sheet to tick off by hand.

    python -m scripts.jobs ai_explanations --sitting <id or name> [--csv PATH]

The automatic part re-runs the fact check over each stored assessment (the target is 100%: the
fact check should never have let a wrong one through). The sheet puts each explanation beside the
numbers of its packet so a person can confirm it says what the record shows. Default sheet:
eval/reports/ai-explanations-handcheck.csv
"""

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.models import Packet, Ranking, TestSession
from app.services.ranking.base import Assessment
from app.services.ranking.factcheck import fact_check
from scripts.common import add_sitting_argument, resolve_sitting

DEFAULT_SHEET = REPO_ROOT / "eval" / "reports" / "ai-explanations-handcheck.csv"


@dataclass
class Audited:
    candidate_id: str
    ai_status: str
    explanation: str
    facts: dict
    violations: list[str]


def audit_sitting(db: Session, sitting_id: int) -> list[Audited]:
    """Every ranking that kept an AI answer, re-checked. A ranking that fell back has no AI
    explanation to check and is not listed."""
    rows = db.execute(
        select(Ranking, TestSession.candidate_id, Packet.json)
        .join(TestSession, TestSession.id == Ranking.session_id)
        .join(Packet, Packet.session_id == Ranking.session_id)
        .where(Ranking.sitting_id == sitting_id, Ranking.ai_json.is_not(None))
        .order_by(Ranking.final_rank)
    ).all()
    audited = []
    for ranking, candidate_id, packet in rows:
        if not ranking.ai_json:  # a row written before the column stored real NULLs
            continue
        assessment = Assessment.model_validate(ranking.ai_json)
        found = [str(v) for v in fact_check(assessment, packet)]
        audited.append(
            Audited(candidate_id, ranking.ai_status, assessment.explanation, packet["facts"], found)
        )
    return audited


def write_sheet(audited: list[Audited], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        out = csv.writer(handle)
        out.writerow(
            [
                "candidate_id",
                "ai_status",
                "explanation",
                "packet_facts",
                "automatic_check",
                "hand_check",
            ]
        )
        for item in audited:
            out.writerow(
                [
                    item.candidate_id,
                    item.ai_status,
                    item.explanation,
                    json.dumps(item.facts),
                    "pass" if not item.violations else "; ".join(item.violations),
                    "",  # ticked off by a person
                ]
            )


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_sitting_argument(parser)
    parser.add_argument("--csv", type=Path, default=DEFAULT_SHEET)
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        sitting = resolve_sitting(db, args.sitting)
        audited = audit_sitting(db, sitting.id)
    write_sheet(audited, args.csv)

    clean = sum(1 for a in audited if not a.violations)
    print(f"sitting {sitting.id} ({sitting.name}): {clean} of {len(audited)} AI explanations pass")
    for item in audited:
        if item.violations:
            print(f"  {item.candidate_id}: {'; '.join(item.violations)}")
    print(f"sheet for the hand check: {args.csv}")


if __name__ == "__main__":
    main()
