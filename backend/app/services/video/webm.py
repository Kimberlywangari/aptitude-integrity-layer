"""Read just enough of a WebM header to say whether a recording has a video track and an audio
track. A pure function over bytes, so the start-of-test gate needs no ffprobe and no subprocess.

WebM is EBML: every element is an ID, a size and a body. The first chunk a browser's recorder
produces holds the container header, including the Tracks element, ahead of the first Cluster.
Later chunks carry only clusters and have no header, so they simply read as "no tracks here".
"""

from dataclasses import dataclass

EBML_HEADER = 0x1A45DFA3
SEGMENT = 0x18538067
TRACKS = 0x1654AE6B
TRACK_ENTRY = 0xAE
TRACK_TYPE = 0x83
CLUSTER = 0x1F43B675

VIDEO_TRACK = 1
AUDIO_TRACK = 2
EBML_MAGIC = EBML_HEADER.to_bytes(4, "big")


@dataclass(frozen=True)
class Tracks:
    video: int
    audio: int


def _read_id(data: bytes, pos: int) -> tuple[int, int] | None:
    """An element ID keeps its length marker bits. Returns (id, bytes used)."""
    if pos >= len(data):
        return None
    first = data[pos]
    length = 1
    mask = 0x80
    while length <= 4 and not first & mask:
        length += 1
        mask >>= 1
    if length > 4 or pos + length > len(data):
        return None
    return int.from_bytes(data[pos : pos + length], "big"), length


def _read_size(data: bytes, pos: int) -> tuple[int | None, int] | None:
    """A size is a variable-length integer without its marker. All ones means 'unknown', which a
    live recorder uses for the Segment. Returns (size or None, bytes used)."""
    if pos >= len(data):
        return None
    first = data[pos]
    length = 1
    mask = 0x80
    while length <= 8 and not first & mask:
        length += 1
        mask >>= 1
    if length > 8 or pos + length > len(data):
        return None
    value = first & (mask - 1)
    for byte in data[pos + 1 : pos + length]:
        value = (value << 8) | byte
    unknown = value == (1 << (7 * length)) - 1
    return (None if unknown else value), length


def _elements(data: bytes, start: int, end: int):
    """Walk sibling elements in data[start:end], yielding (id, body_start, body_end)."""
    pos = start
    while pos < end:
        element = _read_id(data, pos)
        if element is None:
            return
        element_id, id_len = element
        size = _read_size(data, pos + id_len)
        if size is None:
            return
        body_len, size_len = size
        body_start = pos + id_len + size_len
        body_end = end if body_len is None else min(end, body_start + body_len)
        yield element_id, body_start, body_end
        if body_len is None:  # unknown size: it runs to the end of what we can see
            return
        pos = body_start + body_len


def _count_tracks(data: bytes, start: int, end: int) -> Tracks:
    video = audio = 0
    for element_id, body_start, body_end in _elements(data, start, end):
        if element_id != TRACK_ENTRY:
            continue
        for child_id, child_start, child_end in _elements(data, body_start, body_end):
            if child_id == TRACK_TYPE and child_end > child_start:
                kind = int.from_bytes(data[child_start:child_end], "big")
                video += kind == VIDEO_TRACK
                audio += kind == AUDIO_TRACK
    return Tracks(video, audio)


def read_tracks(data: bytes) -> Tracks | None:
    """The tracks declared in this chunk, or None when it is not the start of a WebM file (a
    later chunk, or not WebM at all). Never raises on malformed input."""
    if not data.startswith(EBML_MAGIC):
        return None
    top_end = len(data)
    for element_id, body_start, body_end in _elements(data, 0, top_end):
        if element_id == SEGMENT:
            for child_id, child_start, child_end in _elements(data, body_start, body_end):
                if child_id == TRACKS:
                    return _count_tracks(data, child_start, child_end)
                if child_id == CLUSTER:
                    break  # the header ends where media starts
            return Tracks(0, 0)
    return Tracks(0, 0)
