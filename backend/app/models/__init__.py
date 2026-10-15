"""Importing this package registers every table on Base.metadata (Alembic relies on it)."""

from app.models.candidate import Candidate
from app.models.evidence import Complaint, Decision, Event, Flag, Heartbeat
from app.models.question import Option, Question, QuestionStats
from app.models.session import SessionQuestion, TestSession
from app.models.sitting import Sitting
from app.models.staff import AuditLog, Reviewer

__all__ = [
    "AuditLog",
    "Candidate",
    "Complaint",
    "Decision",
    "Event",
    "Flag",
    "Heartbeat",
    "Option",
    "Question",
    "QuestionStats",
    "Reviewer",
    "SessionQuestion",
    "Sitting",
    "TestSession",
]
