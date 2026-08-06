from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from monatise.application.hierarchy import (
    BoundaryStatus,
    CandleBoundaryNormalizer,
    CanonicalEvidenceAdapter,
    DataQualityState,
    EvidenceBundle,
    EvidenceContext,
    EvidenceIdentity,
    HierarchyConfiguration,
    HierarchyLayerEvaluator,
    HierarchyRepository,
    HierarchicalAnalysisRequest,
    Provenance,
    SetupState,
    ShadowComparison,
    ShadowEvaluation,
    ShadowHierarchyCoordinator,
    ShadowHierarchyService,
    StrategicState,
    StructuralRiskInputBuilder,
    TriggerState,
    next_boundary,
)
from monatise.core.models import Candle
from monatise.application.hierarchy.evaluator import LayerAnalysis


NOW = datetime(2026, 8, 2, 12, 0, 20, tzinfo=timezone.utc)
PROVENANCE = Provenance("coinglass", "binance", "BTCUSDT", "v4", "hierarchy-candle-v1")


class MemoryStore:
    def __init__(self):
        self.documents = {}
        self.streams = {}

    async def get(self, namespace, key):
        return self.documents.get((namespace, key))

    async def list_namespace(self, namespace):
        return tuple(record for (item_namespace, _), record in self.documents.items() if item_namespace == namespace)

    async def put(self, namespace, key, value, **kwargs):
        current = self.documents.get((namespace, key))
        actual = current.version if current else 0
        if "expected_version" in kwargs and kwargs["expected_version"] != actual:
            raise RuntimeError("durable state version conflict")
        record = SimpleNamespace(namespace=namespace, key=key, value=value, version=actual + 1)
        self.documents[(namespace, key)] = record
        return record

    async def append(self, stream, value):
        self.streams.setdefault(stream, []).append(value)

    async def read_stream(self, stream):
        return tuple(self.streams.get(stream, ()))


def candle(timestamp="2026-08-02T11:00:00+00:00", close=105.0):
    return Candle(timestamp, 100.0, max(110.0, close), 95.0, close, 1000.0)


def context(timeframe, state, parent=None, *, direction="long", candle_id=None):
    identity = EvidenceIdentity.create(
        kind=timeframe, symbol="BTC", timeframe=timeframe, candle_id=candle_id or f"{timeframe}-candle",
        parent_id=parent.identity.context_id if parent else None, strategy_version="hierarchy-shadow-v1",
    )
    duration = {"4h": timedelta(hours=4), "1h": timedelta(hours=1), "15m": timedelta(minutes=15), "5m": timedelta(minutes=5)}.get(timeframe)
    return EvidenceContext(identity, NOW - duration if duration else None, NOW if duration else None, NOW, NOW + timedelta(hours=4), state, direction, 0.8, DataQualityState.READY, PROVENANCE)


def test_boundary_normalization_requires_close_grace_and_second_observation():
    normalizer = CandleBoundaryNormalizer(grace_seconds=10)
    first = normalizer.normalize(candle(), symbol="BTC", timeframe="1h", received_at=NOW, provenance=PROVENANCE)
    second = normalizer.normalize(candle(), symbol="BTC", timeframe="1h", received_at=NOW, provenance=PROVENANCE, confirmation_observations=2)

    assert first.boundary_status is BoundaryStatus.FORMING
    assert first.is_final is False
    assert second.boundary_status is BoundaryStatus.FINALIZED
    assert second.is_final is True
    assert next_boundary(datetime(2026, 8, 2, 12, 2, tzinfo=timezone.utc), "5m", grace_seconds=10) == datetime(2026, 8, 2, 12, 5, 10, tzinfo=timezone.utc)


