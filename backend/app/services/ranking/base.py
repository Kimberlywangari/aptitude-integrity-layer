"""What every ranker must produce, and how one is chosen.

The AI ranks and explains. It never decides anything about a candidate, never sets a threshold and
never removes anyone from the queue. This module is the only place that knows which providers
exist: nothing else in the app imports Ollama or Claude directly.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from app.config import Settings

MAX_EXPLANATION_WORDS = 80


class RankerError(Exception):
    """The provider could not give a usable answer: unreachable, too slow, or not valid JSON.
    `raw` carries whatever it did say, kept for the audit trail."""

    def __init__(
        self, message: str, raw: str | None = None, usage: dict[str, int] | None = None
    ) -> None:
        super().__init__(message)
        self.raw = raw
        # tokens the provider reports it used, when it got far enough to say: a refused or
        # unusable answer is still billed
        self.usage = usage


class InnocentExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: bool
    evidence_ids: list[str]


class Cited(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flag_ids: list[str]
    question_numbers: list[StrictInt]
    times_s: list[StrictInt]
    counts: dict[str, StrictInt]


class Assessment(BaseModel):
    """One candidate's assessment, validated strictly: a wrong shape is a failed attempt, not
    something to be patched up."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    flags_support_each_other: Literal["yes", "partly", "no"]
    innocent_explanation: InnocentExplanation
    strength: int = Field(ge=1, le=5, strict=True)
    explanation: str
    cited: Cited

    @field_validator("explanation")
    @classmethod
    def _short_enough(cls, value: str) -> str:
        if len(value.split()) > MAX_EXPLANATION_WORDS:
            raise ValueError(f"explanation is longer than {MAX_EXPLANATION_WORDS} words")
        return value


@dataclass(frozen=True)
class RankerResult:
    assessment: Assessment
    raw: str  # exactly what the provider returned, for the audit trail
    # {"input_tokens": n, "output_tokens": n} as the provider's own response reported them. This
    # is what spend is worked out from, so it is the provider's count, never our estimate.
    usage: dict[str, int] | None = None


class Ranker(Protocol):
    name: str
    model: str

    def assess(self, packet: dict[str, Any], violations: list[str] | None = None) -> RankerResult:
        """Assess one packet. On a retry, `violations` lists what the first answer got wrong so
        the provider can correct it. Raises RankerError when no usable answer comes back."""
        ...


def get_ranker(settings: Settings) -> Ranker | None:
    """The configured provider, or None for `rules`: no AI step, the rule order stands."""
    provider = settings.ai_provider
    if provider == "rules":
        return None
    if provider == "ollama":
        from app.services.ranking.ollama import OllamaRanker

        return OllamaRanker(settings.ollama_base_url, settings.ollama_model, settings.ai_timeout_s)
    if provider == "claude":
        from app.services.ranking.claude import ClaudeRanker

        return ClaudeRanker(
            settings.claude_model, settings.anthropic_api_key, settings.ai_timeout_s
        )
    raise ValueError(f"unknown AI_PROVIDER {provider!r}")
