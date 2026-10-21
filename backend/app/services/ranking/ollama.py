"""The local model, through Ollama's chat API with its answer constrained to the Assessment schema.

Every way this can go wrong (Ollama not running, too slow, an HTTP error, an answer that is not
valid JSON or breaks the schema) comes out as one RankerError, so the runner has a single thing to
catch and can fall back to the rule order.
"""

from typing import Any

import httpx
from pydantic import ValidationError

from app.services.ranking import prompts
from app.services.ranking.base import Assessment, RankerError, RankerResult

# temperature 0 and a fixed seed: the same packet gives the same answer, which makes a result
# something to compare rather than something to hope for
OPTIONS = {"temperature": 0, "num_ctx": 4096, "seed": 7}


class OllamaRanker:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 150.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_s)

    def _chat(self, body: dict[str, Any]) -> httpx.Response:
        return self._client.post("/api/chat", json=body)

    def assess(self, packet: dict[str, Any], violations: list[str] | None = None) -> RankerResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": prompts.build_messages(packet, violations),
            "stream": False,
            "format": prompts.schema(),
            "think": False,  # a thinking model would spend the minutes on its own reasoning
            "options": OPTIONS,
            "keep_alive": "10m",
        }
        try:
            response = self._chat(body)
            if response.status_code == 400 and "think" in response.text.lower():
                body.pop("think")  # a model with no thinking mode may reject the switch
                response = self._chat(body)
            response.raise_for_status()
            reply = response.json()
            content = reply["message"]["content"]
        except httpx.TimeoutException as problem:
            raise RankerError("ollama took too long to answer") from problem
        except httpx.HTTPError as problem:
            raise RankerError(
                f"ollama could not be reached or refused the request: {problem}"
            ) from problem
        except (KeyError, TypeError, ValueError) as problem:
            raise RankerError(
                f"ollama's reply was not in the expected shape: {problem}"
            ) from problem

        try:
            assessment = Assessment.model_validate_json(content)
        except ValidationError as problem:
            raise RankerError(
                f"the answer broke the schema: {problem.error_count()} problems",
                content,
                {
                    "input_tokens": int(reply.get("prompt_eval_count") or 0),
                    "output_tokens": int(reply.get("eval_count") or 0),
                },
            ) from problem
        usage = {
            "input_tokens": int(reply.get("prompt_eval_count") or 0),
            "output_tokens": int(reply.get("eval_count") or 0),
        }
        return RankerResult(assessment, content, usage)