def test_evidence_bundle_requires_an_exact_parent_chain_and_disables_execution():
    macro = context("macro", StrategicState.NEUTRAL)
    regime = context("4h", StrategicState.LONG_ONLY, macro)
    strategy = context("1h", StrategicState.LONG_ONLY, regime)
    setup = context("15m", SetupState.SETUP_CONFIRMED, strategy)
    trigger = context("5m", TriggerState.TRIGGER_CONFIRMED, setup)
    risk = StructuralRiskInputBuilder(atr_multiplier=0.1).build(
        direction="long", entry_zone_low=99, entry_zone_high=101, structural_invalidation=97,
        target_liquidity=110, atr=2, movement_tolerance_pct=0.002, expires_at=NOW + timedelta(minutes=15),
    )
    bundle = EvidenceBundle.create(symbol="BTC", created_at=NOW, macro_context=macro, regime_4h=regime, strategy_1h=strategy, setup_15m=setup, trigger_5m=trigger, risk_inputs=risk, strategy_version="hierarchy-shadow-v1")

    assert bundle.execution_enabled is False
    assert bundle.bundle_id.startswith("bundle-")
    with pytest.raises(ValueError, match="parent chain"):
        EvidenceBundle.create(symbol="BTC", created_at=NOW, macro_context=macro, regime_4h=regime, strategy_1h=strategy, setup_15m=setup, trigger_5m=context("5m", TriggerState.TRIGGER_CONFIRMED, strategy), risk_inputs=risk, strategy_version="hierarchy-shadow-v1")


def test_structural_risk_builder_uses_structure_volatility_and_estimated_costs():
    proposal = StructuralRiskInputBuilder(atr_multiplier=0.5).build(
        direction="long", entry_zone_low=99, entry_zone_high=101, structural_invalidation=97,
        target_liquidity=110, atr=2, movement_tolerance_pct=0.002, expires_at=NOW + timedelta(minutes=15),
    )

    assert proposal.reference_entry == 100
    assert proposal.final_stop < 97
    assert proposal.calculated_reward_to_risk > proposal.minimum_reward_to_risk
    assert proposal.estimates_observed is False


def test_hierarchy_short_notification_preserves_directional_risk_geometry():
    macro = context("macro", StrategicState.NEUTRAL, direction="neutral")
    regime = context("4h", StrategicState.SHORT_ONLY, macro, direction="short")
    strategy = context("1h", StrategicState.SHORT_ONLY, regime, direction="short")
    setup = context("15m", SetupState.SETUP_CONFIRMED, strategy, direction="short")
    trigger = context("5m", TriggerState.TRIGGER_CONFIRMED, setup, direction="short")
    risk = StructuralRiskInputBuilder(atr_multiplier=0.1).build(
        direction="short", entry_zone_low=99, entry_zone_high=101, structural_invalidation=103,
        target_liquidity=90, atr=2, movement_tolerance_pct=0.002, expires_at=NOW + timedelta(minutes=15),
    )
    bundle = EvidenceBundle.create(
        symbol="BTC", created_at=NOW, macro_context=macro, regime_4h=regime,
        strategy_1h=strategy, setup_15m=setup, trigger_5m=trigger,
        risk_inputs=risk, strategy_version="hierarchy-shadow-v1",
    )
    evaluation = ShadowEvaluation("BTC", NOW, macro, regime, strategy, setup, trigger, bundle, None, True, ())

    message = ShadowHierarchyService._format_notification(evaluation, publication_id="short-publication", mark_price=100.25, price_observed_at=NOW)

    assert "BTC | SHORT" in message
    assert "Current mark price: 100.25 | source backpack_public | observed 2026-08-02T12:00:20+00:00" in message
    assert f"Entry {risk.reference_entry:.8g}" in message
    assert f"Stop {risk.final_stop:.8g}" in message
    assert f"Target {risk.target_liquidity:.8g}" in message
    assert risk.final_stop > risk.reference_entry > risk.target_liquidity


