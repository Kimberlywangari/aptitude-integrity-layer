"""The two providers, with a fake HTTP server for Ollama and a stand-in client for Claude. Neither
test touches a real model."""

import json
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.services.qgen import writers
from app.services.qgen.categories import CATEGORIES
from app.services.qgen.schema import RawBatch, RawQuestion, SolvedBatch
from app.services.qgen.writers import (
    ClaudeWriter,
    OllamaWriter,
    WriterError,
    WriterUnavailable,
    letters_from,
)

QUESTION = {
    "difficulty": "easy",
    "question": "A cyclist rides 36 km in 3 hours. What is the average speed in km per hour?",
    "options": ["10", "12", "14", "9"],
    "correct_index": 1,
    "explanation": "36 / 3 = 12.",
    "calculation": "36/3",
}


def ollama(handler) -> OllamaWriter:
    client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))
    return OllamaWriter("http://ollama.test", "qwen-test", client=client)


def reply(content: dict | str) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(200, json={"message": {"content": text}})


# ------------------------------------------------------------------------------------- Ollama


def test_ollama_is_asked_for_json_in_the_schema_with_thinking_off():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return reply({"questions": [QUESTION]})

    out = ollama(handler).write(CATEGORIES["numerical"], 1, ["easy"], ["an earlier question"])

    body = seen["body"]
    assert body["model"] == "qwen-test" and body["stream"] is False and body["think"] is False
    assert body["format"] == RawBatch.model_json_schema()
    assert body["options"]["temperature"] > 0  # writing wants variety
    assert "an earlier question" in body["messages"][1]["content"]
    assert "calculation" in body["messages"][0]["content"]  # a numerical category asks for it
    assert out == [RawQuestion(**QUESTION)]


def test_ollama_solves_at_temperature_zero_and_lines_answers_up_by_number():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        # answers out of order, one lower case, one missing
        answers = [{"n": 3, "letter": "c"}, {"n": 1, "working": "x", "letter": "B"}]
        return reply({"answers": answers})

    letters = ollama(handler).solve(
        [("q1", ["a", "b", "c", "d"]), ("q2", ["a", "b", "c", "d"]), ("q3", ["a", "b", "c", "d"])]
    )

    assert seen["body"]["options"]["temperature"] == 0
    assert seen["body"]["format"] == SolvedBatch.model_json_schema()
    assert letters == ["B", None, "C"]
    shown = seen["body"]["messages"][1]["content"]
    assert "Question 1\nq1\nA. a\nB. b\nC. c\nD. d" in shown


def test_ollama_retries_without_the_thinking_switch_when_the_model_rejects_it():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append("think" in body)
        if "think" in body:
            return httpx.Response(400, text='{"error":"model does not support think"}')
        return reply({"questions": [QUESTION]})

    assert len(ollama(handler).write(CATEGORIES["numerical"], 1, ["easy"], [])) == 1
    assert calls == [True, False]


def test_ollama_not_running_is_unavailable_and_a_missing_model_too():
    def refused(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(WriterUnavailable, match="not running"):
        ollama(refused).write(CATEGORIES["verbal"], 1, ["easy"], [])

    def missing(request):
        return httpx.Response(404, text='{"error":"model not found"}')

    with pytest.raises(WriterUnavailable, match="no model"):
        ollama(missing).solve([("q", ["a", "b", "c", "d"])])


@pytest.mark.parametrize(
    ("handler", "match"),
    [
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), "too long"),
        (lambda r: httpx.Response(500, text="boom"), "refused the request"),
        (lambda r: reply("this is not json"), "broke the schema"),
        (lambda r: reply({"questions": [{"question": "no options"}]}), "broke the schema"),
        (lambda r: httpx.Response(200, json={"unexpected": 1}), "not in the expected shape"),
    ],
)
def test_every_other_failure_is_an_ordinary_writer_error(handler, match):
    with pytest.raises(WriterError, match=match) as caught:
        ollama(handler).write(CATEGORIES["verbal"], 1, ["easy"], [])
    assert not isinstance(caught.value, WriterUnavailable)


