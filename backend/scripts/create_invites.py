"""Make invitation codes for a sitting and write them, with their links, to a CSV.

    python -m scripts.jobs create_invites --sitting <id or exact name> --count 20 [--out PATH]

Every code opens that sitting's paper (Cytonn's questions, AI-written ones or the practice ones,
whatever the sitting was made with) for as long as the sitting gives. The same as the Invitations
page, for when a terminal is handier. Only each code's hash is stored, so the CSV is the one place
the codes exist: it goes under data/, which git ignores, unless --out says otherwise.
"""

import argparse
import csv
from pathlib import Path

from sqlalchemy import select

from app.config import REPO_ROOT, get_settings
from app.core.security import format_invite_code
from app.errors import ApiError
from app.models import Sitting
from app.services import admin as admin_service


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sitting", required=True, help="the sitting's id or its exact name")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--out", type=Path, help="where to write the CSV")
    args = parser.parse_args(argv)

    base = get_settings().public_base_url.rstrip("/")
    with SessionLocal() as db:
        if args.sitting.isdigit():
            sitting = db.get(Sitting, int(args.sitting))
        else:
            sitting = db.scalar(select(Sitting).where(Sitting.name == args.sitting))
        if sitting is None:
            raise SystemExit(f"no sitting matches {args.sitting!r}")
        try:
            invites = admin_service.generate_invites(db, args.count, sitting)
        except ApiError as problem:
            db.rollback()
            raise SystemExit(f"not made: {problem.code} {problem.extra or ''}".strip()) from problem
        db.commit()
        name, sitting_id = sitting.name, sitting.id

    out = args.out or REPO_ROOT / "data" / f"invites-sitting-{sitting_id}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["candidate_id", "token", "url", "sitting"])
        for candidate_id, code in invites:
            shown = format_invite_code(code)
            writer.writerow([candidate_id, shown, f"{base}/?t={shown}", name])
    print(f'{len(invites)} invitations for sitting {sitting_id} ("{name}") written to {out}')


if __name__ == "__main__":
    main()
