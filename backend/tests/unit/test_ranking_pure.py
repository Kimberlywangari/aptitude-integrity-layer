"""The AI step's guard rails, with no database and no model: the assessment schema, the fact check,
the prompt, and how a rule score becomes a strength."""

import json

import pytest
from pydantic import ValidationError

from app.services.ranking import prompts
from app.services.ranking.base import Assessment
from app.services.ranking.factcheck import fact_check
from app.services.ranking.rules import STRENGTH_CUTS, strength_bucket
from tests.support import good_assessment, sample_packet


def check(packet, **overrides):
    return fact_check(Assessment.model_validate(good_assessment(packet, **overrides)), packet)


# ------------------------------------------------------------------------------------ schema


def test_a_good_assessment_is_accepted_and_passes_the_fact_check():
    packet = sample_packet()
    assessment = Assessment.model_validate(good_assessment(packet))
    assert assessment.strength == 3
    assert fact_check(assessment, packet) == []


@pytest.mark.parametrize("strength", [0, 6, 7, -1, 2.5, "3"])
def test_a_strength_outside_one_to_five_is_not_an_assessment(strength):
    with pytest.raises(ValidationError):
        Assessment.model_validate(good_assessment(sample_packet(), strength=strength))


def test_an_explanation_over_eighty_words_is_not_an_assessment():
    longer = " ".join(["word"] * 81)
    with pytest.raises(ValidationError):
        Assessment.model_validate(good_assessment(sample_packet(), explanation=longer))
    exactly = " ".join(["word"] * 80)
    assert Assessment.model_validate(good_assessment(sample_packet(), explanation=exactly))


def test_extra_fields_and_missing_fields_are_refused():
    answer = good_assessment(sample_packet())
    with pytest.raises(ValidationError):
        Assessment.model_validate({**answer, "verdict": "guilty"})
    del answer["cited"]
    with pytest.raises(ValidationError):
        Assessment.model_validate(answer)


def test_support_must_be_yes_partly_or_no():
    with pytest.raises(ValidationError):
        Assessment.model_validate(
            good_assessment(sample_packet(), flags_support_each_other="definitely")
        )


# ------------------------------------------------------------------------------- fact check

HALLUCINATIONS = {
    "a flag id that is not in the packet": (
        {"cited": {"flag_ids": ["F9"], "question_numbers": [], "times_s": [], "counts": {}}},
        "unknown_flag_id",
    ),
    "a question number that is not in the packet": (
        {"cited": {"flag_ids": [], "question_numbers": [99], "times_s": [], "counts": {}}},
        "unknown_question_number",
    ),
    "a time that is not in the packet": (
        {"cited": {"flag_ids": [], "question_numbers": [], "times_s": [999], "counts": {}}},
        "unknown_time",
    ),
    "a count that does not match": (
        {"cited": {"flag_ids": [], "question_numbers": [], "times_s": [], "counts": {"flags": 5}}},
        "count_mismatch",
    ),
    "a count the packet never made": (
        {
            "cited": {
                "flag_ids": [],
                "question_numbers": [],
                "times_s": [],
                "counts": {"phone_calls": 1},
            }
        },
        "count_mismatch",
    ),
    "a verdict word": (
        {"explanation": "The candidate cheated on Q9."},
        "verdict_word",
    ),
    "another verdict word": (
        {"explanation": "This is dishonest behaviour."},
        "verdict_word",
    ),
    "a number in the text that is not in the packet": (
        {"explanation": "F1 happened 777 s in."},
        "number_not_in_facts",
    ),
    "a question reference that is not in the packet": (
        {"explanation": "Look at Q99 and F1."},
        "unknown_question_reference",
    ),
    "a question written out in words": (
        {"explanation": "See question 41 for F2."},
        "unknown_question_reference",
    ),
    "the wrong candidate": (
        {"candidate_id": "cand-999"},
        "wrong_candidate_id",
    ),
    "an evidence id that is not in the packet": (
        {"innocent_explanation": {"present": True, "evidence_ids": ["I7"]}},
        "unknown_evidence_id",
    ),
}


@pytest.mark.parametrize("what", HALLUCINATIONS)
def test_each_kind_of_invented_fact_is_caught(what):
    overrides, rule = HALLUCINATIONS[what]
    rules = {v.rule for v in check(sample_packet(), **overrides)}
    assert rule in rules


