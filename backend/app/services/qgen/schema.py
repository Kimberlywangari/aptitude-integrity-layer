"""The shapes a writer must answer in, and the question as it leaves the checks.

The models are what Ollama's `format` and Claude's structured output are asked to follow. They are
kept loose enough for a small model to satisfy (no length bounds in the schema itself) because the
real limits are enforced afterwards in check.py, where a failure can be counted and retried.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field


class RawQuestion(BaseModel):
    """One question as a writer produces it.

    The order of the fields matters: a model fills them in this order, so the working comes before
    the options. A model that writes the options first commits to an answer it has not worked out,
    and its working then disagrees with it.
    """

    model_config = ConfigDict(extra="ignore")

    difficulty: str
    question: str
    # Numerical questions only: one arithmetic expression that equals the correct option.
    calculation: str = ""
    explanation: str = ""  # a short working, for reviewers; never shown to a candidate
    options: list[str]
    correct_index: int  # 0-based position in `options` of the one right answer


class RawBatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    questions: list[RawQuestion]


class SolvedQuestion(BaseModel):
    """A solver's pick for one question it was shown without the answer."""

    model_config = ConfigDict(extra="ignore")

    n: int = Field(description="the question's number, as it was shown")
    working: str = ""
    letter: str


class SolvedBatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answers: list[SolvedQuestion]


@dataclass(frozen=True)
class Written:
    """A question that passed every check, with its options in the order they will be stored (the
    correct one is wherever the server's shuffle put it)."""

    category: str
    difficulty: str
    text: str
    options: tuple[str, ...]
    correct_index: int
    explanation: str
