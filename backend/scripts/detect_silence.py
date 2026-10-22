"""Scan the saved audio of a sitting for long muted or silent stretches (the server's layer of the
microphone checks). Context for a reviewer only: it never raises a flag.

    python -m scripts.jobs detect_silence --sitting <id or name>

Run before build_packets so the stretches the server found appear in the packets. Needs ffmpeg.
Safe to repeat: each run replaces a session's earlier rows.
"""

import argparse

from sqlalchemy import select

from app.clock import SystemClock
from app.config import get_settings
from app.models import TestSession
from app.services.audio.silence import detect_silence
from app.services.video import ffmpeg
from app.services.video.store import LocalVideoStore
from scripts.common import add_sitting_argument, resolve_sitting


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_sitting_argument(parser)
    args = parser.parse_args(argv)
    settings = get_settings()
    store = LocalVideoStore(settings.video_root_path)
    clock = SystemClock()

    with SessionLocal() as db:
        sitting = resolve_sitting(db, args.sitting)
        sessions = list(
            db.execute(
                select(TestSession.id, TestSession.candidate_id).where(
                    TestSession.sitting_id == sitting.id,
                    TestSession.status == "finished",
                    TestSession.video_deleted_at.is_(None),
                )
            ).all()
        )
        total = 0
        for session_id, candidate in sessions:
            try:
                found = detect_silence(db, store, clock, settings, session_id)
            except ffmpeg.FfmpegMissing as problem:
                raise SystemExit(str(problem)) from problem
            total += found
            if found:
                print(f"  {candidate}: {found} quiet stretch(es)")
    print(f"sitting {sitting.id} ({sitting.name}): {total} stretches in {len(sessions)} sessions")


if __name__ == "__main__":
    main()
