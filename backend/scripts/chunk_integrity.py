"""Prove no video chunk was lost: every chunk expected has arrived, and its bytes still match.

    python -m scripts.jobs chunk_integrity --sitting <id or name>
    python -m scripts.jobs chunk_integrity --session <session id>

Exits with status 1 if any candidate has a missing, changed or unreadable chunk, so it can gate a
script. Pass means 0 missing and 0 mismatched for everyone.
"""

import argparse

from sqlalchemy import select

from app.config import get_settings
from app.models import TestSession
from app.services.video.integrity import verify_session
from app.services.video.store import LocalVideoStore
from scripts.common import resolve_sitting


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sitting", help="the sitting's id or its exact name")
    group.add_argument("--session", help="one session id")
    args = parser.parse_args(argv)
    store = LocalVideoStore(get_settings().video_root_path)

    with SessionLocal() as db:
        if args.session:
            session = db.get(TestSession, args.session)
            if session is None:
                raise SystemExit(f"no session {args.session!r}")
            sessions = [session]
        else:
            sitting = resolve_sitting(db, args.sitting)
            sessions = list(
                db.scalars(
                    select(TestSession)
                    .where(TestSession.sitting_id == sitting.id, TestSession.status == "finished")
                    .order_by(TestSession.candidate_id)
                )
            )
        failed = 0
        for session in sessions:
            result = verify_session(db, store, session)
            expected = "?" if result.expected is None else result.expected
            line = f"{session.candidate_id:<12} {result.received}/{expected} chunks"
            if result.ok:
                print(f"{line}  ok")
                continue
            failed += 1
            print(
                f"{line}  FAIL  missing {result.missing}  changed {result.mismatched}  "
                f"unreadable {result.unreadable}"
            )
    print(f"{len(sessions) - failed} of {len(sessions)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
