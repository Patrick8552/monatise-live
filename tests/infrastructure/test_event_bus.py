import asyncio

from monatise.infrastructure.event_bus.bus import EventBus
from monatise.infrastructure.event_bus.models import (
    DeliveryMode,
    DomainEvent,
)
from monatise.infrastructure.event_bus.store import InMemoryEventStore


def test_publish_and_subscribe() -> None:
    async def run() -> None:
        received = []

        async def handler(envelope):
            received.append(envelope.event.payload["value"])

        bus = EventBus()
        bus.subscribe("engine.completed", handler)

        result = await bus.publish(
            DomainEvent(
                event_type="engine.completed",
                payload={"value": 42},
                source="market_data_engine",
                symbol="BTCUSDT",
            )
        )

        assert result.successful is True
        assert result.persisted is True
        assert result.duplicate is False
        assert received == [42]

    asyncio.run(run())


def test_idempotency_prevents_duplicate_delivery() -> None:
    async def run() -> None:
        calls = 0

        async def handler(_):
            nonlocal calls
            calls += 1

        bus = EventBus()
        bus.subscribe("decision.completed", handler)

        event = DomainEvent(
            event_type="decision.completed",
            payload={"classification": "trend"},
            source="decision_engine",
            symbol="BTCUSDT",
        )

        first = await bus.publish(event, idempotency_key="fixed-key")
        second = await bus.publish(event, idempotency_key="fixed-key")

        assert first.duplicate is False
        assert second.duplicate is True
        assert calls == 1

    asyncio.run(run())


def test_at_least_once_retries_failed_handler() -> None:
    async def run() -> None:
        attempts = 0

        async def flaky(_):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("temporary failure")

        bus = EventBus(
            delivery_mode=DeliveryMode.AT_LEAST_ONCE,
            max_attempts=3,
            retry_delay_seconds=0,
        )
        bus.subscribe("report.ready", flaky)

        result = await bus.publish(
            DomainEvent(
                event_type="report.ready",
                payload={},
                source="reporting_engine",
            )
        )

        assert result.successful is True
        assert result.handler_results[0].attempt == 3
        assert attempts == 3

    asyncio.run(run())


def test_at_most_once_does_not_retry() -> None:
    async def run() -> None:
        attempts = 0

        async def failing(_):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("failure")

        bus = EventBus(
            delivery_mode=DeliveryMode.AT_MOST_ONCE,
            max_attempts=5,
            retry_delay_seconds=0,
        )
        bus.subscribe("integration.failed", failing)

        result = await bus.publish(
            DomainEvent(
                event_type="integration.failed",
                payload={},
                source="integration_engine",
            )
        )

        assert result.successful is False
        assert result.handler_results[0].attempt == 1
        assert attempts == 1

    asyncio.run(run())


def test_event_store_can_query_by_type() -> None:
    async def run() -> None:
        bus = EventBus()

        await bus.publish(
            DomainEvent(
                event_type="engine.completed",
                payload={"engine": "macro"},
                source="macro_engine",
            )
        )
        await bus.publish(
            DomainEvent(
                event_type="engine.completed",
                payload={"engine": "regime"},
                source="regime_engine",
            )
        )

        events = await bus.store.by_event_type("engine.completed")
        assert len(events) == 2

    asyncio.run(run())


def test_event_bus_is_non_executable() -> None:
    bus = EventBus()

    assert not hasattr(bus, "place_order")
    assert not hasattr(bus, "submit_trade")


def test_event_store_is_replaceable() -> None:
    async def run() -> None:
        class RecordingStore(InMemoryEventStore):
            append_calls = 0

            async def append(self, envelope):
                self.append_calls += 1
                return await super().append(envelope)

        store = RecordingStore()
        bus = EventBus(store=store)
        await bus.publish(
            DomainEvent(
                event_type="risk.validated",
                payload={"decision": "approved"},
                source="risk_validation_engine",
            )
        )

        assert store.append_calls == 1
        assert bus.store is store

    asyncio.run(run())


def test_persisted_event_is_isolated_from_publishers_and_handlers() -> None:
    async def run() -> None:
        payload = {"nested": {"value": 1}}

        async def mutating_handler(envelope):
            envelope.event.payload["nested"]["value"] = 999

        bus = EventBus()
        bus.subscribe("state.changed", mutating_handler)
        await bus.publish(DomainEvent(
            event_type="state.changed",
            payload=payload,
            source="state_manager",
        ))
        payload["nested"]["value"] = 500

        stored = await bus.store.all()
        assert stored[0].event.payload["nested"]["value"] == 1
        stored[0].event.payload["nested"]["value"] = 200
        reloaded = await bus.store.all()
        assert reloaded[0].event.payload["nested"]["value"] == 1

    asyncio.run(run())
