"""The models that write and solve questions: a local one through Ollama, or Claude.

Every way a call can go wrong (not running, too slow, an HTTP error, an answer that is not valid
JSON or breaks the schema, a refusal) comes out as a `WriterError`, so the pipeline has one thing to
catch. `WriterUnavailable` is the kind that will not fix itself in a few seconds (Ollama is not
running, no API key), so the pipeline gives up at once instead of waiting out four timeouts.

Nothing else in the app imports Ollama or Claude for questions: `get_writer` is the one door.
"""

from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.services.qgen import prompts
from app.services.qgen.categories import Category
from app.services.qgen.check import LABELS, OPTION_COUNT
from app.services.qgen.schema import RawBatch, RawQuestion, SolvedBatch

# Writing wants some variety; solving wants the same answer every time.
WRITE_OPTIONS = {"temperature": 0.8, "top_p": 0.95, "num_ctx": 6144, "num_predict": 3500}
SOLVE_OPTIONS = {"temperature": 0, "num_ctx": 6144, "num_predict": 2500, "seed": 7}

CLAUDE_MAX_TOKENS = 12000


class WriterError(Exception):
    """The model could not give a usable answer this time."""


class WriterUnavailable(WriterError):
    """The model cannot be reached at all, or is not set up. Retrying will not help."""


class QuestionWriter(Protocol):
    name: str
    model: str

    def write(
        self, category: Category, count: int, difficulties: list[str], avoid: list[str]
    ) -> list[RawQuestion]:
        """Up to `count` new questions. Raises WriterError when nothing usable comes back."""
        ...

    def solve(self, items: list[tuple[str, list[str]]]) -> list[str | None]:
        """The letter chosen for each (question, options), None where the model gave none."""
        ...


def _schema_problem(problem: ValidationError) -> str:
    return f"the answer broke the schema ({problem.error_count()} problems)"


def letters_from(batch: SolvedBatch, count: int) -> list[str | None]:
    """Line the solver's answers up with the questions it was shown, by their numbers."""
    by_number = {a.n: a.letter.strip().upper()[:1] for a in batch.answers}
    allowed = LABELS[:OPTION_COUNT]
    out: list[str | None] = []
    for number in range(1, count + 1):
        letter = by_number.get(number)
        out.append(letter if letter and letter in allowed else None)
    return out


# ------------------------------------------------------------------------------------- Ollama


class OllamaWriter:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 300.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_s)

    def _chat(self, messages: list[dict[str, str]], schema: dict[str, Any], options: dict) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": schema,
            "think": False,  # a thinking model would spend the minutes on its own reasoning
            "options": options,
            "keep_alive": "20m",
        }
        try:
            response = self._client.post("/api/chat", json=body)
            if response.status_code == 400 and "think" in response.text.lower():
                body.pop("think")  # a model with no thinking mode may reject the switch
                response = self._client.post("/api/chat", json=body)
            response.raise_for_status()
            return response.json()["message"]["content"]
        except httpx.ConnectError as problem:
            raise WriterUnavailable("ollama is not running or cannot be reached") from problem
        except httpx.TimeoutException as problem:
            raise WriterError("ollama took too long to answer") from problem
        except httpx.HTTPStatusError as problem:
            detail = problem.response.text[:160]
            if problem.response.status_code == 404:
                message = f"ollama has no model {self.model!r}: {detail}"
                raise WriterUnavailable(message) from problem
            raise WriterError(f"ollama refused the request: {detail}") from problem
        except httpx.HTTPError as problem:
            raise WriterError(f"ollama could not be reached: {problem}") from problem
        except (KeyError, TypeError, ValueError) as problem:
            message = f"ollama's reply was not in the expected shape: {problem}"
            raise WriterError(message) from problem

    def write(
        self, category: Category, count: int, difficulties: list[str], avoid: list[str]
    ) -> list[RawQuestion]:
        content = self._chat(
            prompts.write_messages(category, count, difficulties, avoid),
            prompts.write_schema(),
            WRITE_OPTIONS,
        )
        try:
            return RawBatch.model_validate_json(content).questions
        except ValidationError as problem:
            raise WriterError(_schema_problem(problem)) from problem

    def solve(self, items: list[tuple[str, list[str]]]) -> list[str | None]:
        content = self._chat(prompts.solve_messages(items), prompts.solve_schema(), SOLVE_OPTIONS)
        try:
            return letters_from(SolvedBatch.model_validate_json(content), len(items))
        except ValidationError as problem:
            raise WriterError(_schema_problem(problem)) from problem


