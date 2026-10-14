"""The wrong-code limiter, driven by the fake clock."""

from app.clock import FakeClock
from app.services.rate_limit import MAX_KEYS, AttemptLimiter


def test_a_client_is_blocked_after_max_failures_and_released_when_the_window_passes():
    clock = FakeClock()
    limiter = AttemptLimiter(max_failures=3, window_s=60)

    for _ in range(3):
        assert limiter.retry_after_s("a", clock.now()) == 0
        limiter.record_failure("a", clock.now())
        clock.advance(1)

    # the oldest failure was 3 s ago, so 57 s remain
    assert limiter.retry_after_s("a", clock.now()) == 57
    clock.advance(56)
    assert limiter.retry_after_s("a", clock.now()) == 1
    clock.advance(1)
    assert limiter.retry_after_s("a", clock.now()) == 0


def test_clients_do_not_share_a_count():
    clock = FakeClock()
    limiter = AttemptLimiter(max_failures=2, window_s=60)
    limiter.record_failure("a", clock.now())
    limiter.record_failure("a", clock.now())
    assert limiter.retry_after_s("a", clock.now()) > 0
    assert limiter.retry_after_s("b", clock.now()) == 0


def test_failures_that_have_aged_out_do_not_add_up():
    clock = FakeClock()
    limiter = AttemptLimiter(max_failures=3, window_s=60)
    limiter.record_failure("a", clock.now())
    limiter.record_failure("a", clock.now())
    clock.advance(61)
    limiter.record_failure("a", clock.now())
    assert limiter.retry_after_s("a", clock.now()) == 0


def test_memory_is_bounded_by_sweeping_expired_clients():
    clock = FakeClock()
    limiter = AttemptLimiter(max_failures=3, window_s=60)
    for i in range(MAX_KEYS):
        limiter.record_failure(f"client-{i}", clock.now())
    clock.advance(120)  # all of them have expired
    limiter.record_failure("fresh", clock.now())
    assert len(limiter._failures) == 1


def test_reset_forgets_everything():
    clock = FakeClock()
    limiter = AttemptLimiter(max_failures=1, window_s=60)
    limiter.record_failure("a", clock.now())
    assert limiter.retry_after_s("a", clock.now()) > 0
    limiter.reset()
    assert limiter.retry_after_s("a", clock.now()) == 0
