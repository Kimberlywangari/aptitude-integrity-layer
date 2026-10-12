"""Importing this package registers every table on Base.metadata (Alembic relies on it)."""

from app.models.candidate import Candidate
from app.models.question import Option, Question, QuestionStats
from app.models.sitting import Sitting

__all__ = ["Candidate", "Option", "Question", "QuestionStats", "Sitting"]
