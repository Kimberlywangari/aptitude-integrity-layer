"""Which stored questions a sitting may draw from, by its mode.

`cytonn`: Cytonn's own questions. `practice`: the made-up bank, for trying things out. `bank`: any
stored question, which is what every sitting did before there were modes. `ai` draws nothing from
the database: its questions are written for each candidate.
"""

from sqlalchemy import ColumnElement

from app.models import Question

STORED_MODES = ("bank", "practice", "cytonn")
MODES = (*STORED_MODES, "ai")


def stored_questions(mode: str) -> ColumnElement[bool]:
    """The condition on `questions` that picks out what a sitting in this mode may draw."""
    if mode == "cytonn":
        return Question.source == "cytonn"
    if mode == "practice":
        return Question.source == "synthetic"
    return Question.source != "ai"
