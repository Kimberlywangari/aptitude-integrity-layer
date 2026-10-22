"""Take a finished sitting from raw records to a ranked queue, step by step, timing each step.

    python -m scripts.jobs process_sitting --sitting <id or name>
                                           [--provider rules|ollama|claude] [--skip-video]

The order the pilot uses: compute flags, join the video, scan the audio, build packets, rank. The
video steps need ffmpeg and are skipped (with a note) when it is not installed or --skip-video is
given. Close the sitting first (close_sitting) so the cohort checks run.
"""

import argparse
from collections.abc import Callable

from sqlalchemy import select

from app.clock import SystemClock
from app.config import get_settings
from app.models import TestSession
from app.services.audio.silence import detect_silence
from app.services.flags.engine import compute_sitting_flags
from app.services.packets import build_sitting_packets
from app.services.ranking.base import RankerError, get_ranker
from app.services.ranking.runner import rank_sitting
from app.services.video import ffmpeg
from app.services.video.assemble import ensure_assembled
from app.services.video.store import LocalVideoStore
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
    clock = SystemClock()
    store = LocalVideoStore(settings.video_root_path)
    use_video = not args.skip_video and ffmpeg.available()

    def timed(label: str, step: Callable[[], str]) -> None:
        started = clock.now()
        note = step()
        took = (clock.now() - started).total_seconds()
        print(f"{label:<16} {took:7.1f} s  {note}")

    with SessionLocal() as db:
        sitting = resolve_sitting(db, args.sitting)
        print(f"sitting {sitting.id} ({sitting.name}, {sitting.status})")
        if sitting.status != "closed":
            print("  note: the sitting is still open, so the cohort checks will be skipped")

        def finished_sessions() -> list[str]:
            return list(
                db.scalars(
                    select(TestSession.id).where(
                        TestSession.sitting_id == sitting.id,
                        TestSession.status == "finished",
                        TestSession.video_deleted_at.is_(None),
                    )
                )
            )

        def flags() -> str:
            run = compute_sitting_flags(db, sitting.id, clock=clock)
            db.commit()
            cohort = "applied" if run.cohort_applied else "skipped"
            return f"{run.flags} flags on {run.flagged}/{run.sessions} sessions, cohort {cohort}"

        def assemble() -> str:
            segments = sum(
                len(ensure_assembled(db, store, clock, settings, sid).segments)
                for sid in finished_sessions()
            )
            return f"{segments} segments ready"

        def silence() -> str:
            found = sum(
                detect_silence(db, store, clock, settings, sid) for sid in finished_sessions()
            )
            return f"{found} quiet stretches"

        def packets() -> str:
            built = build_sitting_packets(db, clock, sitting.id)
            db.commit()
            return f"{built} packets"

        def ranking() -> str:
            run = rank_sitting(db, sitting.id, ranker, clock)
            db.commit()
            counts = ", ".join(f"{k} {v}" for k, v in sorted(run.statuses.items()))
            who = f"{ranker.name} {ranker.model}" if ranker else "rules only"
            return f"{run.flagged} ranked by {who} ({counts})"

        timed("compute flags", flags)
        if use_video:
            timed("assemble video", assemble)
            timed("scan audio", silence)
        else:
            print("video steps skipped (--skip-video, or ffmpeg is not installed)")
        timed("build packets", packets)
        timed("rank", ranking)


if __name__ == "__main__":
    main()
