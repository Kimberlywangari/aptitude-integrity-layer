"""The recording: chunks as they arrive, the segments they assemble into, and the server's scan of
the saved audio. Nothing here holds the video itself (that is on disk behind the VideoStore); only
what is needed to find it, check it and show a reviewer where a moment sits in it."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class VideoChunk(Base):
    """One piece of the recording, about ten seconds long.

    `seq` counts up through the whole session (0, 1, 2 ...) and does not restart when the camera
    drops and a new segment begins, so "nothing missing" is one simple check: every number from 0
    to the total is present. `segment` says which recorder run produced it; each run starts with
    its own container header, so segments are assembled separately.
    """

    __tablename__ = "video_chunks"
    __table_args__ = (UniqueConstraint("session_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    segment: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    seq: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String(300))  # relative to the video root
    # Read from the container header when a chunk carries one (the first chunk of a segment), so
    # the start of the test can require a real video and a real audio track without a second pass.
    has_video: Mapped[bool | None] = mapped_column(Boolean)
    has_audio: Mapped[bool | None] = mapped_column(Boolean)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VideoSegment(Base):
    """One recorder run, assembled into a file that seeks. The row stays after the video is
    purged, so the record still says what existed; only `path` is cleared."""

    __tablename__ = "video_segments"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    segment: Mapped[int] = mapped_column(Integer, primary_key=True)
    # server time of the recording_started event: video offset = flag server_ts - started_at
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[float] = mapped_column(Float)
    chunk_count: Mapped[int] = mapped_column(Integer)  # chunks this file was built from
    bytes: Mapped[int] = mapped_column(BigInteger)
    path: Mapped[str | None] = mapped_column(String(300))  # relative to the video root
    assembled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AudioSilence(Base):
    """A silent stretch the server found in the saved audio (layer 3 of master plan 7.8).
    Context for a reviewer, never a flag."""

    __tablename__ = "audio_silences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    segment: Mapped[int] = mapped_column(Integer)
    start_s: Mapped[float] = mapped_column(Float)  # seconds into the segment
    end_s: Mapped[float] = mapped_column(Float)
    start_server_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_server_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
