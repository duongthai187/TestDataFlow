from typing import Any


class KafkaProducerStub:
    """Lightweight Kafka producer placeholder for integration in later waves."""

    def __init__(self, **_kwargs: Any) -> None:
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def send(self, topic: str, value: dict[str, Any]) -> None:
        if not self._connected:
            raise RuntimeError("Producer not connected")
        # Placeholder: integrate with aiokafka or confluent-kafka in later waves.

    async def close(self) -> None:
        self._connected = False
