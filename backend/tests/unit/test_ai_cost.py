"""The cost arithmetic that backs docs/plan/claude-api-cost-estimate.md: published prices, the
estimate, and the ceiling that follows from two limits in the code."""

import pytest

from app.services.ranking import prompts
from app.services.ranking.claude import MAX_OUTPUT_TOKENS
from app.services.ranking.pricing import (
    BATCH_DISCOUNT,
    PRICES_USD_PER_MTOK,
    UnknownModel,
    cost_usd,
    price_of,
)
from app.services.ranking.runner import MAX_ATTEMPTS
from scripts import ai_cost
from tests.support import sample_packet

SONNET = "claude-sonnet-5-5"


# ------------------------------------------------------------------------------------ prices


def test_the_prices_are_the_published_ones():
    # https://platform.claude.com/docs/en/about-claude/pricing, read 19 Oct 2026
    assert PRICES_USD_PER_MTOK[SONNET] == (2.0, 10.0)
    assert PRICES_USD_PER_MTOK["claude-opus-5-5"] == (4.0, 20.0)
    assert PRICES_USD_PER_MTOK["claude-haiku-5-5"] == (0.10, 0.50)
    assert PRICES_USD_PER_MTOK["claude-fable-5-1"] == (10.0, 50.0)
    assert BATCH_DISCOUNT == 0.5


def test_a_million_tokens_each_way_costs_the_two_rates_added():
    assert cost_usd(SONNET, 1_000_000, 1_000_000) == pytest.approx(12.0)
    assert cost_usd(SONNET, 1_000_000, 0) == pytest.approx(2.0)
    assert cost_usd(SONNET, 0, 1_000_000) == pytest.approx(10.0)
    assert cost_usd(SONNET, 0, 0) == 0


def test_a_batch_costs_half():
    assert cost_usd(SONNET, 5000, 7000, batch=True) == pytest.approx(
        cost_usd(SONNET, 5000, 7000) / 2
    )


def test_a_model_with_no_recorded_price_is_refused_not_guessed():
    with pytest.raises(UnknownModel):
        price_of("claude-future-9")
    with pytest.raises(UnknownModel):
        cost_usd("", 1, 1)


# --------------------------------------------------------------------------------- estimate


def test_characters_become_tokens_rounded_up():
    assert ai_cost.tokens_from_chars(2500) == 1000
    assert ai_cost.tokens_from_chars(2501) == 1001
    assert ai_cost.tokens_from_chars(3951, 4.0) == 988


def test_the_estimate_is_the_priced_sum_of_input_answer_and_thinking():
    est = ai_cost.per_candidate(
        [2500, 2500, 5000], SONNET, answer_tokens=250, thinking_tokens=1500, attempts=1.3
    )
    # the median prompt is 2,500 characters = 1,000 tokens; the largest is 2,000
    assert (est.input_tokens, est.input_tokens_largest, est.output_tokens) == (1000, 2000, 1750)
    one = (1000 * 2 + 1750 * 10) / 1_000_000
    assert est.per_attempt_usd == pytest.approx(one)
    assert est.per_candidate_usd == pytest.approx(one * 1.3)


def test_more_thinking_never_costs_less():
    costs = [
        ai_cost.per_candidate([4000], SONNET, thinking_tokens=t).per_candidate_usd
        for t in ai_cost.THINKING_SENSITIVITY
    ]
    assert costs == sorted(costs) and len(set(costs)) == len(costs)


def test_a_dearer_model_costs_proportionally_more():
    sonnet = ai_cost.per_candidate([4000], SONNET).per_candidate_usd
    opus = ai_cost.per_candidate([4000], "claude-opus-5-5").per_candidate_usd
    haiku = ai_cost.per_candidate([4000], "claude-haiku-5-5").per_candidate_usd
    assert opus == pytest.approx(2 * sonnet)  # $4 and $20 against $2 and $10
    assert haiku == pytest.approx(sonnet / 20)  # $0.10 and $0.50


def test_a_real_packet_prompt_is_measured_in_characters():
    packet = sample_packet()
    chars = ai_cost.call_chars(packet)
    system, user = (m["content"] for m in prompts.build_messages(packet))
    assert chars == len(system) + len(user)
    assert chars > len(prompts.SYSTEM_PROMPT)


# ----------------------------------------------------------------------------------- ceiling


def test_the_ceiling_follows_from_two_limits_in_the_code():
    # These two constants are what the ceiling is built from. If either changes, the ceiling in
    # the cost document is out of date, so this test says so.
    assert MAX_ATTEMPTS == 2
    assert MAX_OUTPUT_TOKENS == 16000

    longest = ai_cost.tokens_from_chars(ai_cost.largest_call_chars())
    per_attempt = (longest * 2 + 16000 * 10) / 1_000_000
    assert ai_cost.ceiling_usd(SONNET) == pytest.approx(2 * per_attempt)
    assert 0.30 < ai_cost.ceiling_usd(SONNET) < 0.40  # about a third of a dollar per candidate


def test_the_ceiling_is_above_any_estimate_however_much_thinking_is_assumed():
    cap = ai_cost.ceiling_usd(SONNET)
    for thinking in (0, 1500, 6000, 15000):
        est = ai_cost.per_candidate([4851], SONNET, thinking_tokens=thinking, attempts=2)
        assert est.per_candidate_usd < cap


def test_the_largest_prompt_the_code_can_send_is_bigger_than_a_normal_one():
    assert ai_cost.largest_call_chars() > ai_cost.call_chars(sample_packet())
    assert ai_cost.largest_call_chars() >= prompts.MAX_PACKET_CHARS