@pytest.mark.parametrize(("direction", "expected_swing"), (("long", 112.0), ("short", 132.0)))
def test_hierarchy_stop_invalidation_uses_15m_swing(direction, expected_swing):
    candles = tuple(Candle((NOW - timedelta(minutes=20 - index)).isoformat(), 119, 122, 117, 120, 1000) for index in range(20))
    market = SimpleNamespace(price=120.0, candles=candles)
    demand = SimpleNamespace(lower_bound=119.0, upper_bound=121.0)
    supply = SimpleNamespace(lower_bound=119.0, upper_bound=121.0)

    def layer(*, swing_low, swing_high):
        return LayerAnalysis(
            market=market,
            liquidity=SimpleNamespace(nearest_buy_side=SimpleNamespace(price=145.0), nearest_sell_side=SimpleNamespace(price=95.0)),
            sweep=SimpleNamespace(),
            zones=SimpleNamespace(active_demand=demand, nearest_demand=demand, active_supply=supply, nearest_supply=supply),
            reclaim=SimpleNamespace(),
            structure=SimpleNamespace(swing_lows=((1, swing_low),), swing_highs=((1, swing_high),)),
        )

    trigger_layer = layer(swing_low=115.0, swing_high=130.0)
    entry_layer = layer(swing_low=118.0, swing_high=122.0)
    setup_15m_layer = layer(swing_low=112.0, swing_high=132.0)
    trigger = context("5m", TriggerState.TRIGGER_CONFIRMED, direction=direction)
    evaluator = HierarchyLayerEvaluator(risk_builder=StructuralRiskInputBuilder(atr_multiplier=0.1))

    proposal = evaluator._risk(trigger_layer, trigger, NOW, entry_layer=entry_layer, stop_layer=setup_15m_layer)

    assert proposal.structural_invalidation == expected_swing
    assert proposal.final_stop < expected_swing if direction == "long" else proposal.final_stop > expected_swing


def test_repository_is_append_only_and_trigger_claim_is_idempotent():
    async def scenario():
        store = MemoryStore()
        repository = HierarchyRepository(store)
        macro = context("macro", StrategicState.NEUTRAL)
        replacement = EvidenceContext(
            EvidenceIdentity.create(kind="macro", symbol="BTC", timeframe="macro", candle_id="macro-v2", parent_id=None, strategy_version="hierarchy-shadow-v1"),
            None, None, NOW + timedelta(minutes=1), NOW + timedelta(hours=4), StrategicState.LONG_ONLY, "long", 0.9, DataQualityState.READY, PROVENANCE,
        )
        assert await repository.append_context(macro, expected_current_version=0) == 1
        assert await repository.append_context(replacement, expected_current_version=1) == 2
        first = await repository.claim_trigger(symbol="BTC", candle_close_time=NOW, setup_id="setup-1", direction="long", trigger_type="reclaim", strategy_version="v1", occurred_at=NOW)
        second = await repository.claim_trigger(symbol="BTC", candle_close_time=NOW, setup_id="setup-1", direction="long", trigger_type="reclaim", strategy_version="v1", occurred_at=NOW)
        assert first[0] is True and second == (False, first[1])
        await repository.begin_publication(symbol="BTC", trigger_id=first[1], occurred_at=NOW)
        await repository.record_publication(symbol="BTC", trigger_id=first[1], occurred_at=NOW, succeeded=False, error_type="TimeoutError")
        retry = await repository.claim_trigger(symbol="BTC", candle_close_time=NOW, setup_id="setup-1", direction="long", trigger_type="reclaim", strategy_version="v1", occurred_at=NOW)
        assert retry == (False, first[1])
        current = await store.get("hierarchy_trigger_claims", first[1])
        assert current.value["status"] == "delivery_uncertain"
        assert current.value["reconciliation_required_after"] == (NOW + timedelta(minutes=2)).isoformat()
        published_duplicate = await repository.claim_trigger(symbol="BTC", candle_close_time=NOW, setup_id="setup-1", direction="long", trigger_type="reclaim", strategy_version="v1", occurred_at=NOW)
        assert published_duplicate == (False, first[1])
        await repository.reconcile_publication(
            symbol="BTC", trigger_id=first[1], occurred_at=NOW + timedelta(minutes=3),
            resolution="confirmed_not_delivered", actor="operator:test",
        )
        retry_after_reconciliation = await repository.claim_trigger(symbol="BTC", candle_close_time=NOW, setup_id="setup-1", direction="long", trigger_type="reclaim", strategy_version="v1", occurred_at=NOW + timedelta(minutes=3))
        assert retry_after_reconciliation == (True, first[1])
        events = await repository.reconstruct("BTC")
        assert [event["event_type"] for event in events].count("context_superseded") == 1
        assert [event["event_type"] for event in events].count("trigger_evaluated") == 1
        assert [event["event_type"] for event in events].count("publication_recorded") == 1
        assert [event["event_type"] for event in events].count("publication_reconciled") == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("resolution,telegram_message_id,expected_status", [
    ("delivered", 731, "published"),
    ("abandoned", None, "abandoned"),
])
def test_publication_reconciliation_blocks_unsafe_retries(resolution, telegram_message_id, expected_status):
    async def scenario():
        store = MemoryStore()
        repository = HierarchyRepository(store)
        claimed, trigger_id = await repository.claim_trigger(
            symbol="BTC", candle_close_time=NOW, setup_id="setup-reconcile", direction="long",
            trigger_type="reclaim", strategy_version="v1", occurred_at=NOW,
        )
        assert claimed is True
        await repository.begin_publication(symbol="BTC", trigger_id=trigger_id, occurred_at=NOW)
        await repository.reconcile_publication(
            symbol="BTC", trigger_id=trigger_id, occurred_at=NOW + timedelta(minutes=3),
            resolution=resolution, telegram_message_id=telegram_message_id, actor="operator:test",
        )
        record = await store.get("hierarchy_trigger_claims", trigger_id)
        assert record.value["status"] == expected_status
        assert record.value["reconciled_by"] == "operator:test"
        retry = await repository.claim_trigger(
            symbol="BTC", candle_close_time=NOW, setup_id="setup-reconcile", direction="long",
            trigger_type="reclaim", strategy_version="v1", occurred_at=NOW + timedelta(minutes=4),
        )
        assert retry == (False, trigger_id)

    asyncio.run(scenario())


