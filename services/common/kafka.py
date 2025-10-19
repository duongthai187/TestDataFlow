from __future__ import annotations

from collections import defaultdict
from typing import Any, Awaitable, Callable, Sequence


class _InMemoryBroker:
    """Very small in-memory dispatcher shared by stubbed Kafka components."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[dict[str, Any]], Awaitable[None]]]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        handlers = self._subscribers.get(topic)
        if handlers and handler in handlers:
            handlers.remove(handler)
            if not handlers:
                self._subscribers.pop(topic, None)

    async def publish(self, topic: str, message: dict[str, Any]) -> None:
        # Iterate over a copy in case handlers mutate subscriptions.
        for handler in list(self._subscribers.get(topic, [])):
            await handler(message)


_BROKER = _InMemoryBroker()


class KafkaProducerStub:
    """Lightweight Kafka producer placeholder for integration in later waves."""

    def __init__(self, **_kwargs: Any) -> None:
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def send(self, topic: str, value: dict[str, Any]) -> None:
        if not self._connected:
            raise RuntimeError("Producer not connected")
        await _BROKER.publish(topic, value)

    async def close(self) -> None:
        self._connected = False


class KafkaConsumerStub:
    """Minimal async consumer stub used for local development and tests."""

    def __init__(
        self,
        topics: Sequence[str],
        handler: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._topics = list(topics)
        self._handler = handler
        self._registrations: list[tuple[str, Callable[[dict[str, Any]], Awaitable[None]]]] = []
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        for topic in self._topics:
            async def _callback(message: dict[str, Any], current_topic: str = topic) -> None:
                await self._handler(current_topic, message)

            _BROKER.subscribe(topic, _callback)
            self._registrations.append((topic, _callback))
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        for topic, callback in self._registrations:
            _BROKER.unsubscribe(topic, callback)
        self._registrations.clear()
        self._started = False
