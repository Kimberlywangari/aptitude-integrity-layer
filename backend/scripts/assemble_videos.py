"""Join each candidate's uploaded chunks into video a reviewer can scrub.

    python -m scripts.jobs assemble_videos --sitting <id or name>

Needs ffmpeg (on PATH, or set FFMPEG_BIN). A segment that has not changed since it was last built
is left alone, so this is safe to repeat. A reviewer opening a candidate triggers the same step, so
running it first just means nobody waits.
"""

import argparse

from sqlalchemy import select

from app.clock import SystemClock
from app.config import get_settings
from app.models import TestSession
from app.services.video import ffmpeg
from app.services.video.assemble import ensure_assembled
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
                    TestSession.sitting_id == sitting.id, TestSession.video_deleted_at.is_(None)
                )
            ).all()
        )
        built = failed = 0
        for session_id, candidate in sessions:
            try:
                result = ensure_assembled(db, store, clock, settings, session_id)
            except ffmpeg.FfmpegMissing as problem:
                raise SystemExit(str(problem)) from problem
            built += len(result.segments)
            for segment, why in result.failed.items():
                failed += 1
                print(f"  {candidate}: segment {segment} could not be built: {why[:120]}")
    print(f"sitting {sitting.id} ({sitting.name}): {built} segments ready, {failed} failed")


if __name__ == "__main__":
    main()
