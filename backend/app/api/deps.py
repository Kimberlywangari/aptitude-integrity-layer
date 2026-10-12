from app.clock import Clock, SystemClock

_clock: Clock = SystemClock()


def get_clock() -> Clock:
    """FastAPI dependency. Tests override it with a FakeClock."""
    return _clock
