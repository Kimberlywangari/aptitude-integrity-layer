"""Note, once, every session whose 48 hours to finish uploading have passed with chunks missing.

    python -m scripts.jobs mark_incomplete_uploads

A reviewer sees it as context ("this recording is partial"); it never counts against a candidate.
"""

import argparse

from app.clock import SystemClock
from app.config import get_settings
from app.services.uploads import mark_incomplete_uploads


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    with SessionLocal() as db:
        marked = mark_incomplete_uploads(db, SystemClock(), get_settings().resume_window_s)
    print(f"{len(marked)} sessions marked upload_incomplete")


if __name__ == "__main__":
    main()