def test_a_violation_says_which_rule_failed_and_what_value_was_unknown():
    (violation,) = check(
        sample_packet(),
        cited={"flag_ids": [], "question_numbers": [], "times_s": [999], "counts": {}},
    )
    assert violation.rule == "unknown_time" and violation.value == "999"
    assert str(violation) == "unknown_time: 999"


def test_a_decimal_that_is_in_a_flag_may_be_quoted():
    packet = sample_packet()
    packet["flags"][0]["detail"]["robust_z"] = 3.4
    assert check(packet, explanation="F1 has a robust z of 3.4 on Q9.") == []
    assert {v.rule for v in check(packet, explanation="F1 has a robust z of 3.5 on Q9.")} == {
        "number_not_in_facts"
    }


def test_flag_and_signal_ids_and_the_candidate_id_are_not_counted_as_numbers():
    explanation = "cand-007 shows F1, F2, I1 and M1."
    assert check(sample_packet(), explanation=explanation) == []


def test_a_repeated_problem_is_reported_once():
    violations = check(sample_packet(), explanation="777 and 777 and 777 seconds.")
    assert [v.rule for v in violations].count("number_not_in_facts") == 1


# ----------------------------------------------------------------------------------- prompts


def test_the_prompt_forbids_verdicts_and_guessing_and_the_packet_goes_in_whole():
    packet = sample_packet()
    system, user = [m["content"] for m in prompts.build_messages(packet)]
    assert "never give a verdict" in system and "disqualify or reject" in system
    assert "Do not guess at reasons or methods" in system
    assert json.dumps(packet["facts"]) in user
    assert '"strength"' in user  # the schema is there


def test_the_prompt_carries_nothing_that_names_a_person():
    text = json.dumps(prompts.build_messages(sample_packet()))
    for forbidden in ("token", "email", "password", "invite"):
        assert forbidden not in text.lower()


def test_a_retry_tells_the_model_what_was_wrong():
    messages = prompts.build_messages(sample_packet(), ["unknown_time: 999", "verdict_word: cheat"])
    user = messages[1]["content"]
    assert "not in the packet" in user and "unknown_time: 999" in user
    assert "verdict_word: cheat" in user
    assert "Problems found" not in prompts.build_messages(sample_packet())[1]["content"]


def test_a_short_packet_is_sent_unchanged():
    packet = sample_packet()
    assert prompts.compact(packet) is packet


def test_a_long_packet_loses_context_first_then_repeated_focus_detail_but_never_a_flag():
    packet = sample_packet()
    for n in range(40):
        packet["flags"].append(
            {
                "id": f"F{n + 3}",
                "kind": "FOCUS_LOSS",
                "server_ts": "2026-10-28T09:20:00Z",
                "elapsed_s": 1200 + n,
                "question_number": 22,
                "detail": {"focus_lost_s": 4 + n, "note": "x" * 40},
            }
        )
    small = prompts.compact(packet, max_chars=4000)

    assert "precheck" not in small and "fullscreen_exits" not in small
    assert len(small["flags"]) == len(packet["flags"])  # nobody and nothing removed
    assert small["facts"] == packet["facts"]
    focus = [f for f in small["flags"] if f["kind"] == "FOCUS_LOSS"]
    assert all(f["detail"] for f in focus[: prompts.KEEP_FOCUS_DETAIL])
    assert all(f["detail"] == {} for f in focus[prompts.KEEP_FOCUS_DETAIL :])
    assert small["flags"][0]["detail"] == packet["flags"][0]["detail"]  # a copy flag is untouched


# --------------------------------------------------------------------------------- strength


def test_a_rule_score_maps_onto_one_to_five_at_the_cut_points():
    assert STRENGTH_CUTS == (2.0, 4.0, 6.0, 9.0)
    cases = [(0.5, 1), (1.0, 1), (1.99, 1), (2.0, 2), (3.9, 2), (4.0, 3), (6.0, 4), (8.9, 4)]
    cases += [(9.0, 5), (20.0, 5)]
    for score, expected in cases:
        assert strength_bucket(score) == expected, score


def test_a_gap_in_the_record_alone_is_always_strength_one():
    assert strength_bucket(50.0, logging_only=True) == 1
