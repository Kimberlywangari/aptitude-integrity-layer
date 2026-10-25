"""The worker: the housekeeping that must happen on its own, once an hour.

    python -m scripts.jobs loop [--once] [--every SECONDS]

Each round finishes tests whose time ran out with nobody there (and works out their flags),
deletes video that is due (purge_videos) and notes uploads that never finished
(mark_incomplete_uploads). A round that fails is reported and the next one still runs, so one bad
afternoon does not stop deletions for good. --once runs a single round and exits.
"""

import argparse
import time
import traceback

from app.clock import SystemClock
from app.config import get_settings
from app.services import mail, test_flow
from app.services.flags.refresh import refresh_session_flags
from app.services.uploads import mark_incomplete_uploads
from app.services.video.purge import purge_due
from app.services.video.store import LocalVideoStore


def run_round() -> tuple[int, int]:
    """One round of housekeeping. Returns (sessions purged, uploads marked incomplete)."""
    from app.db import SessionLocal

    settings = get_settings()
    clock = SystemClock()
    with SessionLocal() as db:
        abandoned = test_flow.finish_expired(db, clock)
        db.commit()
        for session_id in abandoned:
            refresh_session_flags(db, session_id)
        purged = purge_due(
            db, LocalVideoStore(settings.video_root_path), clock, settings.retention_days
        )
        marked = mark_incomplete_uploads(db, clock, settings.resume_window_s)
        # mail that was queued when the API stopped, or that a mail server refused earlier
        mailer = mail.get_mailer(settings)
        sent = mail.send_queued(db, clock, mailer).sent if mailer else 0
    print(
        f"{clock.now().isoformat(timespec='seconds')}: finished {len(abandoned)} abandoned tests, "
        f"purged {len(purged.purged)} sessions, marked {len(marked)} incomplete uploads, "
        f"sent {sent} emails",
        flush=True,
    )
    return len(purged.purged), len(marked)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--every", type=int, default=3600, help="seconds between rounds")
    args = parser.parse_args(argv)

    while True:
        try:
            run_round()
        except Exception:  # keep the worker alive; the traceback is what the log is for
            traceback.print_exc()
        if args.once:
            return
        time.sleep(args.every)


if __name__ == "__main__":
    main()
