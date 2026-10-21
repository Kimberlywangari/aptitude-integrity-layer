"""Layer 3 of the muted-microphone checks (master plan 7.8): the server listens to the saved audio
for long quiet stretches. A page cannot stop a candidate muting the microphone, so this is what
lets a reviewer see it from the recording itself. It adds context for a person; it never raises a
flag or changes a score.
"""

import re
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.models import AudioSilence
from app.services.video import ffmpeg
from app.services.video.assemble import ensure_assembled
from app.services.video.store import VideoStore

START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


def parse_silencedetect(log: str, total_s: float | None = None) -> list[tuple[float, float]]:
    """(start, end) seconds for each quiet stretch in ffmpeg's `silencedetect` log.

    A stretch still open when the file ends has a start and no end; it runs to `total_s` if that
    is known and is dropped otherwise. ffmpeg can report a start a hair below zero.
    """
    stretches: list[tuple[float, float]] = []
    open_start: float | None = None
    for line in log.splitlines():
        started = START.search(line)
        if started:
            open_start = max(0.0, float(started.group(1)))
            continue
        ended = END.search(line)
        if ended and open_start is not None:
            stretches.append((open_start, max(open_start, float(ended.group(1)))))
            open_start = None
    if open_start is not None and total_s is not None and total_s > open_start:
        stretches.append((open_start, total_s))
    return stretches


def detect_silence(
    db: Session, store: VideoStore, clock: Clock, settings: Settings, session_id: str
) -> int:
    """Scan every segment of a session and store its quiet stretches. Running it again replaces
    the earlier rows, so the result is the same however often it runs. Returns the stretches
    found."""
    assembly = ensure_assembled(db, store, clock, settings, session_id)
    db.execute(delete(AudioSilence).where(AudioSilence.session_id == session_id))

    found = 0
    for segment in assembly.segments:
        if segment.path is None or segment.started_at is None:
            continue
        log = ffmpeg.silencedetect(
            store.local_path(segment.path),
            settings.mic_silence_db,
            settings.mic_server_min_silence_s,
        )
        for start_s, end_s in parse_silencedetect(log, segment.duration_s):
            db.add(
                AudioSilence(
                    session_id=session_id,
                    segment=segment.segment,
                    start_s=start_s,
                    end_s=end_s,
                    start_server_ts=segment.started_at + timedelta(seconds=start_s),
                    end_server_ts=segment.started_at + timedelta(seconds=end_s),
                )
            )
            found += 1
    db.commit()
    return found
