from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Awaitable, Callable, Protocol
from uuid import uuid4


class EventPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class DeliveryMode(StrEnum):
    AT_MOST_ONCE = "at_most_once"
    AT_LEAST_ONCE = "at_least_once"


@dataclass(frozen=True)
class DomainEvent:
    event_type: str
    payload: dict[str, Any]
    source: str
    symbol: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    priority: EventPriority = EventPriority.NORMAL
    schema_version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.event_type, str):
            raise ValueError("event_type must be a string")
        if not isinstance(self.source, str):
            raise ValueError("source must be a string")
        if not self.event_type.strip():
            raise ValueError("event_type is required")
        if not self.source.strip():
            raise ValueError("source is required")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a dictionary")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dictionary")


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event: DomainEvent
    created_at: datetime
    sequence: int
    idempotency_key: str
    delivery_mode: DeliveryMode
    attempt: int = 1
    max_attempts: int = 3

    @classmethod
    def create(
        cls,
        event: DomainEvent,
        *,
        sequence: int,
        idempotency_key: str,
        delivery_mode: DeliveryMode,
        max_attempts: int,
    ) -> "EventEnvelope":
        event.validate()
        return cls(
            event_id=str(uuid4()),
            event=deepcopy(event),
            created_at=datetime.now(timezone.utc),
            sequence=sequence,
            idempotency_key=idempotency_key,
            delivery_mode=delivery_mode,
            max_attempts=max_attempts,
        )


@dataclass(frozen=True)
class HandlerResult:
    handler_name: str
    success: bool
    attempt: int
    error: str | None = None


@dataclass(frozen=True)
class EventPublishResult:
    envelope: EventEnvelope
    handler_results: tuple[HandlerResult, ...]
    duplicate: bool
    persisted: bool

    @property
    def successful(self) -> bool:
        return all(result.success for result in self.handler_results)


class EventHandler(Protocol):
    async def __call__(self, envelope: EventEnvelope) -> None:
        ...


HandlerCallable = Callable[[EventEnvelope], Awaitable[None]]
