from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Candidate(Base):
    """An opaque candidate. No names are stored anywhere (assumption A7)."""

    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    invite_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