def test_stale_publications_are_flagged_for_operator_reconciliation_without_retry():
    async def scenario():
        store = MemoryStore()
        repository = HierarchyRepository(store)
        claimed, trigger_id = await repository.claim_trigger(
            symbol="BTC", candle_close_time=NOW, setup_id="setup-stale", direction="long",
            trigger_type="reclaim", strategy_version="v1", occurred_at=NOW,
        )
        assert claimed is True
        await repository.begin_publication(symbol="BTC", trigger_id=trigger_id, occurred_at=NOW)
        assert await repository.flag_stale_publications(occurred_at=NOW + timedelta(minutes=1)) == ()
        assert await repository.flag_stale_publications(occurred_at=NOW + timedelta(minutes=2)) == (trigger_id,)
        assert await repository.flag_stale_publications(occurred_at=NOW + timedelta(minutes=3)) == ()
        record = await store.get("hierarchy_trigger_claims", trigger_id)
        assert record.value["status"] == "reconciliation_required"
        retry = await repository.claim_trigger(
            symbol="BTC", candle_close_time=NOW, setup_id="setup-stale", direction="long",
            trigger_type="reclaim", strategy_version="v1", occurred_at=NOW + timedelta(minutes=3),
        )
        assert retry == (False, trigger_id)
        events = await repository.reconstruct("BTC")
        assert [event["event_type"] for event in events].count("publication_reconciliation_required") == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("occurred_at,resolution,message_id", [
    (NOW.replace(tzinfo=None), "delivered", 731),
    (NOW, "delivered", True),
    (NOW, "delivered", 0),
    (NOW, "abandoned", 731),
])
def test_invalid_publication_reconciliation_cannot_mutate_state(occurred_at, resolution, message_id):
    async def scenario():
        store = MemoryStore()
        repository = HierarchyRepository(store)
        claimed, trigger_id = await repository.claim_trigger(
            symbol="BTC", candle_close_time=NOW, setup_id="setup-invalid", direction="long",
            trigger_type="reclaim", strategy_version="v1", occurred_at=NOW,
        )
        assert claimed is True
        await repository.begin_publication(symbol="BTC", trigger_id=trigger_id, occurred_at=NOW)
        before = await store.get("hierarchy_trigger_claims", trigger_id)
        with pytest.raises(ValueError):
            await repository.reconcile_publication(
                symbol="BTC", trigger_id=trigger_id, occurred_at=occurred_at,
                resolution=resolution, telegram_message_id=message_id, actor="operator:test",
            )
        after = await store.get("hierarchy_trigger_claims", trigger_id)
        assert after.version == before.version
        assert after.value == before.value

    asyncio.run(scenario())


