"""Where the video bytes live, behind one small interface so cloud storage can replace the local
disk later without touching the rest of the app.

Keys are plain relative paths such as `<session_id>/<segment>/<seq>.chunk`. The local store keeps
them under one root folder, writes each file whole (a half-written chunk is never visible) and
refuses a key that would step outside the root.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Protocol


class VideoStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def read(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def local_path(self, key: str) -> Path:
        """A file on this machine for ffmpeg and for range responses. A cloud store would fetch
        the object to a cache and return that."""
        ...

    def delete_session(self, session_id: str) -> int:
        """Remove everything stored for one session. Returns the number of files removed."""
        ...


def chunk_key(session_id: str, segment: int, seq: int) -> str:
    return f"{session_id}/{segment}/{seq:06d}.chunk"


def assembled_key(session_id: str, segment: int) -> str:
    return f"{session_id}/assembled/seg{segment}.webm"


class LocalVideoStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        root = self.root.resolve()
        if root != path and root not in path.parents:
            raise ValueError(f"key {key!r} is outside the video root")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # write beside the target, then rename: readers see the old file or the whole new one
        handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".part")
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(data)
            os.replace(temp_name, path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def local_path(self, key: str) -> Path:
        return self._path(key)

    def delete_session(self, session_id: str) -> int:
        folder = self._path(session_id)
        if not folder.is_dir():
            return 0
        count = sum(1 for p in folder.rglob("*") if p.is_file())
        shutil.rmtree(folder, ignore_errors=True)
        return count
