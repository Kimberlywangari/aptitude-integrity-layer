"""The three things the server asks ffmpeg to do. Everything else in the video code is plain
Python, so only these functions need the binary, and tests can swap them for fakes.

Only `ffmpeg` is needed (not `ffprobe`): its own log carries the duration.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
PROGRESS_TIME = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


class FfmpegMissing(RuntimeError):
    """ffmpeg is not installed or not on PATH (set FFMPEG_BIN to point at it)."""


class FfmpegFailed(RuntimeError):
    """ffmpeg ran and refused the input; the message is the end of its own log."""


def ffmpeg_path() -> str:
    found = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg")
    if not found:
        raise FfmpegMissing("ffmpeg was not found: install it or set FFMPEG_BIN")
    return found


def available() -> bool:
    try:
        ffmpeg_path()
    except FfmpegMissing:
        return False
    return True


def run(args: list[str], *, timeout: float = 900, check: bool = True) -> str:
    """Run ffmpeg and return its log (stderr). `check=False` for the few calls that are meant to
    end in an error, such as asking it to read a file and write nothing."""
    try:
        done = subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-nostdin", *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise FfmpegFailed(f"ffmpeg took longer than {timeout:g} s") from exc
    if check and done.returncode != 0:
        raise FfmpegFailed(done.stderr.strip()[-600:] or f"ffmpeg exited {done.returncode}")
    return done.stderr


def _seconds(match: re.Match[str]) -> float:
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_duration(log: str) -> float | None:
    """The duration ffmpeg reports for its input, or None when it says N/A."""
    found = DURATION.search(log)
    return _seconds(found) if found else None


def parse_last_progress(log: str) -> float | None:
    matches = list(PROGRESS_TIME.finditer(log))
    return _seconds(matches[-1]) if matches else None


def remux(source: Path, target: Path) -> None:
    """Rewrite the file without re-encoding, so it gets a duration and a seek index. A recorder's
    raw output has neither, which is why scrubbing it does not work."""
    run(["-y", "-i", str(source), "-c", "copy", str(target)])


def probe_duration(path: Path) -> float:
    """How long a file is. Reads the header; if the container has no duration, reads the whole
    file once without decoding it."""
    header = run(["-i", str(path)], check=False)
    found = parse_duration(header)
    if found is not None:
        return found
    log = run(["-i", str(path), "-c", "copy", "-f", "null", "-"])
    return parse_last_progress(log) or 0.0


def silencedetect(path: Path, noise_db: float, min_s: float) -> str:
    """ffmpeg's log of the quiet stretches in a file's audio (video is ignored)."""
    return run(
        [
            "-i",
            str(path),
            "-vn",
            "-af",
            f"silencedetect=noise={noise_db:g}dB:d={min_s:g}",
            "-f",
            "null",
            "-",
        ]
    )