def test_shadow_coordinator_waits_for_confirmed_candles_and_records_revisions():
    class Provider:
        revised = False
        def candles(self, symbol, limit, interval="1h"):
            close = 106 if self.revised and interval == "5m" else 105
            return [candle("2026-08-02T04:00:00+00:00", close)]

    async def scenario():
        store = MemoryStore()
        provider = Provider()
        coordinator = ShadowHierarchyCoordinator(
            provider, HierarchyRepository(store),
            configuration=HierarchyConfiguration(enabled=True), provenance=PROVENANCE,
        )
        first = await coordinator.collect("BTC", observed_at=NOW)
        assert all(snapshot.latest_finalized is None for snapshot in first.values())
        second = await coordinator.collect("BTC", observed_at=NOW + timedelta(seconds=1))
        assert all(snapshot.latest_finalized is not None for snapshot in second.values())
        provider.revised = True
        third = await coordinator.collect("BTC", observed_at=NOW + timedelta(seconds=2))
        assert third["5m"].revisions
        events = await coordinator.repository.reconstruct("BTC")
        assert any(event["event_type"] == "candle_revised" for event in events)
        assert coordinator.execution_enabled is False

    asyncio.run(scenario())


def test_shadow_configuration_can_enable_notifications_without_execution():
    configuration = HierarchyConfiguration(enabled=True, telegram_publish_enabled=True)
    assert configuration.telegram_publish_enabled is True


def test_environment_configuration_is_disabled_by_default_and_allows_notification_only_publication():
    assert HierarchyConfiguration.from_environment({}).enabled is False
    configured = HierarchyConfiguration.from_environment({
        "MONATISE_HIERARCHICAL_SHADOW_ENABLED": "true",
        "MONATISE_HIERARCHICAL_STRATEGY_VERSION": "v2",
    })
    assert configured.enabled is True and configured.strategy_version == "v2"
    publish = HierarchyConfiguration.from_environment({"MONATISE_HIERARCHICAL_TELEGRAM_PUBLISH_ENABLED": "true"})
    assert publish.telegram_publish_enabled is True


def test_canonical_adapter_blocks_stale_or_low_reward_evidence_and_bridges_risk_values():
    macro = context("macro", StrategicState.NEUTRAL)
    regime = context("4h", StrategicState.LONG_ONLY, macro)
    strategy = context("1h", StrategicState.LONG_ONLY, regime)
    setup = context("15m", SetupState.SETUP_CONFIRMED, strategy)
    trigger = context("5m", TriggerState.TRIGGER_CONFIRMED, setup)
    risk = StructuralRiskInputBuilder(atr_multiplier=0.1).build(
        direction="long", entry_zone_low=99, entry_zone_high=101, structural_invalidation=97,
        target_liquidity=110, atr=2, movement_tolerance_pct=0.002, expires_at=NOW + timedelta(minutes=15),
    )
    bundle = EvidenceBundle.create(symbol="BTC", created_at=NOW, macro_context=macro, regime_4h=regime, strategy_1h=strategy, setup_15m=setup, trigger_5m=trigger, risk_inputs=risk, strategy_version="hierarchy-shadow-v1")
    adapter = CanonicalEvidenceAdapter()
    validation = adapter.validate(HierarchicalAnalysisRequest("BTC", bundle, NOW + timedelta(seconds=1)))
    values = adapter.risk_request_values(bundle)

    assert validation.eligible_for_shadow_decision is True
    assert validation.outcome.value == "valid_signal"
    assert values["proposed_entry"] == 100
    expired = adapter.validate(HierarchicalAnalysisRequest("BTC", bundle, NOW + timedelta(hours=5)))
    assert expired.outcome.value == "expired"


