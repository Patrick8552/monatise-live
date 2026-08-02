from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
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
    PUBLICATION_RECONCILED = "publication_reconciled"


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
                status = existing.value.get("status", "published" if existing.value.get("published") else "pending")
                lease_until = datetime.fromisoformat(existing.value["lease_until"]) if existing.value.get("lease_until") else None
                if status in {"publishing", "delivery_uncertain", "published", "abandoned"} or (status == "pending" and lease_until is not None and occurred_at < lease_until):
                    return False, identity
                attempts = int(existing.value.get("attempts", 1)) + 1
                try:
                    await self.store.put(
                        "hierarchy_trigger_claims",
                        identity,
                        {"status": "pending", "evaluated": True, "published": False, "occurred_at": occurred_at.isoformat(), "lease_until": (occurred_at + timedelta(minutes=2)).isoformat(), "attempts": attempts},
                        expected_version=existing.version,
                    )
                except RuntimeError:
                    return False, identity
                return True, identity
            try:
                await self.store.put(
                    "hierarchy_trigger_claims",
                    identity,
                    {"status": "pending", "evaluated": True, "published": False, "occurred_at": occurred_at.isoformat(), "lease_until": (occurred_at + timedelta(minutes=2)).isoformat(), "attempts": 1},
                    expected_version=0,
                )
            except RuntimeError:
                return False, identity
            await self._append_event(LifecycleEvent(
                deterministic_id("event", {"type": "trigger_evaluated", "trigger": identity}),
                LifecycleEventType.TRIGGER_EVALUATED, symbol.upper(), occurred_at, setup_id,
                metadata={"trigger_id": identity},
            ))
            return True, identity

    async def begin_publication(self, *, symbol: str, trigger_id: str, occurred_at: datetime) -> None:
        """Durably close automatic retries before crossing the Telegram boundary."""
        async with await self.symbol_lock(symbol):
            current = await self.store.get("hierarchy_trigger_claims", trigger_id)
            if current is None or current.value.get("status") != "pending":
                raise RuntimeError("trigger publication claim is not pending")
            value = dict(current.value)
            value.update({
                "status": "publishing",
                "published": False,
                "publication_id": trigger_id,
                "publication_started_at": occurred_at.isoformat(),
                "reconciliation_required_after": (occurred_at + timedelta(minutes=2)).isoformat(),
            })
            value.pop("lease_until", None)
            await self.store.put("hierarchy_trigger_claims", trigger_id, value, expected_version=current.version)

    async def record_publication(self, *, symbol: str, trigger_id: str, occurred_at: datetime, succeeded: bool, error_type: str | None = None, telegram_message_id: int | None = None) -> None:
        async with await self.symbol_lock(symbol):
            current = await self.store.get("hierarchy_trigger_claims", trigger_id)
            if current is None:
                raise RuntimeError("trigger publication claim is unavailable")
            value = dict(current.value)
            value.update({
                # A transport exception may occur after Telegram accepted the
                # request, so failed attempts require reconciliation and must
                # never be retried automatically.
                "status": "published" if succeeded else "delivery_uncertain",
                "published": succeeded,
                "publication_updated_at": occurred_at.isoformat(),
                "error_type": error_type,
                "publication_id": trigger_id,
                "telegram_message_id": telegram_message_id,
            })
            value.pop("lease_until", None)
            if succeeded:
                value.pop("reconciliation_required_after", None)
            await self.store.put("hierarchy_trigger_claims", trigger_id, value, expected_version=current.version)
            await self._append_event(LifecycleEvent(
                deterministic_id("event", {"type": "publication", "trigger": trigger_id, "attempt": value.get("attempts"), "status": value["status"]}),
                LifecycleEventType.PUBLICATION_RECORDED, symbol.upper(), occurred_at, None,
                reason="telegram_delivery_succeeded" if succeeded else "telegram_delivery_uncertain",
                metadata={"trigger_id": trigger_id, "publication_id": trigger_id, "telegram_message_id": telegram_message_id, "status": value["status"], "attempt": value.get("attempts"), "error_type": error_type},
            ))

    async def reconcile_publication(self, *, symbol: str, trigger_id: str, occurred_at: datetime, resolution: str, telegram_message_id: int | None = None, actor: str) -> None:
        """Resolve an ambiguous delivery without making an automatic resend decision."""
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("publication reconciliation time must be timezone-aware")
        normalized_resolution = resolution.strip().casefold()
        if normalized_resolution not in {"delivered", "confirmed_not_delivered", "abandoned"}:
            raise ValueError("unsupported publication reconciliation resolution")
        if not actor.strip():
            raise ValueError("publication reconciliation requires an actor")
        if normalized_resolution == "delivered" and (
            not isinstance(telegram_message_id, int) or isinstance(telegram_message_id, bool) or telegram_message_id <= 0
        ):
            raise ValueError("delivered reconciliation requires a positive Telegram message ID")
        if normalized_resolution != "delivered" and telegram_message_id is not None:
            raise ValueError("only delivered reconciliation accepts a Telegram message ID")
        async with await self.symbol_lock(symbol):
            current = await self.store.get("hierarchy_trigger_claims", trigger_id)
            if current is None:
                raise RuntimeError("trigger publication claim is unavailable")
            current_status = current.value.get("status")
            if current_status not in {"publishing", "delivery_uncertain"}:
                raise RuntimeError("publication is not awaiting reconciliation")
            status = {
                "delivered": "published",
                "confirmed_not_delivered": "failed",
                "abandoned": "abandoned",
            }[normalized_resolution]
            value = dict(current.value)
            value.update({
                "status": status,
                "published": normalized_resolution == "delivered",
                "telegram_message_id": telegram_message_id,
                "reconciliation_resolution": normalized_resolution,
                "reconciled_at": occurred_at.isoformat(),
                "reconciled_by": actor.strip(),
            })
            value.pop("reconciliation_required_after", None)
            await self.store.put("hierarchy_trigger_claims", trigger_id, value, expected_version=current.version)
            await self._append_event(LifecycleEvent(
                deterministic_id("event", {"type": "publication_reconciled", "trigger": trigger_id, "resolution": normalized_resolution}),
                LifecycleEventType.PUBLICATION_RECONCILED, symbol.upper(), occurred_at, None,
                reason=f"telegram_{normalized_resolution}",
                metadata={"trigger_id": trigger_id, "publication_id": trigger_id, "telegram_message_id": telegram_message_id, "status": status, "resolution": normalized_resolution, "actor": actor.strip()},
            ))

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
