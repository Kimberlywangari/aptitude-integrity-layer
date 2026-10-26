"""Take a finished sitting from raw records to a ranked queue, step by step, timing each step.

    python -m scripts.jobs process_sitting --sitting <id or name>
                                           [--provider rules|ollama|claude] [--skip-video]

The order the pilot uses: compute flags, join the video, scan the audio, build packets, rank. The
video steps need ffmpeg and are skipped (with a note) when it is not installed or --skip-video is
given. Close the sitting first (close_sitting) so the cohort checks run. The admin's "Process
sitting" button runs the same steps (services/processing.py).
"""

import argparse

from app.clock import SystemClock
from app.config import get_settings
from app.services.processing import Step, process_sitting
from app.services.ranking.base import RankerError, get_ranker
from app.services.video import ffmpeg
from scripts.common import add_sitting_argument, resolve_sitting


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_sitting_argument(parser)
    parser.add_argument("--provider", choices=("rules", "ollama", "claude"), default=None)
    parser.add_argument("--skip-video", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.provider:
        settings = settings.model_copy(update={"ai_provider": args.provider})
    try:
        ranker = get_ranker(settings)
    except RankerError as problem:
        raise SystemExit(f"cannot use {settings.ai_provider}: {problem}") from problem

    def show(step: Step) -> None:
        print(f"{step.label:<16} {step.seconds:7.1f} s  {step.note}")

    with SessionLocal() as db:
        sitting = resolve_sitting(db, args.sitting)
        print(f"sitting {sitting.id} ({sitting.name}, {sitting.status})")
        if sitting.status != "closed":
            print("  note: the sitting is still open, so the cohort checks will be skipped")
        use_video = not args.skip_video and ffmpeg.available()
        process_sitting(db, sitting.id, settings, SystemClock(), ranker, use_video, show)


if __name__ == "__main__":
    main()
