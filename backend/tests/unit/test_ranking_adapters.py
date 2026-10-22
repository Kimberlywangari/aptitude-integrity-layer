"""The two model adapters against stand-in servers: Ollama over a mocked HTTP transport, Claude
through a stand-in client. Neither needs a model, a network or a key."""

import json

import httpx
import pytest

from app.config import Settings
from app.services.ranking.base import Assessment, RankerError, RankerResult, get_ranker
from app.services.ranking.claude import ClaudeRanker
from app.services.ranking.ollama import OPTIONS, OllamaRanker
from tests.support import good_assessment, sample_packet


def ollama_with(handler) -> OllamaRanker:
    client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))
    return OllamaRanker("http://ollama.test", "qwen-test", 30, client=client)


def reply(content, status=200):
    body = {"message": {"role": "assistant", "content": content}}
    return httpx.Response(status, json=body)


# ------------------------------------------------------------------------------------ Ollama


def test_ollama_returns_a_parsed_assessment_and_the_raw_text():
    packet = sample_packet()
    answer = json.dumps(good_assessment(packet))
    ranker = ollama_with(lambda request: reply(answer))

    result = ranker.assess(packet)

    assert isinstance(result, RankerResult)
    assert result.assessment.strength == 3 and result.raw == answer


def test_ollama_is_asked_for_schema_constrained_json_at_temperature_zero():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return reply(json.dumps(good_assessment(sample_packet())))

    ollama_with(handler).assess(sample_packet())

    body = seen["body"]
    assert seen["path"] == "/api/chat"
    assert body["model"] == "qwen-test" and body["stream"] is False
    assert body["format"]["properties"]["strength"]["maximum"] == 5  # the Assessment schema
    assert body["options"] == OPTIONS and OPTIONS["temperature"] == 0
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_a_retry_puts_the_violations_in_the_prompt():
    seen = {}

    def handler(request):
        seen["user"] = json.loads(request.content)["messages"][1]["content"]
        return reply(json.dumps(good_assessment(sample_packet())))

    ollama_with(handler).assess(sample_packet(), ["unknown_time: 999"])
    assert "unknown_time: 999" in seen["user"]


def test_a_model_with_no_thinking_mode_is_asked_again_without_the_switch():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append("think" in body)
        if "think" in body:
            return httpx.Response(400, text='{"error":"model does not support think"}')
        return reply(json.dumps(good_assessment(sample_packet())))

    result = ollama_with(handler).assess(sample_packet())
    assert calls == [True, False] and result.assessment.strength == 3


def test_ollama_down_is_one_ranker_error():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(RankerError, match="could not be reached"):
        ollama_with(handler).assess(sample_packet())


def test_ollama_too_slow_is_one_ranker_error():
    def handler(request):
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(RankerError, match="too long"):
        ollama_with(handler).assess(sample_packet())


def test_an_http_error_is_one_ranker_error():
    with pytest.raises(RankerError):
        ollama_with(lambda request: httpx.Response(500, text="boom")).assess(sample_packet())


def test_an_answer_that_is_not_json_keeps_its_raw_text_for_the_audit():
    with pytest.raises(RankerError) as caught:
        ollama_with(lambda request: reply("Sure! Here is my answer.")).assess(sample_packet())
    assert caught.value.raw == "Sure! Here is my answer."


def test_an_answer_that_breaks_the_schema_is_refused():
    wrong = json.dumps(good_assessment(sample_packet(), strength=9))
    with pytest.raises(RankerError, match="schema") as caught:
        ollama_with(lambda request: reply(wrong)).assess(sample_packet())
    assert caught.value.raw == wrong


def test_a_reply_without_a_message_is_refused():
    with pytest.raises(RankerError, match="expected shape"):
        ollama_with(lambda request: httpx.Response(200, json={"oops": 1})).assess(sample_packet())


# ------------------------------------------------------------------------------------ Claude


class FakeBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, parsed=None, text="", stop_reason="end_turn"):
        self.parsed_output = parsed
        self.content = [FakeBlock(text)] if text else []
        self.stop_reason = stop_reason


class FakeClient:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.messages = self
        self._response, self._error = response, error

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._response


def claude_with(client) -> ClaudeRanker:
    return ClaudeRanker("claude-sonnet-5-5", client=client)


def test_claude_returns_the_parsed_assessment():
    packet = sample_packet()
    parsed = Assessment.model_validate(good_assessment(packet))
    client = FakeClient(FakeResponse(parsed, text=parsed.model_dump_json()))

    result = claude_with(client).assess(packet)

    assert result.assessment == parsed and result.raw == parsed.model_dump_json()
    (call,) = client.calls
    assert call["model"] == "claude-sonnet-5-5"
    assert call["output_format"] is Assessment
    assert call["output_config"] == {"effort": "low"}
    assert "never give a verdict" in call["system"]
    assert "Evidence packet" in call["messages"][0]["content"]


def test_claude_is_told_what_the_first_answer_got_wrong():
    packet = sample_packet()
    parsed = Assessment.model_validate(good_assessment(packet))
    client = FakeClient(FakeResponse(parsed))

    claude_with(client).assess(packet, ["unknown_time: 999"])

    assert "unknown_time: 999" in client.calls[0]["messages"][0]["content"]


def test_a_refusal_is_a_ranker_error_so_the_rule_order_takes_over():
    client = FakeClient(FakeResponse(None, text="", stop_reason="refusal"))
    with pytest.raises(RankerError, match="declined"):
        claude_with(client).assess(sample_packet())


def test_an_answer_the_sdk_could_not_parse_is_a_ranker_error():
    client = FakeClient(FakeResponse(None, text="not json", stop_reason="end_turn"))
    with pytest.raises(RankerError, match="no usable answer") as caught:
        claude_with(client).assess(sample_packet())
    assert caught.value.raw == "not json"


def test_a_failed_api_call_is_a_ranker_error():
    with pytest.raises(RankerError, match="call failed"):
        claude_with(FakeClient(error=RuntimeError("429 rate limited"))).assess(sample_packet())


# ---------------------------------------------------------------------------- the provider


def test_the_provider_is_chosen_in_one_place():
    assert get_ranker(Settings(ai_provider="rules")) is None
    ollama = get_ranker(Settings(ai_provider="ollama", ollama_model="qwen-test"))
    assert ollama.name == "ollama" and ollama.model == "qwen-test"


def test_claude_without_the_sdk_installed_says_how_to_get_it(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no anthropic here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(RankerError, match=r"pip install -e"):
        get_ranker(Settings(ai_provider="claude"))
