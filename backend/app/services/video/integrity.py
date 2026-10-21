"""Checking that nothing was lost: every chunk the page said it made is on the server and its bytes
still match the checksum recorded when it arrived. This is the "no video chunks lost after upload"
criterion as code."""

import hashlib
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TestSession, VideoChunk
from app.services.video.store import VideoStore

BLOCK = 1024 * 1024


@dataclass
class Integrity:
    session_id: str
    expected: int | None  # what the page reported, or None if it never did
    received: int
    missing: list[int] = field(default_factory=list)  # numbers that never arrived
    mismatched: list[int] = field(default_factory=list)  # on disk, but the bytes have changed
    unreadable: list[int] = field(default_factory=list)  # a row with no file behind it

    @property
    def ok(self) -> bool:
        return not (self.missing or self.mismatched or self.unreadable)


def _sha256_of(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(BLOCK):
            digest.update(block)
    return digest.hexdigest()


def verify_session(db: Session, store: VideoStore, session: TestSession) -> Integrity:
    """Compare what arrived with what was expected, and re-hash every stored file. A chunk that
    was purged on purpose (its row is marked deleted) counts as received and is not re-read."""
    chunks = list(
        db.scalars(
            select(VideoChunk).where(VideoChunk.session_id == session.id).order_by(VideoChunk.seq)
        )
    )
    present = {c.seq for c in chunks}
    horizon = session.chunks_total
    if horizon is None:  # the page never said: judge what arrived by the highest number seen
        horizon = max(present, default=-1) + 1
    result = Integrity(session.id, session.chunks_total, len(chunks))
    result.missing = [n for n in range(horizon) if n not in present]
    for chunk in chunks:
        if chunk.deleted_at is not None:
            continue
        if not store.exists(chunk.path):
            result.unreadable.append(chunk.seq)
        elif _sha256_of(store.local_path(chunk.path)) != chunk.sha256:
            result.mismatched.append(chunk.seq)
    return result
