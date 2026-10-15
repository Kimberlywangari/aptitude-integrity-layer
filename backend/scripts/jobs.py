"""CLI entry point for the batch jobs: python -m scripts.jobs <name> [args]

Later days register more jobs here (compute_flags, build_packets, rank, purge_videos, ...).
"""

import sys
from collections.abc import Callable

from scripts import (
    compute_flags,
    load_question_bank,
    measure_false_flags,
    reviewers,
    seed_synthetic,
    simulate_cohort,
)

JOBS: dict[str, Callable[[list[str]], None]] = {
    "seed_synthetic": seed_synthetic.main,
    "load_question_bank": load_question_bank.main,
    "simulate_cohort": simulate_cohort.main,
    "compute_flags": compute_flags.main,
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
