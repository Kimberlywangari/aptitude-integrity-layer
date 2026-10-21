"""Joining a session's chunks back into video a reviewer can scrub.

A browser recorder's chunks are slices of one long stream: only the first carries the container
header and none of them knows the total length. So each segment's chunks are joined in order and
then rewritten once without re-encoding (`remux`), which gives the file a duration and a seek
index. Each segment is a separate file because a recorder restart (a camera drop) begins a new
stream with its own header; the gap between two segments is simply "no video at this moment".
"""

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.models import Event, VideoChunk, VideoSegment
from app.services.video import ffmpeg
from app.services.video.store import VideoStore, assembled_key


@dataclass
class Assembly:
    segments: list[VideoSegment] = field(default_factory=list)
    failed: dict[int, str] = field(default_factory=dict)  # segment -> why ffmpeg refused it


def segment_starts(db: Session, session_id: str) -> dict[int, datetime]:
    """When each recorder run began, by the server's clock: the `recording_started` events."""
    starts: dict[int, datetime] = {}
    rows = db.execute(
        select(Event.server_ts, Event.payload).where(
            Event.session_id == session_id, Event.type == "recording_started"
        )
    )
    for server_ts, payload in rows:
        segment = int((payload or {}).get("segment", 0))
        if segment not in starts or server_ts < starts[segment]:
            starts[segment] = server_ts
    return starts


def _is_current(existing: VideoSegment | None, count: int, store: VideoStore) -> bool:
    return (
        existing is not None
        and existing.chunk_count == count
        and existing.path is not None
        and store.exists(existing.path)
    )


def ensure_assembled(
    db: Session, store: VideoStore, clock: Clock, settings: Settings, session_id: str
) -> Assembly:
    """Build (or reuse) one playable file per segment. Does nothing for a segment whose chunks
    have not changed since it was last built. Needs ffmpeg; raises `FfmpegMissing` without it."""
    by_segment: dict[int, list[VideoChunk]] = {}
    for chunk in db.scalars(
        select(VideoChunk)
        .where(VideoChunk.session_id == session_id, VideoChunk.deleted_at.is_(None))
        .order_by(VideoChunk.segment, VideoChunk.seq)
    ):
        by_segment.setdefault(chunk.segment, []).append(chunk)

    starts = segment_starts(db, session_id)
    result = Assembly()
    for segment, chunks in sorted(by_segment.items()):
        existing = db.get(VideoSegment, (session_id, segment))
        if _is_current(existing, len(chunks), store):
            result.segments.append(existing)
            continue

        raw_key = f"{session_id}/assembled/seg{segment}.raw.webm"
        final_key = assembled_key(session_id, segment)
        raw_path = store.local_path(raw_key)
        final_path = store.local_path(final_key)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with raw_path.open("wb") as joined:
                for chunk in chunks:
                    with store.local_path(chunk.path).open("rb") as part:
                        shutil.copyfileobj(part, joined)
            ffmpeg.remux(raw_path, final_path)
            duration = ffmpeg.probe_duration(final_path)
        except ffmpeg.FfmpegFailed as problem:
            result.failed[segment] = str(problem)
            final_path.unlink(missing_ok=True)
            continue
        finally:
            raw_path.unlink(missing_ok=True)

        # no recording_started event arrived (it can be lost with the page): the first chunk lands
        # about one chunk length after the recorder began, which is close enough to show something
        started = starts.get(segment) or (
            chunks[0].received_at - timedelta(seconds=settings.chunk_seconds)
        )
        values = {
            "session_id": session_id,
            "segment": segment,
            "started_at": started,
            "duration_s": duration,
            "chunk_count": len(chunks),
            "bytes": final_path.stat().st_size,
            "path": final_key,
            "assembled_at": clock.now(),
        }
        db.execute(
            pg_insert(VideoSegment)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["session_id", "segment"],
                set_={k: v for k, v in values.items() if k not in ("session_id", "segment")},
            )
        )
        db.commit()
        # the upsert bypassed the session's cache, so read the row back rather than reuse it
        result.segments.append(
            db.get(VideoSegment, (session_id, segment), populate_existing=True)
        )
    return result


def known_segments(db: Session, session_id: str) -> list[VideoSegment]:
    """The segments already assembled, without touching ffmpeg."""
    return list(
        db.scalars(
            select(VideoSegment)
            .where(VideoSegment.session_id == session_id)
            .order_by(VideoSegment.segment)
        )
    )
