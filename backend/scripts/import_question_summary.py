"""Import Cytonn's per-question summary (and, if they send one, the question-bank export).

    python -m scripts.jobs import_question_summary SUMMARY.csv [--bank BANK.csv] [--allow-open]

The summary needs question_id, section, correct_option, difficulty_tag, n_candidates, pct_correct,
median_s, p25_s and p75_s. A row that fails its checks is reported and skipped; the rest go in.
Refuses while a sitting is open (a change to the answer key mid-sitting would corrupt stored
answers) unless --allow-open. The report is also written to data/import_report.json.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.clock import SystemClock
from app.config import REPO_ROOT
from app.errors import ApiError
from app.models import AuditLog
from app.services import admin as admin_service
from app.services import question_import


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("summary", type=Path)
    parser.add_argument("--bank", type=Path, default=None)
    parser.add_argument("--allow-open", action="store_true")
    args = parser.parse_args(argv)

    summary_csv = args.summary.read_text(encoding="utf-8-sig")
    bank_csv = args.bank.read_text(encoding="utf-8-sig") if args.bank else None

    with SessionLocal() as db:
        if not args.allow_open and admin_service.has_open_sitting(db):
            raise SystemExit("not imported: a sitting is open (close it first, or --allow-open)")
        try:
            result = question_import.import_summary(db, args.summary.name, summary_csv, bank_csv)
        except ApiError as problem:
            db.rollback()
            raise SystemExit(f"not imported: {problem.code} {problem.extra}") from problem
        db.add(
            AuditLog(
                reviewer_id=None,
                action="admin",
                ts=SystemClock().now(),
                detail=(
                    f"imported {result.imported} of {result.rows} questions from "
                    f"{args.summary.name} (command line)"
                ),
            )
        )
        db.commit()

    report = REPO_ROOT / "data" / "import_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    print(f"{result.imported} of {result.rows} rows imported, {len(result.rejected)} rejected")
    for bad in result.rejected:
        print(f"  row {bad.row} ({bad.question_id or 'no id'}): {bad.reason}")
    for warning in result.warnings:
        print(f"  note: {warning}")
    print(f"report written to {report}")


if __name__ == "__main__":
    main()
