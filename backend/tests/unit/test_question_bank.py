"""Quality rules for the authored question bank (scripts/question_bank.json).

These guard what a reviewer would otherwise have to eyeball: complete items, one right answer per
question, answer positions spread evenly, and the same easy / medium / hard mix the synthetic
seed used. They cannot check that an answer is *right*; that was verified by recomputing it, and
the verbal items need a human reviewer.
"""

import json
from collections import Counter

import pytest

from scripts.load_question_bank import DEFAULT_BANK_PATH, validate

SECTION_RANGES = {
    "numerical": range(1, 21),
    "verbal": range(21, 41),
    "logical": range(41, 61),
}


@pytest.fixture(scope="module")
def bank():
    return json.loads(DEFAULT_BANK_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def questions(bank):
    return bank["questions"]


def test_the_file_is_structurally_valid(bank):
    assert validate(bank) == []


def test_sixty_questions_with_the_ids_the_database_already_uses(questions):
    assert [q["id"] for q in questions] == [f"Q{n:03d}" for n in range(1, 61)]


def test_each_section_owns_its_twenty_ids(questions):
    for section, numbers in SECTION_RANGES.items():
        in_section = [q for q in questions if int(q["id"][1:]) in numbers]
        assert len(in_section) == 20
        assert {q["section"] for q in in_section} == {section}


def test_each_section_has_7_easy_7_medium_6_hard(questions):
    for section in SECTION_RANGES:
        counts = Counter(q["difficulty"] for q in questions if q["section"] == section)
        assert counts == {"easy": 7, "medium": 7, "hard": 6}, section


def test_correct_answers_are_spread_across_a_to_d(questions):
    overall = Counter(q["correct"] for q in questions)
    assert set(overall) == {"A", "B", "C", "D"}
    assert all(12 <= n <= 18 for n in overall.values()), overall
    for section in SECTION_RANGES:
        by_section = Counter(q["correct"] for q in questions if q["section"] == section)
        assert all(3 <= by_section[label] <= 7 for label in "ABCD"), (section, by_section)


def test_no_question_text_or_option_set_is_repeated(questions):
    assert len({q["text"] for q in questions}) == len(questions)
    assert len({tuple(q["options"].values()) for q in questions}) == len(questions)


def test_nothing_is_left_as_placeholder(questions):
    for q in questions:
        everything = " ".join([q["text"], q["explanation"], *q["options"].values()]).lower()
        assert "placeholder" not in everything, q["id"]
        assert "todo" not in everything, q["id"]
        assert "lorem" not in everything, q["id"]


def test_the_correct_option_is_not_the_longest_every_time(questions):
    """A cheap tell: if the right answer is always the longest, test-wise candidates spot it."""
    longest = sum(
        1
        for q in questions
        if len(q["options"][q["correct"]]) == max(len(t) for t in q["options"].values())
        and len({len(t) for t in q["options"].values()}) > 1
    )
    assert longest <= 24, longest  # under 40% of the bank


def test_validate_reports_each_kind_of_fault():
    good = {
        "id": "Q001",
        "section": "numerical",
        "difficulty": "easy",
        "text": "What is 2 + 2?",
        "options": {"A": "3", "B": "4", "C": "5", "D": "6"},
        "correct": "B",
        "explanation": "2 + 2 = 4.",
    }
    assert validate({"version": 1, "questions": [good]}) == []

    def faults(**changes):
        return validate({"version": 1, "questions": [{**good, **changes}]})

    assert faults(id="X1")
    assert faults(difficulty="extreme")
    assert faults(text="   ")
    assert faults(correct="E")
    assert faults(options={"A": "3", "B": "4", "C": "5"})
    assert faults(options={"A": "3", "B": "3", "C": "5", "D": "6"})
    assert faults(explanation="")
    assert validate({"version": 2, "questions": [good]})
    assert validate({"version": 1, "questions": [good, good]})  # duplicate id
