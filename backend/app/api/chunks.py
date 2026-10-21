import random

from fastapi import APIRouter, Depends, Path, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.api.deps import get_clock, get_video_store, session_from_any_token
from app.clock import Clock
from app.config import Settings, get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import TestSession
from app.schemas.recording import ChunkResponse, ManifestResponse
from app.services.video import chunks as chunk_service
from app.services.video.store import VideoStore

router = APIRouter(prefix="/chunks", tags=["chunks"])


def _for_path(session: TestSession, session_id: str) -> TestSession:
    # the token must belong to the session named in the path, never to another candidate's
    if session.id != session_id:
        raise ApiError(401, "unauthorized")
    return session


@router.put("/{session_id}/{seq}", response_model=ChunkResponse)
async def put_chunk(
    request: Request,
    session_id: str,
    seq: int = Path(ge=0, le=1_000_000),
    session: TestSession = Depends(session_from_any_token),
    db: Session = Depends(get_db),
    store: VideoStore = Depends(get_video_store),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> ChunkResponse:
    """One chunk of the recording. The body is the raw bytes; `X-Chunk-SHA256` is their SHA-256 and
    `X-Chunk-Segment` says which recorder run made them (0 unless the camera dropped)."""
    _for_path(session, session_id)

    # Dev only (ignored when ENV=production): refuse some uploads on purpose, so the page's retry
    # and resume paths can be exercised without unplugging anything.
    rate = settings.effective_chunk_fail_rate
    if rate > 0 and random.random() < rate:
        raise ApiError(503, "chunk_unavailable")

    claimed = request.headers.get("x-chunk-sha256")
    if not claimed:
        raise ApiError(422, "missing_checksum")
    try:
        segment = int(request.headers.get("x-chunk-segment", "0"))
    except ValueError:
        segment = -1
    if not 0 <= segment <= 1000:
        raise ApiError(422, "bad_segment")

    limit = settings.chunk_max_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, "chunk_too_large", max_bytes=limit)
    body = bytearray()
    async for part in request.stream():
        body += part
        if len(body) > limit:
            raise ApiError(413, "chunk_too_large", max_bytes=limit)

    status = await run_in_threadpool(
        chunk_service.put_chunk,
        db,
        store,
        clock,
        session,
        seq=seq,
        segment=segment,
        claimed_sha256=claimed,
        data=bytes(body),
        max_bytes=limit,
    )
    return ChunkResponse(status=status)


@router.get("/{session_id}/manifest", response_model=ManifestResponse)
def get_manifest(
    session_id: str,
    session: TestSession = Depends(session_from_any_token),
    db: Session = Depends(get_db),
) -> ManifestResponse:
    _for_path(session, session_id)
    result = chunk_service.manifest(db, session)
    return ManifestResponse(
        expected=result.expected,
        received=result.received,
        missing=result.missing,
        bytes=result.bytes,
        complete=result.complete,
    )
