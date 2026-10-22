"""CLI entry point for the batch jobs: python -m scripts.jobs <name> [args]

Every job is one module in scripts/ with a main(argv); register a new one in JOBS below.
"""

import sys
from collections.abc import Callable

from scripts import (
    ai_cost,
    ai_explanations,
    assemble_videos,
    build_packets,
    chunk_integrity,
    close_sitting,
    compute_flags,
    detect_silence,
    fetch_cytonn_bank,
    import_question_summary,
    load_question_bank,
    loop,
    mark_incomplete_uploads,
    measure_false_flags,
    pilot_metrics,
    process_sitting,
    purge_videos,
    rank,
    reviewers,
    seed_synthetic,
    simulate_cohort,
    video_offset,
)

JOBS: dict[str, Callable[[list[str]], None]] = {
    "seed_synthetic": seed_synthetic.main,
    "load_question_bank": load_question_bank.main,
    "fetch_cytonn_bank": fetch_cytonn_bank.main,
    "import_question_summary": import_question_summary.main,
    "simulate_cohort": simulate_cohort.main,
    "close_sitting": close_sitting.main,
    "compute_flags": compute_flags.main,
    "assemble_videos": assemble_videos.main,
    "detect_silence": detect_silence.main,
    "build_packets": build_packets.main,
    "rank": rank.main,
    "process_sitting": process_sitting.main,
    "chunk_integrity": chunk_integrity.main,
    "ai_explanations": ai_explanations.main,
    "ai_cost": ai_cost.main,
    "pilot_metrics": pilot_metrics.main,
    "video_offset": video_offset.main,
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
