import pytest
from prometheus_client import REGISTRY

from services.notification_service.app.rate_limit import RateLimiter


class _StubRedis:
    def __init__(
        self,
        *,
        fail_incr: bool = False,
        fail_expire: bool = False,
        fail_decr: bool = False,
    ) -> None:
        self._store: dict[str, int] = {}
        self.fail_incr = fail_incr
        self.fail_expire = fail_expire
        self.fail_decr = fail_decr
        self.expire_calls: list[tuple[str, int]] = []

    async def incrby(self, key: str, amount: int) -> int:
        if self.fail_incr:
            raise RuntimeError("incr failure")
        value = self._store.get(key, 0) + amount
        self._store[key] = value
        return value

    async def expire(self, key: str, seconds: int) -> bool:
        self.expire_calls.append((key, seconds))
        if self.fail_expire:
            raise RuntimeError("expire failure")
        return True

    async def decrby(self, key: str, amount: int) -> int:
        if self.fail_decr:
            raise RuntimeError("decr failure")
        value = self._store.get(key, 0) - amount
        self._store[key] = value
        return value


class _MetricTracker:
    def __init__(self, name: str, labels: dict[str, str] | None = None) -> None:
        self.name = name
        self.labels = labels or {}
        baseline = REGISTRY.get_sample_value(name, self.labels)
        self._baseline = baseline if baseline is not None else 0.0

    def delta(self) -> float:
        current = REGISTRY.get_sample_value(self.name, self.labels)
        value = current if current is not None else 0.0
        return value - self._baseline


@pytest.mark.asyncio
async def test_rate_limiter_allows_within_limit() -> None:
    redis = _StubRedis()
    limiter = RateLimiter(redis_client=redis, limit=5, window_seconds=30)

    for _ in range(5):
        assert await limiter.allow("EMAIL") is True

    assert redis.expire_calls
    assert redis._store["notification_rate:email"] == 5


@pytest.mark.asyncio
async def test_rate_limiter_blocks_when_limit_exceeded() -> None:
    redis = _StubRedis()
    limiter = RateLimiter(redis_client=redis, limit=2, window_seconds=30)

    assert await limiter.allow("SMS") is True
    assert await limiter.allow("SMS") is True
    assert await limiter.allow("SMS") is False
    assert redis._store["notification_rate:sms"] == 2


@pytest.mark.asyncio
async def test_rate_limiter_allows_when_increment_fails() -> None:
    redis = _StubRedis(fail_incr=True)
    limiter = RateLimiter(redis_client=redis, limit=1, window_seconds=30)
    error_tracker = _MetricTracker(
        "notification_rate_limit_errors_total",
        {"operation": "incrby"},
    )

    assert await limiter.allow("PUSH") is True
    assert error_tracker.delta() == 1


@pytest.mark.asyncio
async def test_rate_limiter_records_expire_failure() -> None:
    redis = _StubRedis(fail_expire=True)
    limiter = RateLimiter(redis_client=redis, limit=2, window_seconds=60)
    error_tracker = _MetricTracker(
        "notification_rate_limit_errors_total",
        {"operation": "expire"},
    )

    assert await limiter.allow("EMAIL") is True
    assert error_tracker.delta() == 1


@pytest.mark.asyncio
async def test_rate_limiter_allows_when_decrement_fails() -> None:
    redis = _StubRedis(fail_decr=True)
    limiter = RateLimiter(redis_client=redis, limit=1, window_seconds=30)
    error_tracker = _MetricTracker(
        "notification_rate_limit_errors_total",
        {"operation": "decrby"},
    )

    assert await limiter.allow("EMAIL") is True
    # Second call would exceed quota and trigger decr failure.
    assert await limiter.allow("EMAIL") is True
    assert error_tracker.delta() == 1
