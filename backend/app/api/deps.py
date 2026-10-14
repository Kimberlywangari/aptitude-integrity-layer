from fastapi import Depends

from app.clock import Clock, SystemClock
from app.config import Settings, get_settings
from app.services.rate_limit import AttemptLimiter

_clock: Clock = SystemClock()
_start_limiter: AttemptLimiter | None = None


def get_clock() -> Clock:
    """FastAPI dependency. Tests override it with a FakeClock."""
    return _clock


def get_start_limiter(settings: Settings = Depends(get_settings)) -> AttemptLimiter:
    """FastAPI dependency: the one limiter for wrong invitation codes. Tests override it."""
    global _start_limiter
    if _start_limiter is None:
        _start_limiter = AttemptLimiter(settings.start_max_failures, settings.start_window_s)
    return _start_limiter
