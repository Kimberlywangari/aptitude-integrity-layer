"""Recompute the rule flags for a sitting.

    python -m scripts.jobs compute_flags --sitting <id or name>

Safe to repeat: each run replaces that sitting's earlier rule flags. Run it after a threshold in
app/services/flags/config.py changes, or once a sitting is closed so the cohort rules apply.
"""

import argparse

from sqlalchemy import select

from app.models import Sitting
from app.services.flags.engine import compute_sitting_flags


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sitting", required=True, help="the sitting's id or its exact name")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        if args.sitting.isdigit():
            sitting = db.get(Sitting, int(args.sitting))
        else:
            sitting = db.scalar(select(Sitting).where(Sitting.name == args.sitting))
        if sitting is None:
            raise SystemExit(f"no sitting matches {args.sitting!r}")
        run = compute_sitting_flags(db, sitting.id)
        db.commit()

    print(
        f"sitting {sitting.id} ({sitting.name}): {run.flags} flags on {run.flagged} of "
        f"{run.sessions} finished sessions; cohort rules "
        f"{'applied' if run.cohort_applied else 'skipped'} "
        f"({'closed' if sitting.status == 'closed' else 'still open'}, "
        "needs 8 or more finished candidates)"
    )


if __name__ == "__main__":
    main()
