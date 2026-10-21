"""The measurement job must be safe to run in a database that already holds a simulated sitting
(the dev database does), and must leave that sitting exactly as it was."""

from sqlalchemy import func, select

from app.models import Candidate, Flag, Sitting, TestSession
from app.services.flags.config import DEFAULTS
from scripts.measure_false_flags import measure, parse_overrides
from scripts.simulate_cohort import SITTING_NAME, simulate


def test_it_runs_beside_an_existing_simulated_sitting_and_leaves_it_alone(db, seeded):
    simulate(db, seed=1)
    before = (
        db.scalar(select(func.count()).select_from(TestSession)),
        db.scalar(select(func.count()).select_from(Flag)),
        db.scalar(select(func.count()).select_from(Candidate)),
    )

    out = measure(db, cohorts=2, cfg=DEFAULTS)

    after = (
        db.scalar(select(func.count()).select_from(TestSession)),
        db.scalar(select(func.count()).select_from(Flag)),
        db.scalar(select(func.count()).select_from(Candidate)),
    )
    assert after == before  # the measurement removed everything it made, and nothing else
    assert db.scalar(select(Sitting).where(Sitting.name == SITTING_NAME)) is not None
    assert out["honest_n"] == 2 * 10
    assert set(out["recall"]) == {
        "tab_lookup",
        "copier",
        "answer_runner",
        "fast_correct",
        "logging_blocker",
    }


def test_thresholds_can_be_overridden_by_name():
    cfg = parse_overrides(["run_length=4", "run_gap_focus_s=10"])
    assert cfg.run_length == 4
    assert cfg.run_gap_focus_s == 10.0
    assert cfg.hold_factor == DEFAULTS.hold_factor  # everything else is left at the default


def test_an_unknown_threshold_is_refused_with_the_known_names():
    try:
        parse_overrides(["not_a_threshold=3"])
    except SystemExit as stop:
        assert "unknown threshold" in str(stop)
        assert "run_length" in str(stop)
    else:
        raise AssertionError("expected a refusal")
