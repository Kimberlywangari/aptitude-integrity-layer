import json
from collections import Counter
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.models import Option, Question, QuestionStats, Sitting, TestSession
from scripts.load_question_bank import DEFAULT_BANK_PATH, BankInUse, load_bank
from scripts.seed_synthetic import seed

BANK = json.loads(DEFAULT_BANK_PATH.read_text(encoding="utf-8"))
EXPECTED_BANDS = {"easy": (25, 0.85), "medium": (45, 0.60), "hard": (75, 0.35)}


@pytest.fixture
def seeded(db):
    seed(db, seed=42, secret="s", public_base_url="http://x")
    return db


def test_replaces_the_placeholders_in_place_and_keeps_every_id(seeded):
    ids_before = set(seeded.scalars(select(Question.id)))
    summary = load_bank(seeded, BANK)

    assert set(seeded.scalars(select(Question.id))) == ids_before
    assert summary.created == 0
    assert summary.updated == 60
    assert seeded.scalar(select(func.count()).select_from(Option)) == 240

    by_id = {item["id"]: item for item in BANK["questions"]}
    for question in seeded.scalars(select(Question)):
        item = by_id[question.id]
        assert question.text == item["text"]
        assert question.section == item["section"]
        assert question.difficulty == item["difficulty"]
        assert question.correct_option == item["correct"]
        assert {o.label: o.text for o in question.options} == item["options"]
        assert "placeholder" not in question.text.lower()


def test_each_section_keeps_the_7_7_6_mix(seeded):
    load_bank(seeded, BANK)
    rows = seeded.execute(select(Question.section, Question.difficulty)).all()
    by_section: dict[str, Counter] = {}
    for section, difficulty in rows:
        by_section.setdefault(section, Counter())[difficulty] += 1
    assert set(by_section) == {"numerical", "verbal", "logical"}
    for counts in by_section.values():
        assert counts == {"easy": 7, "medium": 7, "hard": 6}


def test_synthetic_statistics_follow_the_new_difficulty_and_stay_labelled_synthetic(seeded):
    load_bank(seeded, BANK)
    rows = seeded.execute(
        select(Question.difficulty, QuestionStats).join(
            QuestionStats, QuestionStats.question_id == Question.id
        )
    ).all()
    assert len(rows) == 60
    for difficulty, stats in rows:
        median, pct = EXPECTED_BANDS[difficulty]
        assert stats.source == "synthetic"
        assert 0.8 * median - 0.1 <= stats.median_s <= 1.2 * median + 0.1
        assert 0.8 * pct - 0.001 <= stats.pct_correct <= min(0.99, 1.2 * pct) + 0.001
        assert stats.p25_s <= stats.median_s <= stats.p75_s


def test_running_it_twice_changes_nothing(seeded):
    load_bank(seeded, BANK)
    again = load_bank(seeded, BANK)
    assert (again.created, again.updated, again.unchanged) == (0, 0, 60)


def test_never_touches_statistics_that_came_from_cytonn(seeded):
    stats = seeded.get(QuestionStats, "Q010")
    stats.source = "cytonn"
    stats.n, stats.pct_correct = 912, 0.51
    stats.median_s, stats.p25_s, stats.p75_s = 33.0, 20.0, 50.0
    seeded.flush()

    summary = load_bank(seeded, BANK)

    kept = seeded.get(QuestionStats, "Q010")
    assert (kept.source, kept.n, kept.pct_correct, kept.median_s) == ("cytonn", 912, 0.51, 33.0)
    assert summary.stats_kept_cytonn == 1
    assert summary.stats_refreshed == 59


def test_refuses_while_a_session_is_in_progress_unless_forced(seeded):
    sitting = seeded.scalar(select(Sitting))
    now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    seeded.add(
        TestSession(
            id="s" * 32,
            candidate_id="cand-001",
            sitting_id=sitting.id,
            status="in_progress",
            created_at=now,
            started_at=now,
        )
    )
    seeded.flush()

    with pytest.raises(BankInUse):
        load_bank(seeded, BANK)
    assert "placeholder" in seeded.get(Question, "Q001").text.lower()  # nothing was changed

    assert load_bank(seeded, BANK, force=True).updated == 60


def test_an_invalid_bank_is_rejected_before_anything_changes(seeded):
    broken = json.loads(json.dumps(BANK))
    broken["questions"][0]["correct"] = "Z"
    with pytest.raises(ValueError, match="Q001"):
        load_bank(seeded, broken)
    assert "placeholder" in seeded.get(Question, "Q001").text.lower()


def test_creates_a_question_that_does_not_exist_yet(db):
    summary = load_bank(db, BANK)  # empty database: nothing was seeded
    assert summary.created == 60
    assert db.scalar(select(func.count()).select_from(Question)) == 60
    assert db.scalar(select(func.count()).select_from(QuestionStats)) == 60