# ------------------------------------------------------------------------------------- Claude


class FakeMessages:
    def __init__(self, parsed=None, stop_reason="end_turn", error=None):
        self.parsed, self.stop_reason, self.error = parsed, stop_reason, error
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(parsed_output=self.parsed, stop_reason=self.stop_reason)


def claude(messages: FakeMessages) -> ClaudeWriter:
    return ClaudeWriter("claude-test", client=SimpleNamespace(messages=messages))


def test_claude_is_asked_for_the_same_schema_and_returns_the_parsed_questions():
    messages = FakeMessages(RawBatch(questions=[RawQuestion(**QUESTION)]))
    out = claude(messages).write(CATEGORIES["numerical"], 1, ["easy"], [])

    call = messages.calls[0]
    assert call["model"] == "claude-test" and call["output_format"] is RawBatch
    assert "Numerical" in call["messages"][0]["content"]
    assert out[0].question.startswith("A cyclist")


def test_claude_solving_returns_letters():
    messages = FakeMessages(SolvedBatch(answers=[{"n": 1, "letter": "b"}]))
    assert claude(messages).solve([("q", ["a", "b", "c", "d"])]) == ["B"]


def test_a_claude_refusal_an_empty_answer_and_an_api_error_are_writer_errors():
    with pytest.raises(WriterError, match="declined"):
        refused = FakeMessages(None, stop_reason="refusal")
        claude(refused).write(CATEGORIES["verbal"], 1, ["easy"], [])
    with pytest.raises(WriterError, match="no usable answer"):
        claude(FakeMessages(None)).write(CATEGORIES["verbal"], 1, ["easy"], [])
    with pytest.raises(WriterError, match="API call failed"):
        claude(FakeMessages(error=RuntimeError("rate limited"))).solve([("q", list("abcd"))])


# ----------------------------------------------------------------------------------- the rest


def test_letters_outside_the_options_are_not_answers():
    batch = SolvedBatch(answers=[{"n": 1, "letter": "Z"}, {"n": 2, "letter": " d "}])
    assert letters_from(batch, 3) == [None, "D", None]


def plain_settings(**given) -> Settings:
    """Settings from the code's defaults and what a test names. Neither a developer's .env nor their
    environment variables (a real Anthropic key, Claude chosen) can change what these tests see."""
    pinned = {
        "question_provider": "ollama",
        "question_ollama_model": "qwen3:8b",
        "ollama_model": "gemma4:e2b",
        "anthropic_api_key": "",
    }
    return Settings(_env_file=None, **{**pinned, **given})


def test_the_provider_chosen_in_settings_is_the_one_built():
    built = writers.get_writer(plain_settings(question_provider="ollama"))
    assert isinstance(built, OllamaWriter)
    chosen = writers.get_writer(plain_settings(question_ollama_model="m1"))
    assert chosen.model == "m1"
    assert plain_settings(question_provider="claude", claude_model="c1").question_model == "c1"
    assert plain_settings(question_ollama_model="").question_model == plain_settings().ollama_model


def test_availability_names_what_is_wrong(monkeypatch):
    def tags(models):
        def get(url, timeout):
            return httpx.Response(200, json={"models": [{"name": m} for m in models]},
                                  request=httpx.Request("GET", url))

        return get

    settings = plain_settings(question_ollama_model="qwen-test")
    monkeypatch.setattr(writers.httpx, "get", tags(["qwen-test:latest"]))
    assert writers.check_available(settings)[0] is True

    monkeypatch.setattr(writers.httpx, "get", tags(["something-else"]))
    ok, detail = writers.check_available(settings)
    assert ok is False and "ollama pull qwen-test" in detail

    def down(url, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(writers.httpx, "get", down)
    ok, detail = writers.check_available(settings)
    assert ok is False and "not running" in detail

    ok, detail = writers.check_available(
        plain_settings(question_provider="claude", anthropic_api_key="")
    )
    assert ok is False and "ANTHROPIC_API_KEY" in detail
