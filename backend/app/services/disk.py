"""How much room is left where the recordings are kept. Video is the one thing here that grows
without limit (about 80 MB an hour per candidate), so a full disk is the likeliest way a sitting
breaks. The staff overview and /api/health both read this, so they cannot disagree."""

import shutil
from pathlib import Path

# About 125 candidate-hours of recording. Under this, free space or move the recordings.
LOW_FREE_BYTES = 10 * 1024**3


def free_and_total(path: Path) -> tuple[int, int]:
    """Bytes free and in all on the disk `path` lives on. The folder is made by the first upload,
    so until then the nearest folder that exists stands in for it."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return usage.free, usage.total


def is_low(path: Path) -> bool:
    return free_and_total(path)[0] < LOW_FREE_BYTES
