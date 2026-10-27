# How a flag finds its moment in the video

The page tells the server when each recorder run starts (`recording_started {segment}`, with its
`age_ms`). The server stores that moment on **its own clock**: `server_ts = receive time - age_ms`.
That is the anchor for the segment.

For any flag, mic stretch or other moment with a server time:

```
video offset = moment's server_ts - segment's recording_started server_ts
jump to      = max(0, offset - 5 s)
```

The segment is the one whose `[start, start + duration]` holds the moment. If none does (the camera
dropped and the next run had not begun, or the upload never finished) there is no video at that
moment and the page says so. `backend/app/services/video/seek.py` is this arithmetic, and
`backend/tests/unit/test_video_pure.py` checks it by hand.

Why this holds: the server clock is the only clock that counts, a late event keeps its true moment
through `age_ms`, and the duration of each segment comes from the assembled file itself. What it
cannot remove is the delay between the recorder starting and the page noticing `onstart`; the
seek-accuracy check (`python -m scripts.jobs video_offset`) measures the error in practice, against
the 2-second target.
