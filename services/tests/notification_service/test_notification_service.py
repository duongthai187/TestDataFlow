from types import SimpleNamespace
from typing import Any, cast

import pytest
from prometheus_client import REGISTRY

from services.notification_service.app.models import Notification
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


class _RecordingRepository:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.status_history: list[tuple[str, Any, str | None]] = []

    async def add_event(self, notification: SimpleNamespace, *, event_type: str, payload: str) -> object:
        notification.events.append({"type": event_type, "payload": payload})
        self.events.append((event_type, payload))
        return object()

    async def update_status(
        self,
        notification: SimpleNamespace,
        *,
        status: str,
        sent_at,
        error_message: str | None,
    ) -> SimpleNamespace:
        notification.status = status
        notification.sent_at = sent_at
        notification.error_message = error_message
        self.status_history.append((status, sent_at, error_message))
        return notification


class _SuccessfulProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class _FailingProvider:
    def __init__(self, message: str = "smtp down") -> None:
        self.message = message
        self.calls = 0

    async def send(self, **_: Any) -> None:
        self.calls += 1
        raise RuntimeError(self.message)


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


def _notification(channel: str = "email") -> Notification:
    return cast(
        Notification,
        SimpleNamespace(
        id=101,
        recipient="user@example.com",
        channel=channel,
        subject="Hello",
        body="Body",
        template=None,
        metadata_json=None,
        status="pending",
        sent_at=None,
        error_message=None,
            events=[],
        ),
    )


@pytest.mark.asyncio
async def test_send_notification_success_records_metrics_and_events() -> None:
    repo = _RecordingRepository()
    provider = _SuccessfulProvider()
    limiter = _AllowLimiter()
    notification = _notification()
    sent_tracker = _MetricTracker("notification_sent_total", {"channel": "email"})
    latency_tracker = _MetricTracker("notification_send_latency_seconds_count", {"channel": "email"})

    service = NotificationService(
        repository=cast(NotificationRepository, repo),
        provider=provider,
        rate_limiter=limiter,
    )

    updated = await service.send_notification(notification)

    assert provider.calls and provider.calls[0]["recipient"] == "user@example.com"
    assert updated.status == "sent"
    assert any(event[0] == "sent" for event in repo.events)
    assert sent_tracker.delta() == 1
    assert latency_tracker.delta() == 1


@pytest.mark.asyncio
async def test_send_notification_marks_failure_when_provider_raises() -> None:
    repo = _RecordingRepository()
    provider = _FailingProvider("smtp timeout")
    notification = _notification()
    failure_tracker = _MetricTracker("notification_failure_total", {"channel": "email"})

    service = NotificationService(
        repository=cast(NotificationRepository, repo),
        provider=provider,
        rate_limiter=None,
    )

    with pytest.raises(RuntimeError):
        await service.send_notification(notification)

    assert notification.status == "failed"
    assert "provider_error" in (notification.error_message or "")
    assert any(event[0] == "failed" for event in repo.events)
    assert not any(event[0] == "sent" for event in repo.events)
    assert failure_tracker.delta() == 1
