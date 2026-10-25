"""How often do the flag thresholds flag an honest candidate, and do they still find the scripted
cases? The measurement the plan asks for before any threshold is trusted (master plan R10, D10).

    python -m scripts.jobs measure_false_flags [--cohorts 40] [--set run_length=4 ...]

It simulates many cohorts (scripts/simulate_cohort.py), computes flags with the thresholds you
give it, and prints the rates. Everything happens inside one transaction that is rolled back, so
nothing is left behind even if it is interrupted.

Read the result with care. The honest behaviour is the simulator's assumption, and the scripted
cases are stark by construction, so the recall figure is flattering: real cheating is subtler.
The false-flag figure depends on how closely the simulated honest people resemble real ones. Once
Cytonn's sittings exist, run the same rules over them instead.
"""

import argparse
from collections import defaultdict
from dataclasses import fields, replace

from sqlalchemy import select

from app.models import Flag, TestSession
from app.services.flags.config import DEFAULTS, FlagConfig
from app.services.flags.engine import compute_sitting_flags
from scripts.simulate_cohort import purge, simulate

MEASURE_PREFIX = "measure"
HONEST = {"honest", "honest_fast", "honest_tech"}
EXPECTED = {
    "tab_lookup": "LONG_HOLD_CORRECT",
    "copier": "COPY_ATTEMPT",
    "answer_runner": "CORRECT_RUN_AFTER_GAP",
    "logging_blocker": "LOGGING_PROBLEM",
}


def parse_overrides(pairs: list[str]) -> FlagConfig:
    known = {f.name: f.type for f in fields(FlagConfig)}
    changes: dict[str, float | int] = {}
    for pair in pairs:
        name, _, raw = pair.partition("=")
        if name not in known:
            raise SystemExit(f"unknown threshold {name!r}; known: {', '.join(sorted(known))}")
        changes[name] = int(raw) if known[name] in (int, "int") else float(raw)
    return replace(DEFAULTS, **changes)


def measure(db, cohorts: int, cfg: FlagConfig) -> dict:
    honest_n = honest_beyond = 0
    kinds_on_honest: dict[str, int] = defaultdict(int)
    recall: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    for seed in range(1, cohorts + 1):
        name = f"measure-false-flags {seed}"
        # its own candidate names, so it can run beside a simulated sitting that already exists
        result = simulate(db, seed=seed, name=name, prefix=MEASURE_PREFIX)
        compute_sitting_flags(db, result.sitting_id, cfg)  # simulate() used the defaults
        by_candidate: dict[str, set[str]] = defaultdict(set)
        for candidate, kind in db.execute(
            select(TestSession.candidate_id, Flag.kind)
            .join(Flag, Flag.session_id == TestSession.id)
            .where(TestSession.sitting_id == result.sitting_id)
        ):
            by_candidate[candidate].add(kind)

        for candidate, archetype in result.by_archetype.items():
            kinds = by_candidate.get(candidate, set())
            if archetype in HONEST:
                honest_n += 1
                extra = kinds - {"FOCUS_LOSS"}
                if extra:
                    honest_beyond += 1
                    for kind in extra:
                        kinds_on_honest[kind] += 1
            elif archetype in EXPECTED:
                recall[archetype][1] += 1
                recall[archetype][0] += EXPECTED[archetype] in kinds
        purge(db, name, prefix=MEASURE_PREFIX)
    return {
        "honest_n": honest_n,
        "honest_beyond_focus": honest_beyond,
        "kinds_on_honest": dict(kinds_on_honest),
        "recall": {a: tuple(v) for a, v in recall.items()},
    }


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cohorts", type=int, default=40, help="how many simulated cohorts of 16")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="override a threshold from app/services/flags/config.py",
    )
    args = parser.parse_args(argv)
    cfg = parse_overrides(args.set)

    with SessionLocal() as db:
        try:
            out = measure(db, args.cohorts, cfg)
        finally:
            db.rollback()  # nothing from the measurement is ever kept

    n, bad = out["honest_n"], out["honest_beyond_focus"]
    changed = {
        f.name: getattr(cfg, f.name)
        for f in fields(cfg)
        if getattr(cfg, f.name) != getattr(DEFAULTS, f.name)
    }
    print(
        f"{args.cohorts} simulated cohorts of 16; "
        f"thresholds changed from the defaults: {changed or 'none'}"
    )
    print(
        "honest candidates flagged beyond a lone loss of focus: "
        f"{bad} of {n} ({100 * bad / n:.1f}%)"
    )
    print(f"  what fired on them: {out['kinds_on_honest'] or 'nothing'}")
    print("scripted cases found:")
    for archetype, (hit, seen) in sorted(out["recall"].items()):
        rate = 100 * hit / seen
        print(f"  {archetype:16} {hit}/{seen} ({rate:.0f}%)  expects {EXPECTED[archetype]}")


if __name__ == "__main__":
    main()
