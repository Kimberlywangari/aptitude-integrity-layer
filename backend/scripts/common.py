"""Small helpers the batch jobs share."""

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Sitting


def resolve_sitting(db: Session, ref: str) -> Sitting:
    """A sitting from its id or its exact name; exits with a plain message when there is none."""
    if ref.isdigit():
        sitting = db.get(Sitting, int(ref))
    else:
        sitting = db.scalar(select(Sitting).where(Sitting.name == ref))
    if sitting is None:
        raise SystemExit(f"no sitting matches {ref!r}")
    return sitting


def add_sitting_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sitting", required=True, help="the sitting's id or its exact name")
