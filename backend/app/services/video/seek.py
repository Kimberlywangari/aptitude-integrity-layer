"""Where a moment sits in the saved video. Pure, so the "flag lands within 2 seconds" claim rests on
arithmetic that can be checked by hand.

The video offset of a moment is its server time minus the server time the segment started (the
`recording_started` event). The reviewer is sent to 5 seconds before it.
"""

from dataclasses import dataclass
from datetime import datetime

LEAD_S = 5.0


@dataclass(frozen=True)
class SegmentSpan:
    segment: int
    started_at: datetime
    duration_s: float


@dataclass(frozen=True)
class Seek:
    segment: int
    seek_s: float


def seek_for(spans: list[SegmentSpan], moment: datetime, lead_s: float = LEAD_S) -> Seek | None:
    """The segment holding `moment` and the second to start playing from, or None when nothing
    was recording then (a camera drop between segments, or an upload that never finished)."""
    for span in sorted(spans, key=lambda s: s.started_at):
        offset = (moment - span.started_at).total_seconds()
        if 0 <= offset <= span.duration_s:
            return Seek(span.segment, max(0.0, round(offset - lead_s, 3)))
    return None
