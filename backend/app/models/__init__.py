"""Importing this package registers every table on Base.metadata (Alembic relies on it)."""

from app.models.candidate import Candidate
from app.models.evidence import Complaint, Decision, Event, Flag, Heartbeat
from app.models.outbox import EmailOutbox
from app.models.question import Option, Question, QuestionImage, QuestionStats
from app.models.ranking import Packet, Ranking, SittingStat
from app.models.session import SessionQuestion, TestSession
from app.models.sitting import Sitting
from app.models.staff import AuditLog, Reviewer
from app.models.video import AudioSilence, VideoChunk, VideoSegment

__all__ = [
    "AudioSilence",
    "AuditLog",
    "Candidate",
    "Complaint",
    "Decision",
    "EmailOutbox",
    "Event",
    "Flag",
    "Heartbeat",
    "Option",
    "Packet",
    "Question",
    "QuestionImage",
    "QuestionStats",
    "Ranking",
    "Reviewer",
    "SessionQuestion",
    "Sitting",
    "SittingStat",
    "TestSession",
    "VideoChunk",
    "VideoSegment",
]
