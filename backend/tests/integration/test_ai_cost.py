"""Metering: every AI call keeps the token counts the provider reported, and the spend for a
sitting is worked out from those counts, so after a real run the cost is measured, not estimated."""

from types import SimpleNamespace

import pytest

from app.services.ranking.base import RankerError, RankerResult
from app.services.ranking.claude import MAX_OUTPUT_TOKENS, ClaudeRanker
from app.services.ranking.pricing import cost_usd
from app.services.ranking.runner import rank_sitting
from scripts.ai_cost import actual_for_sitting
from tests.integration.test_packets_and_ranking import hallucinating, passing
from tests.support import good_assessment, sample_packet

USAGE = {"input_tokens": 1600, "output_tokens": 2000}


class Metered:
    """A stand-in provider that reports usage on every call."""

    def __init__(self, name="claude", model="claude-sonnet-5-5", usage=USAGE, plan=None):
        self.name, self.model, self.usage = name, model, usage
        self.plan = plan or (lambda packet, attempt: passing(packet))
        self.calls: dict[str, int] = {}

    def assess(self, packet, violations=None):
        who = packet["candidate_id"]
        self.calls[who] = self.calls.get(who, 0) + 1
        assessment = self.plan(packet, self.calls[who])
        return RankerResult(assessment, assessment.model_dump_json(), self.usage)


# ------------------------------------------------------------------------ in the runner


def test_every_attempt_keeps_the_tokens_the_provider_reported(db, sim, clock):
    run = rank_sitting(db, sim.sitting_id, Metered(), clock)
    for ranking in run.rankings:
        (attempt,) = ranking.ai_attempts
        assert attempt["usage"] == USAGE


def test_a_retry_is_billed_too_so_both_attempts_are_kept(db, sim, clock):
    flaky = Metered(
        plan=lambda p, attempt: hallucinating(p, attempt, None) if attempt == 1 else passing(p)
    )
    run = rank_sitting(db, sim.sitting_id, flaky, clock)
    for ranking in run.rankings:
        assert [a["usage"] for a in ranking.ai_attempts] == [USAGE, USAGE]


def test_a_refused_or_unusable_answer_still_carries_its_usage(db, sim, clock):
    class Refuses:
        name, model = "claude", "claude-sonnet-5-5"

        def assess(self, packet, violations=None):
            raise RankerError(
                "Claude declined to assess this packet",
                None,
                {"input_tokens": 900, "output_tokens": 40},
            )

    run = rank_sitting(db, sim.sitting_id, Refuses(), clock)
    attempts = run.rankings[0].ai_attempts
    assert [a["usage"] for a in attempts] == [{"input_tokens": 900, "output_tokens": 40}] * 2
    assert all(a["error"] for a in attempts)


# ------------------------------------------------------------------------- the spend report


def test_the_spend_is_the_reported_tokens_at_the_published_price(db, sim, clock):
    run = rank_sitting(db, sim.sitting_id, Metered(), clock)
    n = run.flagged

    result = actual_for_sitting(db, sim.sitting_id)

    assert (result.candidates, result.attempts, result.unmetered_attempts) == (n, n, 0)
    assert (result.input_tokens, result.output_tokens) == (n * 1600, n * 2000)
    assert result.usd == pytest.approx(n * cost_usd("claude-sonnet-5-5", 1600, 2000))
    assert result.by_model == {"claude-sonnet-5-5": pytest.approx(result.usd)}


def test_retries_count_as_spend(db, sim, clock):
    flaky = Metered(
        plan=lambda p, attempt: hallucinating(p, attempt, None) if attempt == 1 else passing(p)
    )
    run = rank_sitting(db, sim.sitting_id, flaky, clock)

    result = actual_for_sitting(db, sim.sitting_id)

    assert result.attempts == 2 * run.flagged
    assert result.usd == pytest.approx(2 * run.flagged * cost_usd("claude-sonnet-5-5", 1600, 2000))


def test_a_local_model_is_counted_but_costs_nothing(db, sim, clock):
    run = rank_sitting(db, sim.sitting_id, Metered(name="ollama", model="qwen-test"), clock)

    result = actual_for_sitting(db, sim.sitting_id)

    assert result.usd == 0 and result.input_tokens == 0
    assert result.local_input_tokens == run.flagged * 1600


def test_a_rules_only_run_spent_nothing(db, sim, clock):
    rank_sitting(db, sim.sitting_id, None, clock)
    result = actual_for_sitting(db, sim.sitting_id)
    assert (result.candidates, result.attempts, result.usd) == (0, 0, 0)


def test_calls_with_no_recorded_usage_are_called_out_not_hidden(db, sim, clock):
    class Silent:
        name, model = "claude", "claude-sonnet-5-5"

        def assess(self, packet, violations=None):
            raise RankerError("the Claude API call failed: connection reset")

    run = rank_sitting(db, sim.sitting_id, Silent(), clock)
    result = actual_for_sitting(db, sim.sitting_id)
    assert result.unmetered_attempts == 2 * run.flagged and result.usd == 0


# ----------------------------------------------------------------------------- the adapters


class FakeBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, parsed=None, text="", stop_reason="end_turn", usage=None):
        self.parsed_output, self.stop_reason = parsed, stop_reason
        self.content = [FakeBlock(text)] if text else []
        if usage is not None:
            self.usage = SimpleNamespace(**usage)


class FakeClient:
    def __init__(self, response):
        self.messages, self.calls, self._response = self, [], response

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_claude_reports_the_usage_on_its_response():
    from app.services.ranking.base import Assessment

    packet = sample_packet()
    parsed = Assessment.model_validate(good_assessment(packet))
    client = FakeClient(
        FakeResponse(parsed, text="{}", usage={"input_tokens": 1581, "output_tokens": 1900})
    )

    result = ClaudeRanker("claude-sonnet-5-5", client=client).assess(packet)

    assert result.usage == {"input_tokens": 1581, "output_tokens": 1900}
    assert client.calls[0]["max_tokens"] == MAX_OUTPUT_TOKENS  # the cap the ceiling relies on


def test_a_refusal_is_billed_so_it_carries_its_usage():
    client = FakeClient(
        FakeResponse(None, stop_reason="refusal", usage={"input_tokens": 1500, "output_tokens": 12})
    )
    with pytest.raises(RankerError) as caught:
        ClaudeRanker("claude-sonnet-5-5", client=client).assess(sample_packet())
    assert caught.value.usage == {"input_tokens": 1500, "output_tokens": 12}


def test_a_response_with_no_usage_field_gives_none():
    from app.services.ranking.base import Assessment

    parsed = Assessment.model_validate(good_assessment(sample_packet()))
    result = ClaudeRanker("claude-sonnet-5-5", client=FakeClient(FakeResponse(parsed))).assess(
        sample_packet()
    )
    assert result.usage is None


def test_ollama_reports_its_own_counts():
    import json

    import httpx

    from app.services.ranking.ollama import OllamaRanker

    packet = sample_packet()
    body = {
        "message": {"role": "assistant", "content": json.dumps(good_assessment(packet))},
        "prompt_eval_count": 1234,
        "eval_count": 321,
    }
    client = httpx.Client(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    )
    result = OllamaRanker("http://ollama.test", "qwen-test", 30, client=client).assess(packet)
    assert result.usage == {"input_tokens": 1234, "output_tokens": 321}
