"""Real calls to Claude: the key, the model and the answer shapes still work together.

Every other test uses a stand-in, so none of them can notice the live service changing (a model
retired, a field renamed, a key that stopped working). This file can. It is SKIPPED unless you ask:

    RUN_LIVE_CLAUDE=1 python -m pytest tests/live -q

It uses the key in .env and spends real money: about 3 cents for the whole file (one numerical
question written and confirmed, one packet assessed). The repository has no spend limit of its own
for tests, so for a hard cap run it with a guard that refuses calls past a dollar amount.
"""

import os
import random

import pytest

from app.clock import SystemClock
from app.config import Settings
from app.services.qgen import pipeline
from app.services.qgen.categories import CATEGORIES
from app.services.qgen.writers import ClaudeWriter
from app.services.ranking.claude import ClaudeRanker
from app.services.ranking.runner import _assess
from tests.support import sample_packet

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_CLAUDE") != "1",
    reason="set RUN_LIVE_CLAUDE=1 to spend a few cents on real Claude calls",
)


@pytest.fixture(scope="module")
def live() -> Settings:
    settings = Settings()  # .env and the environment: the real key, unlike the pinned fixture
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY is not set")
    return settings


def test_the_writer_writes_and_the_checks_confirm_a_numerical_question(live):
    writer = ClaudeWriter(live.claude_model, live.anthropic_api_key, live.question_timeout_s)
    report = pipeline.Report()

    batches = pipeline.produce(
        writer, CATEGORIES["numerical"], ["easy"], [], random.Random(1), report,
        live.question_solves,
    )
    written = [question for batch in batches for question in batch]

    assert len(written) == 1, report.rejected
    question = written[0]
    assert question.category == "numerical" and len(question.options) == 4
    assert 0 <= question.correct_index < 4


def test_the_ranker_answers_a_packet_and_reports_what_the_call_used(live):
    ranker = ClaudeRanker(live.claude_model, live.anthropic_api_key, live.ai_timeout_s)
    packet = sample_packet()

    accepted, attempts, _ = _assess(ranker, packet, SystemClock())

    # The model's wording is not under test and may need its one retry. What must hold is that
    # the call went through, was counted, and either passed the fact check or fell back cleanly.
    assert 1 <= len(attempts) <= 2
    assert all(a["usage"] and a["usage"]["output_tokens"] > 0 for a in attempts if not a["error"])
    assert accepted is None or accepted.assessment.candidate_id == packet["candidate_id"]
