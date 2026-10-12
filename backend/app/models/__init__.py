"""Importing this package registers every table on Base.metadata (Alembic relies on it)."""

from app.models.candidate import Candidate
from app.models.sitting import Sitting

__all__ = ["Candidate", "Sitting"]