def test_boundary_due_collection_sleeps_5m_until_watching_and_persists_metrics():
    class Provider:
        def __init__(self): self.calls = []
        def candles(self, symbol, limit, interval="1h"):
            self.calls.append(interval)
            return [candle("2026-08-02T04:00:00+00:00")]

    async def scenario():
        store = MemoryStore()
        provider = Provider()
        coordinator = ShadowHierarchyCoordinator(provider, HierarchyRepository(store), configuration=HierarchyConfiguration(enabled=True), provenance=PROVENANCE)
        first = await coordinator.collect_due("BTC", watching=False, observed_at=NOW)
        assert tuple(first) == ("4h", "1h", "15m")
        assert provider.calls == ["4h", "1h", "15m"]
        confirmed = await coordinator.collect_due("BTC", watching=False, observed_at=NOW + timedelta(seconds=5))
        assert tuple(confirmed) == ("4h", "1h", "15m")
        assert await coordinator.collect_due("BTC", watching=False, observed_at=NOW + timedelta(seconds=10)) == {}
        watching = await coordinator.collect_due("BTC", watching=True, observed_at=NOW + timedelta(seconds=10))
        assert tuple(watching) == ("5m", "1m")
        comparison = ShadowComparison("BTC", NOW, "blocked", "no_trade", forming_candle_blocked=True)
        await coordinator.record_comparison(comparison)
        stored = await coordinator.repository.shadow_comparisons("BTC")
        assert stored[0]["execution_enabled"] is False
        assert stored[0]["forming_candle_blocked"] is True

    asyncio.run(scenario())


def test_boundary_due_collection_can_include_5m_on_every_confluence_cycle():
    class Provider:
        def candles(self, symbol, limit, interval="1h"):
            return [candle("2026-08-02T04:00:00+00:00")]

    async def scenario():
        coordinator = ShadowHierarchyCoordinator(
            Provider(),
            HierarchyRepository(MemoryStore()),
            configuration=HierarchyConfiguration(enabled=True, always_collect_5m=True),
            provenance=PROVENANCE,
        )
        snapshots = await coordinator.collect_due("BTC", watching=False, observed_at=NOW)
        assert tuple(snapshots) == ("4h", "1h", "15m", "5m", "1m")

    asyncio.run(scenario())


def test_real_layer_evaluator_builds_4h_1h_and_15m_evidence_without_publication():
    durations = {"4h": timedelta(hours=4), "1h": timedelta(hours=1), "15m": timedelta(minutes=15), "5m": timedelta(minutes=5), "1m": timedelta(minutes=1)}

    def candles_for(timeframe):
        duration = durations[timeframe]
        start = NOW - duration * 80
        values = []
        for index in range(70):
            base = 100 + index * 0.4
            values.append(Candle((start + duration * index).isoformat(), base, base + 1.2, base - 0.8, base + 0.6, 1000 + index))
        return values

    normalizer = CandleBoundaryNormalizer()
    snapshots = {}
    for timeframe in durations:
        normalized = tuple(normalizer.normalize(item, symbol="BTC", timeframe=timeframe, received_at=NOW, provenance=PROVENANCE, confirmation_observations=2) for item in candles_for(timeframe))
        finalized = tuple(item for item in normalized if item.is_final)
        snapshots[timeframe] = SimpleNamespace(symbol="BTC", timeframe=timeframe, observed_at=NOW, candles=normalized, latest_finalized=finalized[-1], revisions=())

    evaluator = HierarchyLayerEvaluator(configuration=HierarchyConfiguration(enabled=True))
    result = evaluator.evaluate("BTC", snapshots, evaluated_at=NOW, macro_degraded=True)

    assert result.macro_context is not None
    assert result.regime_4h is not None
    assert result.strategy_1h is not None
    assert result.setup_15m is not None
    assert result.execution_enabled is False
    assert result.bundle is None or result.bundle.execution_enabled is False


