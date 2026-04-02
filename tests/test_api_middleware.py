import pytest

pytest.importorskip("fastapi")

from sena.api.middleware import FixedWindowRateLimiter


def test_fixed_window_rate_limiter_limits_and_expires() -> None:
    limiter = FixedWindowRateLimiter(max_requests=2, window_seconds=10)

    assert limiter.allow("k", now=100.0)
    assert limiter.allow("k", now=101.0)
    assert not limiter.allow("k", now=102.0)
    assert limiter.allow("k", now=111.0)


def test_fixed_window_rate_limiter_rejects_invalid_config() -> None:
    with pytest.raises(ValueError):
        FixedWindowRateLimiter(max_requests=0, window_seconds=1)
    with pytest.raises(ValueError):
        FixedWindowRateLimiter(max_requests=1, window_seconds=0)
