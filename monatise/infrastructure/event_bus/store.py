from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Protocol

from monatise.infrastructure.event_bus.models import EventEnvelope


class EventStore(Protocol):
    """Replaceable persistence boundary for event envelopes."""

    async def contains_idempotency_key(self, key: str) -> bool: ...

    async def append(self, envelope: EventEnvelope) -> bool: ...

    async def all(self) -> tuple[EventEnvelope, ...]: ...

    async def by_event_type(self, event_type: str) -> tuple[EventEnvelope, ...]: ...


class InMemoryEventStore:
    """Development event store.

    Production deployments may replace this with PostgreSQL, Redis Streams,
    Kafka, NATS JetStream, or another durable adapter.
    """

    def __init__(self) -> None:
        self._events: list[EventEnvelope] = []
        self._idempotency_keys: set[str] = set()
        self._lock = asyncio.Lock()

    async def contains_idempotency_key(self, key: str) -> bool:
        async with self._lock:
            return key in self._idempotency_keys

    async def append(self, envelope: EventEnvelope) -> bool:
        async with self._lock:
            if envelope.idempotency_key in self._idempotency_keys:
                return False
            self._events.append(deepcopy(envelope))
            self._idempotency_keys.add(envelope.idempotency_key)
            return True

    async def all(self) -> tuple[EventEnvelope, ...]:
        async with self._lock:
            return tuple(deepcopy(self._events))

    async def by_event_type(
        self,
        event_type: str,
    ) -> tuple[EventEnvelope, ...]:
        async with self._lock:
            return tuple(deepcopy(tuple(
                envelope
                for envelope in self._events
                if envelope.event.event_type == event_type
            )))
