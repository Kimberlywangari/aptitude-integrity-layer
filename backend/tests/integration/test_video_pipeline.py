"""The recording, from a candidate's upload to a file a reviewer can scrub and an audio scan.

Needs a real ffmpeg (on PATH, or FFMPEG_BIN pointing at it); skipped without one. The recording
is made by ffmpeg itself and written to a pipe, as a browser recorder does: no duration, no seek
index. It is then cut into arbitrary chunks, uploaded through the real endpoints and joined again.
"""

import os
import shutil
import subprocess
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AudioSilence, VideoSegment
from app.services.audio.silence import detect_silence
from app.services.video import ffmpeg
from app.services.video.assemble import ensure_assembled
from app.services.video.store import LocalVideoStore
from app.services.video.webm import Tracks, read_tracks
from tests.support import Live

FFMPEG = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")

SECONDS = 24
SILENT = (8, 20)  # the microphone goes quiet for twelve seconds in the middle


@pytest.fixture(scope="module")
def recording() -> bytes:
    """24 s of 320x240 video and a tone that is switched off from 8 s to 20 s."""
    command = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=15:duration={SECONDS}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={SECONDS}",
        "-af", f"volume=enable='between(t,{SILENT[0]},{SILENT[1]})':volume=0",
        "-c:v", "libvpx", "-b:v", "150k", "-c:a", "libopus", "-b:a", "24k",
        "-f", "webm", "pipe:1",
    ]  # fmt: skip
    return subprocess.run(command, capture_output=True, check=True).stdout


def cut(data: bytes, size: int = 9000) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


@pytest.fixture
def uploaded(client, db, seeded, clock, recording):
    live = Live(client, db, seeded.invites[0].token).start()
    assert live.begin().status_code == 200
    chunks = cut(recording)
    clock.advance(30)
    live.events({"client_seq": 1, "type": "recording_started", "payload": {"segment": 0}})
    for seq, data in enumerate(chunks):
        assert live.put_chunk(seq, data).status_code == 200
    live.answer_everything(clock)
    live.finish(chunks_total=len(chunks))
    live.chunks = chunks
    live.start_ts = live.session().recording_started_at
    return live


def test_a_real_recorders_first_chunk_declares_video_and_audio(recording):
    assert read_tracks(cut(recording)[0]) == Tracks(video=1, audio=1)
    assert read_tracks(cut(recording)[1]) is None  # later chunks carry no header


def test_the_manifest_is_complete_after_every_chunk_arrived(uploaded):
    body = uploaded.manifest().json()
    assert body["expected"] == len(uploaded.chunks)
    assert (body["missing"], body["complete"]) == (0, True)


def test_chunks_join_into_one_seekable_file_of_the_right_length(uploaded, db, clock, settings):
    store = LocalVideoStore(settings.video_root_path)
    result = ensure_assembled(db, store, clock, settings, uploaded.session_id)

    assert result.failed == {}
    (segment,) = result.segments
    assert segment.segment == 0 and segment.chunk_count == len(uploaded.chunks)
    assert segment.duration_s == pytest.approx(SECONDS, abs=1.5)
    assert segment.started_at == uploaded.start_ts  # the recording_started event is the anchor
    assert store.exists(segment.path)
    # the rewritten file now carries a duration of its own, which the raw stream never had
    assert ffmpeg.parse_duration(
        ffmpeg.run(["-i", str(store.local_path(segment.path))], check=False)
    )


def test_assembling_twice_does_not_rebuild_an_unchanged_segment(uploaded, db, clock, settings):
    store = LocalVideoStore(settings.video_root_path)
    first = ensure_assembled(db, store, clock, settings, uploaded.session_id).segments[0]
    stamp = first.assembled_at
    clock.advance(60)

    again = ensure_assembled(db, store, clock, settings, uploaded.session_id).segments[0]

    assert again.assembled_at == stamp
    assert db.scalars(select(VideoSegment)).all().__len__() == 1


def test_a_late_chunk_makes_the_segment_rebuild(uploaded, db, clock, settings):
    store = LocalVideoStore(settings.video_root_path)
    first = ensure_assembled(db, store, clock, settings, uploaded.session_id).segments[0]
    count, stamp = first.chunk_count, first.assembled_at
    clock.advance(60)
    # a stray extra chunk at the end (a duplicate of the last bytes, new sequence number)
    uploaded.put_chunk(len(uploaded.chunks), uploaded.chunks[-1][:200])

    again = ensure_assembled(db, store, clock, settings, uploaded.session_id).segments[0]

    assert again.chunk_count == count + 1
    assert again.assembled_at > stamp


def test_a_segment_ffmpeg_cannot_read_is_reported_not_raised(client, db, seeded, clock, settings):
    live = Live(client, db, seeded.invites[1].token).start()
    live.put_chunk(0, b"this is not video at all")
    store = LocalVideoStore(settings.video_root_path)

    result = ensure_assembled(db, store, clock, settings, live.session_id)

    assert result.segments == [] and 0 in result.failed
    assert not store.exists(f"{live.session_id}/assembled/seg0.webm")


def test_the_audio_scan_finds_the_quiet_stretch_and_places_it_in_server_time(
    uploaded, db, clock, settings
):
    settings.mic_server_min_silence_s = 5
    settings.mic_silence_db = -50
    store = LocalVideoStore(settings.video_root_path)

    found = detect_silence(db, store, clock, settings, uploaded.session_id)

    assert found == 1
    (row,) = db.scalars(select(AudioSilence))
    assert row.start_s == pytest.approx(SILENT[0], abs=1.5)
    assert row.end_s == pytest.approx(SILENT[1], abs=1.5)
    assert row.start_server_ts == uploaded.start_ts + timedelta(seconds=row.start_s)
    assert row.end_server_ts == uploaded.start_ts + timedelta(seconds=row.end_s)


def test_running_the_scan_again_leaves_the_same_rows(uploaded, db, clock, settings):
    settings.mic_server_min_silence_s = 5
    settings.mic_silence_db = -50
    store = LocalVideoStore(settings.video_root_path)

    detect_silence(db, store, clock, settings, uploaded.session_id)
    first = [(r.start_s, r.end_s) for r in db.scalars(select(AudioSilence))]
    detect_silence(db, store, clock, settings, uploaded.session_id)

    assert [(r.start_s, r.end_s) for r in db.scalars(select(AudioSilence))] == first


def test_a_quiet_stretch_shorter_than_the_minimum_is_not_reported(uploaded, db, clock, settings):
    settings.mic_server_min_silence_s = (
        60  # the real default: a twelve second pause is just a pause
    )
    settings.mic_silence_db = -50
    store = LocalVideoStore(settings.video_root_path)
    assert detect_silence(db, store, clock, settings, uploaded.session_id) == 0
