"""The most a ranking run may spend on Claude: candidates past it keep the rule order, and nobody
is dropped. A stand-in ranker reports the tokens a real call would, so no money is spent."""

import pytest

from app.config import Settings
from app.services.ranking import pricing
from app.services.ranking.base import RankerResult
from app.services.ranking.rules import rule_order
from app.services.ranking.runner import BUDGET_REACHED, rank_sitting
from tests.integration.test_packets_and_ranking import Scripted, always

# 2,000 tokens in and 300 out at claude-sonnet-5-5 prices: (2000 x 2 + 300 x 10) / 1,000,000
CALL_USD = pricing.cost_usd("claude-sonnet-5-5", 2000, 300)


class Priced(Scripted):
    """Reports usage on every call, the way ClaudeRanker does."""

    name = "claude"
    model = "claude-sonnet-5-5"

    def assess(self, packet, violations=None):
        result = super().assess(packet, violations)
        return RankerResult(
            result.assessment, result.raw, {"input_tokens": 2000, "output_tokens": 300}
        )


def test_a_call_costs_what_the_published_price_says():
    assert CALL_USD == pytest.approx(0.007)


def test_past_the_budget_the_rest_keep_the_rule_order_and_nobody_is_dropped(db, sim, clock):
    flagged = len(rule_order(db, sim.sitting_id))
    assert flagged > 3
    ranker = Priced(always(4))

    run = rank_sitting(db, sim.sitting_id, ranker, clock, budget_usd=CALL_USD * 2.5)

    assert len(run.rankings) == flagged  # the guarantee holds with a budget too
    # checked before each candidate: 0, 0.007 and 0.014 are all under 0.0175, 0.021 is not
    assert len(ranker.calls) == 3
    assert run.statuses["ok"] == 3 and run.statuses["fallback"] == flagged - 3
    assert run.over_budget == flagged - 3
    assert run.spent_usd == pytest.approx(CALL_USD * 3)
    skipped = [r for r in run.rankings if r.ai_status == "fallback"]
    assert all(r.ai_attempts[0]["error"] == BUDGET_REACHED for r in skipped)
    assert all(r.ai_json is None and r.ai_seconds is None for r in skipped)
    assert len(run.seconds) == 3  # the timing statistics only count calls that were made


def test_with_no_budget_everyone_is_sent_and_the_spend_is_still_counted(db, sim, clock):
    flagged = len(rule_order(db, sim.sitting_id))
    ranker = Priced(always(3))

    run = rank_sitting(db, sim.sitting_id, ranker, clock)

    assert len(ranker.calls) == flagged and run.over_budget == 0
    assert run.spent_usd == pytest.approx(CALL_USD * flagged)


def test_a_local_model_is_free_so_a_budget_never_stops_it(db, sim, clock):
    flagged = len(rule_order(db, sim.sitting_id))
    ranker = Scripted(always(3))  # named "scripted", reports no tokens

    run = rank_sitting(db, sim.sitting_id, ranker, clock, budget_usd=0.0001)

    assert len(ranker.calls) == flagged and run.spent_usd == 0.0


def test_a_claude_model_with_no_recorded_price_is_refused_rather_than_spent_blind(db, sim, clock):
    ranker = Priced(always(3))
    ranker.model = "claude-future-9"

    with pytest.raises(pricing.UnknownModel):
        rank_sitting(db, sim.sitting_id, ranker, clock, budget_usd=1.0)
    assert ranker.calls == []


def test_the_setting_is_zero_for_no_limit_and_never_negative():
    assert Settings(_env_file=None).ai_run_budget_usd == 0.0
    assert Settings(_env_file=None, ai_run_budget_usd=1.5).ai_run_budget_usd == 1.5
    with pytest.raises(ValueError):
        Settings(_env_file=None, ai_run_budget_usd=-1)
