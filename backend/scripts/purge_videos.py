"""Delete video 30 days after a reviewer's decision (RETENTION_DAYS).

    python -m scripts.jobs purge_videos [--report]

The record is kept (chunk rows, flags, packet, decision); only the video goes. A candidate with no
decision is never deleted here. --report also lists those whose video is older than
UNDECIDED_REPORT_DAYS (60 by default), so a person can decide what happens to them.
"""

import argparse

from app.clock import SystemClock
from app.config import get_settings
from app.services.video.purge import purge_due, undecided_report
from app.services.video.store import LocalVideoStore


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true", help="also list undecided old video")
    args = parser.parse_args(argv)
    settings = get_settings()
    clock = SystemClock()

    with SessionLocal() as db:
        result = purge_due(
            db, LocalVideoStore(settings.video_root_path), clock, settings.retention_days
        )
        print(
            f"purged {len(result.purged)} sessions ({result.files_removed} files), "
            f"{settings.retention_days} days after their latest decision"
        )
        if args.report:
            stale = undecided_report(db, clock, settings.undecided_report_days)
            print(
                f"{len(stale)} finished sessions have video, no decision and are over "
                f"{settings.undecided_report_days} days old"
            )
            for item in stale:
                print(f"  {item.candidate_id}  finished {item.age_days} days ago")


if __name__ == "__main__":
    main()
