"""Staff accounts from the command line.

    python -m scripts.jobs create_reviewer --email a@cytonn.com --role admin
    python -m scripts.jobs create_reviewer --email a@cytonn.com --update      # reset a password
    python -m scripts.jobs deactivate_reviewer --email a@cytonn.com

Without --password the job asks for one (twice, without echoing it), so it stays out of the shell
history. This is also how the first admin is made.
"""

import argparse
import getpass

from app.clock import SystemClock
from app.services import staff_auth


def _ask_for_password() -> str:
    first = getpass.getpass("Password: ")
    if getpass.getpass("Password again: ") != first:
        raise SystemExit("error: the two passwords differ")
    return first


def create_main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description="Create a reviewer or admin account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", help="omit to be asked, which keeps it out of shell history")
    parser.add_argument("--role", choices=staff_auth.ROLES, default="reviewer")
    parser.add_argument(
        "--update", action="store_true", help="reset an existing account's password and role"
    )
    args = parser.parse_args(argv)

    password = args.password if args.password is not None else _ask_for_password()
    try:
        with SessionLocal() as db:
            reviewer, created = staff_auth.create_reviewer(
                db,
                SystemClock(),
                email=args.email,
                password=password,
                role=args.role,
                update=args.update,
            )
            db.commit()
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(f"{'created' if created else 'updated'} {reviewer.email} ({reviewer.role})")


def deactivate_main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description="Switch an account off. Its tokens stop at once.")
    parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    try:
        with SessionLocal() as db:
            reviewer = staff_auth.deactivate_reviewer(db, args.email)
            db.commit()
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(f"deactivated {reviewer.email}")
