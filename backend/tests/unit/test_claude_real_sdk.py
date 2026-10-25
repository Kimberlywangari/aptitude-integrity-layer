"""The Claude adapter through the real `anthropic` SDK, with the network replaced by a canned HTTP
server.

test_ranking_adapters.py covers the adapter with a hand-made client, which cannot notice the SDK
changing underneath it (a renamed parameter, a different wire format). This file can. It needs the
optional extra and is skipped without it: pip install -e ".[claude]".

It proves the call shape, not the live service: nothing here shows that a real key is accepted, that
the account can use the model, or what the model writes. That needs one run with a key.
"""

import json

import pytest

anthropic = pytest.importorskip("anthropic")
try:
    import httpx2 as http_lib  # anthropic 1.x
except ImportError:
    import httpx as http_lib  # anthropic 0.x

from app.services.ranking.base import RankerError  # noqa: E402
from app.services.ranking.claude import ClaudeRanker  # noqa: E402
from tests.support import good_assessment, sample_packet  # noqa: E402


class Server:
    """What the pretend API answers, and what it was asked."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.status = 200
        self.body: dict = {}

    def handle(self, request) -> object:
        self.requests.append(
            {
                "path": request.url.path,
                "headers": dict(request.headers),
                "body": json.loads(request.content),
            }
        )
        return http_lib.Response(self.status, json=self.body)


def message(text: str | None, stop_reason: str = "end_turn", output_tokens: int = 321) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": text}] if text else [],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1234, "output_tokens": output_tokens},
    }


@pytest.fixture
def server(monkeypatch) -> Server:
    fake = Server()
    real = anthropic.Anthropic
    monkeypatch.setattr(
        anthropic,
        "Anthropic",
        lambda **kwargs: real(
            http_client=http_lib.Client(transport=http_lib.MockTransport(fake.handle)),
            max_retries=0,
            **kwargs,
        ),
    )
    return fake


@pytest.fixture
def ranker(server) -> ClaudeRanker:
    return ClaudeRanker("claude-sonnet-5-5", api_key="sk-ant-test-not-real", timeout_s=30)


def test_the_request_asks_for_the_schema_through_output_config(server, ranker):
    packet = sample_packet()
    server.body = message(json.dumps(good_assessment(packet)))

    ranker.assess(packet)

    request = server.requests[-1]
    body = request["body"]
    assert request["path"] == "/v1/messages"
    # the key travels as x-api-key (anthropic 1.x) or as a bearer token (2.x)
    assert {"x-api-key", "authorization"} & set(request["headers"])
    assert body["model"] == "claude-sonnet-5-5"
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    # the deprecated spelling must not be what goes on the wire
    assert "output_format" not in body
    # one short judgement per call, never a conversation or a tool
    assert "tools" not in body and len(body["messages"]) == 1


def test_a_good_reply_comes_back_parsed_with_its_token_counts(server, ranker):
    packet = sample_packet()
    server.body = message(json.dumps(good_assessment(packet)))

    result = ranker.assess(packet)

    assert result.assessment.candidate_id == packet["candidate_id"]
    assert result.assessment.strength == 3
    assert result.usage == {"input_tokens": 1234, "output_tokens": 321}


def test_the_schema_sent_carries_no_range_so_the_assessment_itself_must_enforce_it(server, ranker):
    """Structured outputs drops numeric limits from the schema, so `strength` 1 to 5 is only a hint
    to the model. The check that matters is the one after the reply."""
    packet = sample_packet()
    server.body = message(json.dumps(good_assessment(packet, strength=7)))

    with pytest.raises(RankerError, match="schema"):
        ranker.assess(packet)

    sent = json.dumps(server.requests[-1]["body"]["output_config"]["format"]["schema"])
    assert '"maximum"' not in sent and '"minimum"' not in sent


def api_error(kind: str) -> dict:
    return {"type": "error", "error": {"type": kind, "message": "refused"}}


@pytest.mark.parametrize(
    ("status", "body", "says"),
    [
        (401, api_error("authentication_error"), "failed"),
        (400, api_error("invalid_request_error"), "failed"),
        (200, message(None, stop_reason="refusal", output_tokens=0), "declined"),
        (200, message('{"candidate_id": "cand-0', stop_reason="max_tokens"), "schema"),
    ],
    ids=["bad key", "rejected request", "refusal", "cut off"],
)
def test_every_way_the_call_can_fail_is_one_ranker_error(server, ranker, status, body, says):
    server.status, server.body = status, body

    with pytest.raises(RankerError, match=says):
        ranker.assess(sample_packet())
