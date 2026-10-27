"""The Claude API behind the same Ranker interface as the local model.

Same prompt, same Assessment schema, same fact check and same runner: only the call differs. Run
live on 27 Oct 2026 on three of the made-up benchmark packets: every first answer failed the fact
check (an id or a number not in the packet) and every retry passed, about 1.7 cents a packet. The
tests use a stand-in client, so they never spend money.

The SDK is an optional extra (`pip install -e ".[claude]"`) and is imported only here, when this
provider is chosen. Every failure comes out as one RankerError, so a refusal, a rate limit or a
network error simply sends that candidate down the rule-order fallback.
"""

from typing import Any

from pydantic import ValidationError

from app.services.ranking import prompts
from app.services.ranking.base import Assessment, RankerError, RankerResult

# The most a single call may write, thinking included. It is a hard limit the API enforces, so it
# is also the ceiling on what one call can cost (see docs/plan/claude-api-cost-estimate.md).
MAX_OUTPUT_TOKENS = 16000


def usage_of(response: Any) -> dict[str, int] | None:
    """The token counts a response reports, or None if it reports none."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }


class ClaudeRanker:
    name = "claude"

    def __init__(
        self,
        model: str,
        api_key: str = "",
        timeout_s: float = 150.0,
        client: Any = None,
    ) -> None:
        self.model = model
        if client is not None:  # a stand-in for tests
            self._client = client
            self._api_errors: tuple[type[BaseException], ...] = (Exception,)
            return
        try:
            import anthropic
        except ImportError as problem:
            raise RankerError(
                'the anthropic package is not installed: pip install -e ".[claude]"'
            ) from problem
        # an empty key falls back to the environment (ANTHROPIC_API_KEY or `ant auth login`)
        self._client = anthropic.Anthropic(api_key=api_key or None, timeout=timeout_s)
        self._api_errors = (anthropic.APIError,)

    def assess(self, packet: dict[str, Any], violations: list[str] | None = None) -> RankerResult:
        messages = prompts.build_messages(packet, violations)
        system, user = messages[0]["content"], messages[1]["content"]
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,  # thinking counts toward this; the answer is short
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=Assessment,
                # a short structured judgement, checked by the fact check afterwards: the low
                # setting keeps the spend and the wait down
                output_config={"effort": "low"},
            )
        except self._api_errors as problem:
            raise RankerError(f"the Claude API call failed: {problem}") from problem
        except TypeError as problem:
            # With no key anywhere (settings empty, no ANTHROPIC_API_KEY, no login) the SDK raises
            # this before it sends anything. That is a setup problem: fall back like any failure,
            # as the docs promise, instead of crashing the whole ranking run. Any other TypeError
            # is a bug and still shows.
            if "authentication method" not in str(problem):
                raise
            raise RankerError("no Anthropic key: set ANTHROPIC_API_KEY in .env") from problem
        except ValidationError as problem:
            raise RankerError(
                f"the answer broke the schema: {problem.error_count()} problems"
            ) from problem

        raw = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        usage = usage_of(response)
        if response.stop_reason == "refusal":
            raise RankerError("Claude declined to assess this packet", raw or None, usage)
        assessment = getattr(response, "parsed_output", None)
        if not isinstance(assessment, Assessment):
            raise RankerError(
                f"no usable answer (stop reason {response.stop_reason})", raw or None, usage
            )
        return RankerResult(assessment, raw or assessment.model_dump_json(), usage)