def test_shadow_service_persists_layer_evidence_and_never_publishes():
    duration = {"4h": timedelta(hours=4), "1h": timedelta(hours=1), "15m": timedelta(minutes=15), "5m": timedelta(minutes=5)}

    class Provider:
        def candles(self, symbol, limit, interval="1h"):
            start = NOW - duration[interval] * 80
            return [Candle((start + duration[interval] * index).isoformat(), 100 + index * 0.3, 101 + index * 0.3, 99 + index * 0.3, 100.5 + index * 0.3, 1000 + index) for index in range(70)]

    async def scenario():
        store = MemoryStore()
        repository = HierarchyRepository(store)
        configuration = HierarchyConfiguration(enabled=True)
        coordinator = ShadowHierarchyCoordinator(Provider(), repository, configuration=configuration, provenance=PROVENANCE)
        service = ShadowHierarchyService(coordinator, HierarchyLayerEvaluator(configuration=configuration), repository)
        first = await service.tick("BTC", observed_at=NOW)
        second = await service.tick("BTC", observed_at=NOW + timedelta(seconds=5))

        assert first["telegram_publish_enabled"] is False and first["execution_enabled"] is False
        assert second["telegram_publish_enabled"] is False and second["execution_enabled"] is False
        assert second["setup_state"] is not None
        events = await repository.reconstruct("BTC")
        assert any(event["event_type"] == "context_created" for event in events)
        comparisons = await repository.shadow_comparisons("BTC")
        assert comparisons and all(item["execution_enabled"] is False for item in comparisons)

    asyncio.run(scenario())


