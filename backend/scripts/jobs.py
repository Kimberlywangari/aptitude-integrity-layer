"""CLI entry point for the batch jobs: python -m scripts.jobs <name> [args]

Every job is one module in scripts/ with a main(argv); register a new one in JOBS below.
"""

import sys
from collections.abc import Callable

from scripts import (
    ai_cost,
    assemble_videos,
    build_packets,
    compute_flags,
    detect_silence,
    load_question_bank,
    loop,
    mark_incomplete_uploads,
    measure_false_flags,
    purge_videos,
    rank,
    reviewers,
    seed_synthetic,
    simulate_cohort,
)

JOBS: dict[str, Callable[[list[str]], None]] = {
    "seed_synthetic": seed_synthetic.main,
    "load_question_bank": load_question_bank.main,
    "simulate_cohort": simulate_cohort.main,
    "compute_flags": compute_flags.main,
    "assemble_videos": assemble_videos.main,
    "detect_silence": detect_silence.main,
    "build_packets": build_packets.main,
    "rank": rank.main,
    "ai_cost": ai_cost.main,
    "mark_incomplete_uploads": mark_incomplete_uploads.main,
    "purge_videos": purge_videos.main,
    "loop": loop.main,
    "measure_false_flags": measure_false_flags.main,
    "create_reviewer": reviewers.create_main,
    "deactivate_reviewer": reviewers.deactivate_main,
}


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in JOBS:
        names = ", ".join(sorted(JOBS))
        raise SystemExit(f"usage: python -m scripts.jobs <job> [args]\njobs: {names}")
    JOBS[argv[0]](argv[1:])


if __name__ == "__main__":
    main()
