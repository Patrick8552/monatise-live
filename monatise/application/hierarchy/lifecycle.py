from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from monatise.application.hierarchy.models import EvidenceContext, deterministic_id


class LifecycleEventType(StrEnum):
    CONTEXT_CREATED = "context_created"
    CONTEXT_SUPERSEDED = "context_superseded"
    CANDLE_REVISED = "candle_revised"
    TRIGGER_EVALUATED = "trigger_evaluated"
    DECISION_RECORDED = "decision_recorded"
    PUBLICATION_RECORDED = "publication_recorded"


@dataclass(frozen=True)
class LifecycleEvent:
    event_id: str
    event_type: LifecycleEventType
    symbol: str
    occurred_at: datetime
    context_id: str | None
    previous_context_id: str | None = None
    replacement_context_id: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("event time must be timezone-aware")


class LifecycleStore(Protocol):
    async def put(self, namespace: str, key: str, value: dict[str, Any], **kwargs: Any) -> Any: ...
    async def get(self, namespace: str, key: str) -> Any | None: ...
    async def append(self, stream: str, value: dict[str, Any]) -> None: ...
    async def read_stream(self, stream: str) -> tuple[dict[str, Any], ...]: ...


def _json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    return value


class HierarchyRepository:
    """Append-only lifecycle history plus optimistic current-state pointers."""

    def __init__(self, store: LifecycleStore) -> None:
        self.store = store
        self._symbol_locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def symbol_lock(self, symbol: str) -> asyncio.Lock:
        normalized = symbol.strip().upper()
        async with self._guard:
            return self._symbol_locks.setdefault(normalized, asyncio.Lock())

    async def append_context(self, context: EvidenceContext, *, expected_current_version: int | None = None) -> int:
        symbol = context.identity.symbol
        layer = context.identity.source_timeframe
        async with await self.symbol_lock(symbol):
            current_key = f"{symbol}:{layer}"
            current = await self.store.get("hierarchy_current", current_key)
            actual_version = int(current.version) if current is not None else 0
            if expected_current_version is not None and actual_version != expected_current_version:
                raise RuntimeError(f"hierarchy state version conflict: expected {expected_current_version}, actual {actual_version}")
            serialized = _json(asdict(context))
            if current is not None and current.value.get("context_id") == context.identity.context_id:
                return actual_version
            try:
                await self.store.put("hierarchy_context", context.identity.context_id, serialized, expected_version=0)
            except RuntimeError:
                existing = await self.store.get("hierarchy_context", context.identity.context_id)
                if existing is None or existing.value != serialized:
                    raise RuntimeError("immutable hierarchy context conflict")
            pointer = await self.store.put("hierarchy_current", current_key, {"context_id": context.identity.context_id}, expected_version=actual_version)
            await self._append_event(LifecycleEvent(
                deterministic_id("event", {"type": "created", "context": context.identity.context_id}),
                LifecycleEventType.CONTEXT_CREATED, symbol, context.evaluated_at, context.identity.context_id,
            ))
            if current is not None and current.value.get("context_id") != context.identity.context_id:
                await self._append_event(LifecycleEvent(
                    deterministic_id("event", {"type": "superseded", "old": current.value.get("context_id"), "new": context.identity.context_id}),
                    LifecycleEventType.CONTEXT_SUPERSEDED, symbol, context.evaluated_at, context.identity.context_id,
                    previous_context_id=current.value.get("context_id"), replacement_context_id=context.identity.context_id,
                    reason="new_context_for_layer",
                ))
            return int(pointer.version)

    async def claim_trigger(self, *, symbol: str, candle_close_time: datetime, setup_id: str, direction: str, trigger_type: str, strategy_version: str, occurred_at: datetime) -> tuple[bool, str]:
        identity = deterministic_id("trigger", {
            "symbol": symbol.upper(), "candle_close_time": candle_close_time.isoformat(), "setup_id": setup_id,
            "direction": direction, "trigger_type": trigger_type, "strategy_version": strategy_version,
        })
        async with await self.symbol_lock(symbol):
            existing = await self.store.get("hierarchy_trigger_claims", identity)
            if existing is not None:
                return False, identity
            try:
                await self.store.put("hierarchy_trigger_claims", identity, {"evaluated": True, "published": False, "occurred_at": occurred_at.isoformat()}, expected_version=0)
            except RuntimeError:
                return False, identity
            await self._append_event(LifecycleEvent(
                deterministic_id("event", {"type": "trigger_evaluated", "trigger": identity}),
                LifecycleEventType.TRIGGER_EVALUATED, symbol.upper(), occurred_at, setup_id,
                metadata={"trigger_id": identity},
            ))
            return True, identity

    async def reconstruct(self, symbol: str) -> tuple[dict[str, Any], ...]:
        events = await self.store.read_stream("hierarchy_lifecycle")
        return tuple(event for event in events if event.get("symbol") == symbol.strip().upper())

    async def record_candle_revision(self, *, symbol: str, candle_id: str, previous_hash: str, replacement_hash: str, occurred_at: datetime) -> None:
        await self._append_event(LifecycleEvent(
            deterministic_id("event", {"type": "candle_revised", "candle": candle_id, "replacement_hash": replacement_hash}),
            LifecycleEventType.CANDLE_REVISED, symbol.upper(), occurred_at, None,
            reason="provider_revised_finalized_candle",
            metadata={"candle_id": candle_id, "previous_hash": previous_hash, "replacement_hash": replacement_hash},
        ))

    async def record_shadow_comparison(self, value: dict[str, Any]) -> None:
        if value.get("execution_enabled") is not False:
            raise ValueError("shadow comparison must explicitly disable execution")
        await self.store.append("hierarchy_shadow_comparisons", _json(value))

    async def shadow_comparisons(self, symbol: str | None = None) -> tuple[dict[str, Any], ...]:
        values = await self.store.read_stream("hierarchy_shadow_comparisons")
        return tuple(value for value in values if symbol is None or value.get("symbol") == symbol.strip().upper())

    async def _append_event(self, event: LifecycleEvent) -> None:
        await self.store.append("hierarchy_lifecycle", _json(asdict(event)))
