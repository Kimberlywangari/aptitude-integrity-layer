"""The per-question check against past sittings: when a question's history is trustworthy enough to
compare with, and how a baseline that is partly made up announces itself."""

from datetime import UTC, datetime, timedelta

from app.services.flags.config import FlagConfig
from app.services.flags.rules import FAST_CORRECT_VS_HISTORY, Answer, baseline, fast_correct_flags

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def answer(
    position, time_s, *, correct=True, difficulty="medium", p25=40.0, n=400, source="cytonn"
):
    opened = T0 + timedelta(minutes=position)
    return Answer(
        position=position,
        question_id=f"Q{position:03d}",
        difficulty=difficulty,
        opened_at=opened,
        answered_at=opened + timedelta(seconds=time_s),
        correct=correct,
        p25_s=p25,
        stats_n=n,
        stats_source=source,
    )


def test_two_fast_correct_answers_are_flagged_with_the_history_source():
    (flag,) = fast_correct_flags([answer(1, 10), answer(2, 12)])
    assert flag.kind == FAST_CORRECT_VS_HISTORY
    assert flag.detail["history_source"] == "cytonn"
    assert flag.detail["questions"] == [1, 2]


def test_a_baseline_with_any_estimated_question_is_labelled_synthetic():
    (flag,) = fast_correct_flags([answer(1, 10), answer(2, 12, source="synthetic")])
    assert flag.detail["history_source"] == "synthetic"


def test_a_question_with_too_little_history_is_ignored():
    # 29 past candidates is not enough to know what "quick" is for that question
    assert fast_correct_flags([answer(1, 10, n=29), answer(2, 12, n=29)]) == []
    # one good question plus one thin one leaves a single hit, which is not enough on its own
    assert fast_correct_flags([answer(1, 10), answer(2, 12, n=29)]) == []
    assert len(fast_correct_flags([answer(1, 10, n=30), answer(2, 12, n=30)])) == 1


def test_unknown_history_size_is_trusted_so_pure_callers_need_not_say():
    plain = [answer(1, 10, n=None), answer(2, 12, n=None)]
    assert len(fast_correct_flags(plain)) == 1


def test_the_minimum_history_can_be_changed():
    cfg = FlagConfig(fast_min_history_n=500)
    assert fast_correct_flags([answer(1, 10), answer(2, 12)], cfg) == []


def test_one_fast_answer_or_a_fast_wrong_answer_is_not_a_flag():
    assert fast_correct_flags([answer(1, 10), answer(2, 80)]) == []
    assert fast_correct_flags([answer(1, 10), answer(2, 12, correct=False)]) == []


def test_hard_questions_use_the_larger_factor():
    # 0.5 x 40 = 20 s for medium; hard allows 0.75 x 40 = 30 s
    assert fast_correct_flags([answer(1, 25), answer(2, 26)]) == []
    hard = [answer(1, 25, difficulty="hard"), answer(2, 26, difficulty="hard")]
    assert len(fast_correct_flags(hard)) == 1


def test_baseline_is_the_median_and_the_raw_median_absolute_deviation():
    assert baseline([10, 12, 14, 16, 18]) == (14, 2)
    assert baseline([5.0, 5.0, 5.0]) == (5.0, 0.0)
