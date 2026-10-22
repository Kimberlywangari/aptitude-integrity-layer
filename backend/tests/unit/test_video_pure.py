"""The parts of the video code that are plain arithmetic and text: seek maths, ffmpeg log parsing
and the local store."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.audio.silence import parse_silencedetect
from app.services.video.ffmpeg import parse_duration, parse_last_progress
from app.services.video.seek import SegmentSpan, seek_for
from app.services.video.store import LocalVideoStore, assembled_key, chunk_key

T0 = datetime(2026, 10, 20, 9, 0, 0, tzinfo=UTC)


def at(seconds):
    return T0 + timedelta(seconds=seconds)


# ------------------------------------------------------------------------------------ seeking


def spans():
    # segment 0: 0 to 100 s; the camera dropped; segment 1: 130 to 200 s (a gap of 30 s)
    return [SegmentSpan(0, at(0), 100.0), SegmentSpan(1, at(130), 70.0)]


def test_a_flag_inside_the_first_segment_seeks_five_seconds_early():
    seek = seek_for(spans(), at(42))
    assert (seek.segment, seek.seek_s) == (0, 37.0)


def test_a_flag_inside_a_later_segment_is_measured_from_that_segments_start():
    seek = seek_for(spans(), at(150))
    assert (seek.segment, seek.seek_s) == (1, 15.0)


def test_a_flag_in_the_first_seconds_never_seeks_below_zero():
    assert seek_for(spans(), at(3)).seek_s == 0.0
    assert seek_for(spans(), at(0)).seek_s == 0.0


def test_a_flag_in_the_gap_has_no_video():
    assert seek_for(spans(), at(115)) is None


def test_a_flag_before_the_recording_or_after_it_has_no_video():
    assert seek_for(spans(), at(-1)) is None
    assert seek_for(spans(), at(201)) is None


def test_the_segment_edges_count_as_inside():
    assert seek_for(spans(), at(100)).segment == 0
    assert seek_for(spans(), at(130)).segment == 1


def test_no_segments_means_no_video_anywhere():
    assert seek_for([], at(10)) is None


def test_the_lead_in_can_be_changed():
    assert seek_for(spans(), at(42), lead_s=2).seek_s == 40.0


# -------------------------------------------------------------------------------- ffmpeg logs

SILENCE_LOG = """\
[silencedetect @ 000001] silence_start: -0.00130
[silencedetect @ 000001] silence_end: 4.2 | silence_duration: 4.2013
[silencedetect @ 000001] silence_start: 10.002
[silencedetect @ 000001] silence_end: 80.1 | silence_duration: 70.098
[silencedetect @ 000001] silence_start: 120.5
size=N/A time=00:02:00.00 bitrate=N/A speed= 300x
"""


def test_silencedetect_pairs_starts_with_ends_and_clamps_a_negative_start():
    stretches = parse_silencedetect(SILENCE_LOG, total_s=130.0)
    assert stretches == [(0.0, 4.2), (10.002, 80.1), (120.5, 130.0)]


def test_a_stretch_still_open_at_the_end_is_dropped_when_the_length_is_unknown():
    assert parse_silencedetect(SILENCE_LOG) == [(0.0, 4.2), (10.002, 80.1)]


def test_a_log_with_no_silence_gives_nothing():
    assert parse_silencedetect("size=N/A time=00:00:30.00 speed=100x\n", total_s=30) == []
    assert parse_silencedetect("") == []


def test_durations_are_read_from_the_log():
    assert parse_duration("  Duration: 00:01:30.50, start: 0.000000, bitrate: 174 kb/s") == 90.5
    assert parse_duration("  Duration: 01:00:00.00, start: 0") == 3600.0
    assert parse_duration("  Duration: N/A, start: 0.000000") is None


def test_the_last_progress_time_is_the_length_when_the_header_has_none():
    log = "frame=1 time=00:00:10.00 x\nframe=2 time=00:00:25.40 bitrate=N/A\n"
    assert parse_last_progress(log) == 25.4
    assert parse_last_progress("nothing here") is None


# ------------------------------------------------------------------------------------- store


def test_the_store_round_trips_a_file_and_leaves_no_partial_files(tmp_path):
    store = LocalVideoStore(tmp_path)
    key = chunk_key("abc123", 0, 7)
    assert key == "abc123/0/000007.chunk"
    assert not store.exists(key)

    store.put(key, b"hello")
    store.put(key, b"hello again")  # replacing is allowed and atomic

    assert store.exists(key) and store.read(key) == b"hello again"
    assert [p.name for p in (tmp_path / "abc123" / "0").iterdir()] == ["000007.chunk"]


def test_the_store_refuses_a_key_outside_its_root(tmp_path):
    store = LocalVideoStore(tmp_path / "video")
    for key in ("../escape.txt", "a/../../escape.txt", "/etc/passwd"):
        with pytest.raises(ValueError):
            store.put(key, b"x")
        with pytest.raises(ValueError):
            store.read(key)


def test_deleting_a_session_removes_only_that_session(tmp_path):
    store = LocalVideoStore(tmp_path)
    store.put(chunk_key("one", 0, 0), b"a")
    store.put(chunk_key("one", 0, 1), b"b")
    store.put(assembled_key("one", 0), b"c")
    store.put(chunk_key("two", 0, 0), b"d")

    assert store.delete_session("one") == 3
    assert not store.exists(chunk_key("one", 0, 0)) and not store.exists(assembled_key("one", 0))
    assert store.exists(chunk_key("two", 0, 0))
    assert store.delete_session("one") == 0  # nothing left: running it again is harmless
    assert store.delete_session("never-existed") == 0
