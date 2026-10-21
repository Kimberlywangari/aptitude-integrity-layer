"""Receiving the recording: checksummed, idempotent chunk uploads and the manifest that says
whether anything is missing.

A chunk is the unit of "nothing was lost". The page sends them in order and retries any that fail,
so the server must accept the same chunk twice (a reply was lost on the way back), refuse one that
arrives damaged, and refuse one that contradicts what it already holds.
"""

import hashlib
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.clock import Clock
from app.errors import ApiError
from app.models import TestSession, VideoChunk
from app.services.video import webm
from app.services.video.store import VideoStore, chunk_key


def recording_verified(db: Session, session_id: str) -> bool:
    """True once the server holds a chunk whose container header declares both a video and an
    audio track. This is what lets the test begin when the gate is set to `recording`.

    Any segment's opening chunk counts, not only chunk 0: a first recorder run that came up
    without sound can be replaced by a fresh segment instead of leaving the candidate stuck."""
    return bool(
        db.scalar(
            select(
                exists().where(
                    VideoChunk.session_id == session_id,
                    VideoChunk.has_video.is_(True),
                    VideoChunk.has_audio.is_(True),
                )
            )
        )
    )


def put_chunk(
    db: Session,
    store: VideoStore,
    clock: Clock,
    session: TestSession,
    *,
    seq: int,
    segment: int,
    claimed_sha256: str,
    data: bytes,
    max_bytes: int,
) -> Literal["stored", "duplicate"]:
    if session.video_deleted_at is not None:
        raise ApiError(410, "video_deleted")
    if len(data) > max_bytes:
        raise ApiError(413, "chunk_too_large", max_bytes=max_bytes)
    digest = hashlib.sha256(data).hexdigest()
    if claimed_sha256.strip().lower() != digest:
        raise ApiError(422, "checksum_mismatch")

    existing = db.scalar(
        select(VideoChunk).where(VideoChunk.session_id == session.id, VideoChunk.seq == seq)
    )
    if existing is not None:
        return _same_or_conflict(existing, digest)

    tracks = webm.read_tracks(data)
    key = chunk_key(session.id, segment, seq)
    store.put(key, data)
    inserted = db.execute(
        pg_insert(VideoChunk)
        .values(
            session_id=session.id,
            segment=segment,
            seq=seq,
            bytes=len(data),
            sha256=digest,
            path=key,
            has_video=None if tracks is None else tracks.video > 0,
            has_audio=None if tracks is None else tracks.audio > 0,
            received_at=clock.now(),
        )
        .on_conflict_do_nothing(index_elements=["session_id", "seq"])
        .returning(VideoChunk.id)
    ).first()
    db.commit()
    if inserted is None:
        # two copies of the same chunk raced; the other one won, so compare against it
        winner = db.scalar(
            select(VideoChunk).where(VideoChunk.session_id == session.id, VideoChunk.seq == seq)
        )
        return _same_or_conflict(winner, digest)
    return "stored"


def _same_or_conflict(existing: VideoChunk, digest: str) -> Literal["duplicate"]:
    if existing.sha256 != digest:
        raise ApiError(409, "chunk_conflict")
    return "duplicate"


@dataclass(frozen=True)
class Manifest:
    expected: int | None
    received: int
    missing: int
    bytes: int
    complete: bool


def manifest(db: Session, session: TestSession) -> Manifest:
    """What has arrived against what the page said it made. One aggregate query.

    `expected` is known only once the page has finished and reported its total. Until then,
    `missing` counts the gaps below the highest chunk seen, which is what a stalled upload looks
    like from here.
    """
    expected = session.chunks_total
    in_range = (
        func.count().filter(VideoChunk.seq < expected) if expected is not None else func.count()
    )
    received, total_bytes, highest, within = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(VideoChunk.bytes), 0),
            func.max(VideoChunk.seq),
            in_range,
        ).where(VideoChunk.session_id == session.id)
    ).one()

    if expected is not None:
        missing = max(0, expected - within)
    else:
        missing = 0 if highest is None else max(0, highest + 1 - received)
    complete = expected is not None and missing == 0 and session.status == "finished"
    return Manifest(expected, received, missing, int(total_bytes), complete)
