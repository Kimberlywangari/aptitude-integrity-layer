"""Reading the tracks out of a WebM header, including whatever a damaged upload could send."""

import pytest

from app.services.video.webm import Tracks, read_tracks
from tests.support import media_chunk, webm_header


@pytest.mark.parametrize("unknown_segment", [True, False])
def test_a_header_with_video_and_audio_is_read(unknown_segment):
    assert read_tracks(webm_header(unknown_segment=unknown_segment)) == Tracks(video=1, audio=1)


def test_video_only_and_audio_only_are_told_apart():
    assert read_tracks(webm_header(audio=False)) == Tracks(video=1, audio=0)
    assert read_tracks(webm_header(video=False)) == Tracks(video=0, audio=1)


def test_a_later_chunk_has_no_header_so_it_is_not_judged():
    assert read_tracks(media_chunk(1)) is None


def test_garbage_and_empty_input_never_raise():
    assert read_tracks(b"") is None
    assert read_tracks(b"not a webm file at all") is None
    assert read_tracks(b"\x1a\x45\xdf\xa3") == Tracks(0, 0)  # the magic and nothing else


@pytest.mark.parametrize("cut", range(0, 80, 3))
def test_a_header_cut_short_anywhere_never_raises(cut):
    result = read_tracks(webm_header()[:cut])
    assert result is None or isinstance(result, Tracks)


def test_a_header_with_no_tracks_reads_as_none_found():
    from tests.support import UNKNOWN_SIZE, element

    ebml = element(0x1A45DFA3, element(0x4282, b"webm"))
    segment = b"\x18\x53\x80\x67" + UNKNOWN_SIZE + element(0x1F43B675, element(0xE7, b"\x00"))
    assert read_tracks(ebml + segment) == Tracks(0, 0)