# ------------------------------------------------------------------------------------- Claude


class ClaudeWriter:
    """Same prompts and schemas as Ollama, through the Claude API. Not run live yet (it needs a
    paid key), so it is covered by tests with a stand-in client; treat it as untested live until a
    real key has been through it."""

    name = "claude"

    def __init__(
        self, model: str, api_key: str = "", timeout_s: float = 300.0, client: Any = None
    ) -> None:
        self.model = model
        if client is not None:  # a stand-in for tests
            self._client = client
            self._api_errors: tuple[type[BaseException], ...] = (Exception,)
            return
        try:
            import anthropic
        except ImportError as problem:
            raise WriterUnavailable(
                'the anthropic package is not installed: pip install -e ".[claude]"'
            ) from problem
        # an empty key falls back to the environment (ANTHROPIC_API_KEY)
        self._client = anthropic.Anthropic(api_key=api_key or None, timeout=timeout_s)
        self._api_errors = (anthropic.APIError,)

    def _parse(self, messages: list[dict[str, str]], schema_type: type) -> Any:
        system, user = messages[0]["content"], messages[1]["content"]
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=CLAUDE_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema_type,
                output_config={"effort": "medium"},
            )
        except self._api_errors as problem:
            raise WriterError(f"the Claude API call failed: {problem}") from problem
        except ValidationError as problem:
            raise WriterError(_schema_problem(problem)) from problem
        if response.stop_reason == "refusal":
            raise WriterError("Claude declined to write this")
        parsed = getattr(response, "parsed_output", None)
        if not isinstance(parsed, schema_type):
            raise WriterError(f"no usable answer (stop reason {response.stop_reason})")
        return parsed

    def write(
        self, category: Category, count: int, difficulties: list[str], avoid: list[str]
    ) -> list[RawQuestion]:
        batch = self._parse(prompts.write_messages(category, count, difficulties, avoid), RawBatch)
        return batch.questions

    def solve(self, items: list[tuple[str, list[str]]]) -> list[str | None]:
        batch = self._parse(prompts.solve_messages(items), SolvedBatch)
        return letters_from(batch, len(items))


# --------------------------------------------------------------------------------- the one door


def get_writer(settings: Settings) -> QuestionWriter:
    timeout = settings.question_timeout_s
    if settings.question_provider == "claude":
        return ClaudeWriter(settings.claude_model, settings.anthropic_api_key, timeout)
    return OllamaWriter(settings.ollama_base_url, settings.question_model, timeout)


def check_available(settings: Settings) -> tuple[bool, str]:
    """Whether the configured writer looks usable, and a sentence a person can act on. Cheap: it
    asks Ollama what models it has, or looks for a key, and writes nothing."""
    if settings.question_provider == "claude":
        if not settings.anthropic_api_key:
            return False, "Claude is chosen but ANTHROPIC_API_KEY is empty."
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, 'The anthropic package is not installed (pip install -e ".[claude]").'
        return True, f"Claude ({settings.claude_model}); not yet tested live."
    model = settings.question_model
    try:
        reply = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=4.0)
        reply.raise_for_status()
        names = {m.get("name") for m in reply.json().get("models", [])}
    except (httpx.HTTPError, ValueError):
        return False, f"Ollama is not running at {settings.ollama_base_url}."
    if model not in names and f"{model}:latest" not in names:
        return False, f"Ollama has no model called {model}. Run: ollama pull {model}"
    return True, f"Ollama ({model})."
