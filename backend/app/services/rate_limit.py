"""A cheap limit on wrong invitation codes.

Invitation codes are short enough to type by hand (40 bits), so the start endpoint refuses a
client that keeps sending codes that do not exist. Only failures count: a venue full of honest
candidates behind one address never locks itself out by starting tests.

In memory and per process, which is enough to make online guessing impractical; it is not shared
between workers. Time comes from the injected clock, never from datetime.now().
"""

import math
from collections import deque
from datetime import datetime

# A bound on memory: past this many keys, expired entries are swept on the next failure.
MAX_KEYS = 10_000


class AttemptLimiter:
    def __init__(self, max_failures: int, window_s: float) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self._failures: dict[str, deque[float]] = {}

    def _live(self, key: str, now_ts: float) -> deque[float]:
        recent = self._failures.get(key)
        if recent is None:
            return deque()
        while recent and recent[0] <= now_ts - self.window_s:
            recent.popleft()
        if not recent:
            del self._failures[key]
            return deque()
        return recent

    def retry_after_s(self, key: str, now: datetime) -> int:
        """Whole seconds until `key` may try again, or 0 when it may try now."""
        now_ts = now.timestamp()
        recent = self._live(key, now_ts)
        if len(recent) < self.max_failures:
            return 0
        return max(1, math.ceil(recent[0] + self.window_s - now_ts))

    def record_failure(self, key: str, now: datetime) -> None:
        now_ts = now.timestamp()
        if len(self._failures) >= MAX_KEYS:
            for stale in list(self._failures):
                self._live(stale, now_ts)
        self._failures.setdefault(key, deque()).append(now_ts)
        recent = self._failures[key]
        while len(recent) > self.max_failures:
            recent.popleft()  # older failures no longer change the answer

    def reset(self) -> None:
        self._failures.clear()
