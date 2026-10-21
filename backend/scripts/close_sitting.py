"""Close a sitting so its cohort checks can run.

    python -m scripts.jobs close_sitting --sitting <id or name> [--force]

Refuses while anyone is still sitting or has not started, unless --force is given; a forced close
is written to the audit log. Closing does not compute anything: run compute_flags next.
"""

import argparse

from app.clock import SystemClock
from app.errors import ApiError
from app.models import AuditLog
from app.services import admin as admin_service
from scripts.common import add_sitting_argument, resolve_sitting


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_sitting_argument(parser)
    parser.add_argument(
        "--force", action="store_true", help="close even if sessions are unfinished"
    )
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        target = resolve_sitting(db, args.sitting)
        try:
            sitting, unfinished = admin_service.close_sitting(db, target.id, force=args.force)
        except ApiError as problem:
            db.rollback()
            hint = ""
            if "unfinished" in problem.extra:
                hint = f" ({problem.extra['unfinished']} unfinished; --force to close anyway)"
            raise SystemExit(f"not closed: {problem.code}{hint}") from problem
        detail = admin_service.audit_detail_for_close(sitting, unfinished)
        db.add(
            AuditLog(
                reviewer_id=None,
                action="admin",
                ts=SystemClock().now(),
                detail=f"{detail} (from the command line)",
            )
        )
        db.commit()
        print(f"sitting {sitting.id} ({sitting.name}) closed" + (" [forced]" if unfinished else ""))


if __name__ == "__main__":
    main()