def test_confirmed_hierarchy_produces_valid_shadow_bundle_and_risk_bridge():
    durations = {"4h": timedelta(hours=4), "1h": timedelta(hours=1), "15m": timedelta(minutes=15), "5m": timedelta(minutes=5), "1m": timedelta(minutes=1)}
    normalizer = CandleBoundaryNormalizer()
    snapshots = {}
    for timeframe, duration in durations.items():
        raw = [Candle((NOW - duration * (30 - index)).isoformat(), 119 + index * 0.03, 121 + index * 0.03, 117 + index * 0.03, 120 + index * 0.03, 1000) for index in range(20)]
        normalized = tuple(normalizer.normalize(item, symbol="BTC", timeframe=timeframe, received_at=NOW, provenance=PROVENANCE, confirmation_observations=2) for item in raw)
        finalized = tuple(item for item in normalized if item.is_final)
        snapshots[timeframe] = SimpleNamespace(symbol="BTC", timeframe=timeframe, observed_at=NOW, candles=normalized, latest_finalized=finalized[-1], revisions=())

    market_candles = tuple(Candle((NOW - timedelta(minutes=5 * (20 - index))).isoformat(), 119, 122, 117, 120, 1000) for index in range(20))
    market = SimpleNamespace(price=120.0, candles=market_candles)
    level = SimpleNamespace(price=140.0)
    zone = SimpleNamespace(lower_bound=119.0, upper_bound=121.0)
    layer = LayerAnalysis(
        market=market,
        liquidity=SimpleNamespace(balanced=True, nearest_buy_side=level, nearest_sell_side=SimpleNamespace(price=100.0)),
        sweep=SimpleNamespace(has_confirmed_sweep=True, has_possible_sweep=False),
        zones=SimpleNamespace(price_inside_zone=True, active_demand=zone, nearest_demand=zone, active_supply=None, nearest_supply=None),
        reclaim=SimpleNamespace(has_confirmed_reclaim=True),
        structure=SimpleNamespace(
            bias=__import__("monatise.engines.market_structure.models", fromlist=["StructureBias"]).StructureBias.BULLISH,
            state=SimpleNamespace(value="bullish_continuation"), confidence=0.9,
            has_confirmed_break=True, swing_lows=((1, 115.0),), swing_highs=((2, 130.0),), metadata={},
        ),
    )
    evaluator = HierarchyLayerEvaluator(configuration=HierarchyConfiguration(enabled=True), risk_builder=StructuralRiskInputBuilder(atr_multiplier=0.1))
    evaluator.regime_engine = SimpleNamespace(assess=lambda request: SimpleNamespace(state=__import__("monatise.engines.regime.models", fromlist=["RegimeState"]).RegimeState.TREND_UP, confidence=SimpleNamespace(value="high"), score=0.9, reasons=()))
    evaluator._analyse_structure = lambda snapshot, regime: layer

    result = evaluator.evaluate("BTC", snapshots, evaluated_at=NOW, macro_degraded=True)

    assert result.setup_15m.state is SetupState.SETUP_CONFIRMED
    assert result.trigger_5m.state is TriggerState.TRIGGER_CONFIRMED
    assert result.bundle is not None
    assert result.validation is not None and result.validation.eligible_for_shadow_decision is True
    assert result.bundle.risk_inputs.reference_entry == 120
    assert result.bundle.risk_inputs.structural_invalidation == 115
    assert result.execution_enabled is False
    message = ShadowHierarchyService._format_notification(result, publication_id="publication-123456789")
    assert "Expires 2026-08-02 12:15:20 UTC" in message
    assert "Valid for 15 min" in message
    assert "Publication publication-1234" in message

    async def publication_scenario():
        store = MemoryStore()
        repository = HierarchyRepository(store)

        class Coordinator:
            configuration = HierarchyConfiguration(enabled=True, telegram_publish_enabled=True)

            async def collect_due(self, symbol, *, watching, observed_at):
                return {"5m": snapshots["5m"]}

            async def claim_closed_trigger(self, *, trigger, setup_id, trigger_type):
                return await repository.claim_trigger(
                    symbol=trigger.identity.symbol,
                    candle_close_time=trigger.source_close_time,
                    setup_id=setup_id,
                    direction=trigger.direction,
                    trigger_type=trigger_type,
                    strategy_version=trigger.identity.strategy_version,
                    occurred_at=trigger.evaluated_at,
                )

            async def record_comparison(self, comparison):
                await repository.record_shadow_comparison(__import__("dataclasses").asdict(comparison))

        class Evaluator:
            def watching(self, symbol): return True
            def evaluate(self, symbol, current, *, evaluated_at, macro_degraded): return result

        attempts = []

        async def publisher(text):
            attempts.append(text)
            if len(attempts) == 1:
                raise TimeoutError("temporary Telegram failure")
            return 987654

        service = ShadowHierarchyService(Coordinator(), Evaluator(), repository, publisher=publisher)
        failed = await service.tick("BTC", observed_at=NOW)
        retried = await service.tick("BTC", observed_at=NOW + timedelta(seconds=1))

        assert failed["telegram_publication_failed"] is True
        assert retried["duplicate_blocked"] is True
        assert retried["telegram_published"] is False
        assert len(attempts) == 1

    asyncio.run(publication_scenario())

    old_setup_id = result.setup_15m.identity.context_id
    refreshed = evaluator.evaluate("BTC", {"4h": snapshots["4h"]}, evaluated_at=NOW + timedelta(minutes=16), macro_degraded=True)
    assert refreshed.setup_15m.identity.context_id != old_setup_id
    assert refreshed.setup_15m.identity.parent_context_id == refreshed.strategy_1h.identity.context_id
    assert refreshed.trigger_5m is None
