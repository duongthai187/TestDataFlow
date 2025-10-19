from typing import cast

import pytest
from prometheus_client import REGISTRY

from services.notification_service.app.repository import NotificationRepository
from services.notification_service.app.services import NotificationService, RateLimitExceeded


class _StubRepository:
    """Minimal repository stub used for NotificationService tests."""

    # The service never touches repository in the rate limit helper, but the
    # constructor requires one. Keeping this stub for clarity and future use.
    async def dummy(self) -> None:  # pragma: no cover - defensive stub
        return None


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


class _AllowLimiter:
    async def allow(self, channel: str, *, amount: int = 1) -> bool:
        self.channel = channel
        self.amount = amount
        return True


class _DenyLimiter:
    async def allow(self, channel: str, *, amount: int = 1) -> bool:
        self.channel = channel
        self.amount = amount
        return False


class _RecorderLimiter:
    def __init__(self) -> None:
        self.called = False
        self.channel: str | None = None
        self.amount: int | None = None

    async def allow(self, channel: str, *, amount: int = 1) -> bool:
        self.called = True
        self.channel = channel
        self.amount = amount
        return True


@pytest.mark.asyncio
async def test_enforce_rate_limit_allows_when_under_quota() -> None:
    limiter = _AllowLimiter()
    service = NotificationService(repository=cast(NotificationRepository, _StubRepository()), rate_limiter=limiter)
    tracker = _MetricTracker("notification_rate_limited_total", {"channel": "email"})

    await service._enforce_rate_limit("email", amount=2)

    assert limiter.channel == "email"
    assert limiter.amount == 2
    assert tracker.delta() == 0


@pytest.mark.asyncio
async def test_enforce_rate_limit_raises_and_counts_when_denied() -> None:
    limiter = _DenyLimiter()
    service = NotificationService(repository=cast(NotificationRepository, _StubRepository()), rate_limiter=limiter)
    tracker = _MetricTracker("notification_rate_limited_total", {"channel": "sms"})

    with pytest.raises(RateLimitExceeded):
        await service._enforce_rate_limit("sms", amount=1)

    assert limiter.channel == "sms"
    assert limiter.amount == 1
    assert tracker.delta() == 1


@pytest.mark.asyncio
async def test_enforce_rate_limit_skips_when_amount_is_zero() -> None:
    limiter = _RecorderLimiter()
    service = NotificationService(repository=cast(NotificationRepository, _StubRepository()), rate_limiter=limiter)
    tracker = _MetricTracker("notification_rate_limited_total", {"channel": "push"})

    await service._enforce_rate_limit("push", amount=0)

    assert limiter.called is False
    assert tracker.delta() == 0


@pytest.mark.asyncio
async def test_enforce_rate_limit_noop_without_limiter() -> None:
    service = NotificationService(repository=cast(NotificationRepository, _StubRepository()), rate_limiter=None)
    tracker = _MetricTracker("notification_rate_limited_total", {"channel": "whatsapp"})

    await service._enforce_rate_limit("whatsapp", amount=3)

    assert tracker.delta() == 0
