from __future__ import annotations

import asyncio
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
from json import dumps
from typing import Iterable

from monatise.infrastructure.event_bus.models import (
    DeliveryMode,
    DomainEvent,
    EventEnvelope,
    EventPublishResult,
    HandlerCallable,
    HandlerResult,
)
from monatise.infrastructure.event_bus.store import EventStore, InMemoryEventStore


class EventBus:
    """Async in-process event bus with persistence and idempotency.

    The bus is infrastructure only. It does not alter engine decisions and
    cannot execute trades.
    """

    def __init__(
        self,
        *,
        store: EventStore | None = None,
        delivery_mode: DeliveryMode = DeliveryMode.AT_LEAST_ONCE,
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.05,
    ) -> None:
        if not isinstance(delivery_mode, DeliveryMode):
            raise ValueError("delivery_mode is invalid")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")

        self._store = store or InMemoryEventStore()
        self._delivery_mode = delivery_mode
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._handlers: dict[str, list[HandlerCallable]] = defaultdict(list)
        self._sequence = 0
        self._sequence_lock = asyncio.Lock()

    def subscribe(
        self,
        event_type: str,
        handler: HandlerCallable,
    ) -> None:
        if not event_type.strip():
            raise ValueError("event_type is required")
        if not callable(handler):
            raise ValueError("event handler must be callable")
        if handler in self._handlers[event_type]:
            return
        self._handlers[event_type].append(handler)

    def unsubscribe(
        self,
        event_type: str,
        handler: HandlerCallable,
    ) -> None:
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(
        self,
        event: DomainEvent,
        *,
        idempotency_key: str | None = None,
    ) -> EventPublishResult:
        event.validate()
        key = idempotency_key or self._default_idempotency_key(event)

        if await self._store.contains_idempotency_key(key):
            envelope = EventEnvelope.create(
                event,
                sequence=await self._next_sequence(),
                idempotency_key=key,
                delivery_mode=self._delivery_mode,
                max_attempts=self._max_attempts,
            )
            return EventPublishResult(
                envelope=envelope,
                handler_results=(),
                duplicate=True,
                persisted=False,
            )

        envelope = EventEnvelope.create(
            event,
            sequence=await self._next_sequence(),
            idempotency_key=key,
            delivery_mode=self._delivery_mode,
            max_attempts=self._max_attempts,
        )

        persisted = await self._store.append(envelope)
        if not persisted:
            return EventPublishResult(
                envelope=envelope,
                handler_results=(),
                duplicate=True,
                persisted=False,
            )

        handlers = tuple(self._handlers.get(event.event_type, ()))
        results = await asyncio.gather(
            *(
                self._deliver(handler, envelope)
                for handler in handlers
            )
        )

        return EventPublishResult(
            envelope=envelope,
            handler_results=tuple(results),
            duplicate=False,
            persisted=True,
        )

    async def publish_many(
        self,
        events: Iterable[DomainEvent],
    ) -> tuple[EventPublishResult, ...]:
        return tuple(
            await asyncio.gather(
                *(self.publish(event) for event in events)
            )
        )

    async def _deliver(
        self,
        handler: HandlerCallable,
        envelope: EventEnvelope,
    ) -> HandlerResult:
        handler_name = getattr(handler, "__name__", handler.__class__.__name__)
        attempts = (
            1
            if self._delivery_mode is DeliveryMode.AT_MOST_ONCE
            else self._max_attempts
        )

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                await handler(deepcopy(envelope))
                return HandlerResult(
                    handler_name=handler_name,
                    success=True,
                    attempt=attempt,
                )
            except Exception as exc:
                last_error = exc
                if attempt < attempts and self._retry_delay_seconds:
                    await asyncio.sleep(self._retry_delay_seconds)

        return HandlerResult(
            handler_name=handler_name,
            success=False,
            attempt=attempts,
            error=(
                f"{type(last_error).__name__}: {last_error}"
                if last_error is not None
                else "unknown handler error"
            ),
        )

    async def _next_sequence(self) -> int:
        async with self._sequence_lock:
            self._sequence += 1
            return self._sequence

    @staticmethod
    def _default_idempotency_key(event: DomainEvent) -> str:
        raw = dumps(
            {
                "event_type": event.event_type,
                "payload": event.payload,
                "source": event.source,
                "symbol": event.symbol,
                "correlation_id": event.correlation_id,
                "causation_id": event.causation_id,
                "schema_version": event.schema_version,
            },
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        return sha256(raw.encode("utf-8")).hexdigest()

    @property
    def store(self) -> EventStore:
        return self._store
