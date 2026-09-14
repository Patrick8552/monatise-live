from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from monatise.application.ftmo_registry import FTMO_REGISTRY
from monatise.application.hierarchy.policy import (
    SHARED_TIMEFRAME_POLICY as POLICY,
    timeframe_policy,
)
from monatise.application.hierarchy.assets import (
    AssetHierarchyAnalysis,
    alpaca_timeframe,
    _candles,
)
from monatise.application.hierarchy.broker_candles import BrokerCandleService, DEMANDS
from monatise.application.hierarchy.approval import validate_shared_evidence, CURRENT
from monatise.application.hierarchy import (
    HierarchyConfiguration,
    HierarchyLayerEvaluator,
    ShadowHierarchyCoordinator,
    HierarchyRepository,
    Provenance,
)
from tests.test_application_hierarchy import MemoryStore
from tests.test_ftmo_master import service, active_environment, heartbeat
from tests.shared_hierarchy_fixtures import persist_proof

NOW = datetime(2026, 9, 14, 16, 0, 20, tzinfo=timezone.utc)
DURATIONS = {"4h": 14400, "1h": 3600, "15m": 900, "5m": 300, "1m": 60}


def rows(tf, now=NOW):
    step = DURATIONS[tf]
    boundary = datetime.fromtimestamp(int(now.timestamp()) // step * step, timezone.utc)
    result = []
    for i in range(100):
        price = 100 + i * 0.4
        result.append(
            {
                "t": (boundary - timedelta(seconds=step * (100 - i))).isoformat(),
                "o": price,
                "h": price + 1.2,
                "l": price - 0.8,
                "c": price + 0.6,
                "v": 1000 + i,
            }
        )
    return result


class Alpaca:
    feed = "iex"

    def __init__(self, *, closed=False, early_close=None, mutation=None):
        self.calls, self.closed, self.early_close, self.mutation = (
            [],
            closed,
            early_close,
            mutation,
        )

    def market_calendar(self, day):
        return (
            []
            if self.closed
            else [{"date": day, "open": "09:30", "close": self.early_close or "16:00"}]
        )

    def stock_bars(self, symbol, timeframe, limit):
        self.calls.append((symbol, timeframe, limit))
        tf = {"4Hour": "4h", "1Hour": "1h", "15Min": "15m", "5Min": "5m", "1Min": "1m"}[
            timeframe
        ]
        data = rows(tf)
        if tf == "1m" and self.mutation == "stale":
            for row in data:
                row["t"] = (
                    datetime.fromisoformat(row["t"]) - timedelta(hours=1)
                ).isoformat()
        return data


def test_crypto_stock_and_index_share_one_immutable_policy():
    for asset in ("crypto", "stock", "indices"):
        p = timeframe_policy(asset)
        assert p is POLICY
        assert (p.analysis, p.setup, p.confirmation, p.trigger, p.entry) == (
            "1h",
            "15m",
            "5m",
            "5m",
            "1m",
        )
        assert p.timeframes == ("4h", "1h", "15m", "5m", "1m")
    with pytest.raises(FrozenInstanceError):
        POLICY.analysis = "15m"
    assert [alpaca_timeframe(tf) for tf in POLICY.timeframes] == [
        "4Hour",
        "1Hour",
        "15Min",
        "5Min",
        "1Min",
    ]


def test_actual_evaluator_produces_same_states_and_expiry_for_all_assets():
    async def scenario():
        values = []
        for symbol, route in (
            ("BTC", "crypto"),
            ("AAPL", "stocks"),
            ("US100.cash", "indices"),
        ):

            class Provider:
                def candles(self, requested, limit, interval):
                    return _candles(rows(interval), interval, NOW)

            coordinator = ShadowHierarchyCoordinator(
                Provider(),
                HierarchyRepository(MemoryStore()),
                configuration=HierarchyConfiguration(enabled=True),
                provenance=Provenance("test", "test", symbol, "v1", "v1"),
            )
            await coordinator.collect(symbol, observed_at=NOW)
            snapshots = await coordinator.collect(
                symbol, observed_at=NOW + timedelta(seconds=1)
            )
            evaluator = HierarchyLayerEvaluator(asset_route=route)
            result = evaluator.evaluate(
                symbol,
                snapshots,
                evaluated_at=NOW + timedelta(seconds=1),
                macro_degraded=True,
            )
            contexts = (result.regime_4h, result.strategy_1h, result.setup_15m)
            values.append(
                [
                    (
                        c.identity.source_timeframe,
                        c.direction,
                        c.state,
                        c.expires_at - c.evaluated_at,
                    )
                    for c in contexts
                ]
            )
            assert result.execution_enabled is False
        assert values[0] == values[1] == values[2]
        assert [row[3] for row in values[0]] == [
            timedelta(hours=5),
            timedelta(hours=2),
            timedelta(minutes=45),
        ]

    asyncio.run(scenario())


def test_stock_analysis_fetches_all_crypto_layers_and_requires_second_observation():
    async def scenario():
        alpaca = Alpaca()
        analysis = AssetHierarchyAnalysis(alpaca=alpaca)
        instrument = FTMO_REGISTRY.resolve("AAPL")
        first = await analysis.analyse(instrument, now=NOW)
        assert first["publication_valid"] is False
        second = await analysis.analyse(instrument, now=NOW + timedelta(seconds=6))
        assert (
            second["analysis_timeframe"] == "1h" and second["trigger_timeframe"] == "5m"
        )
        assert second["entry_timeframe"] == "1m"
        assert {call[1] for call in alpaca.calls} == {
            "4Hour",
            "1Hour",
            "15Min",
            "5Min",
            "1Min",
        }
        assert second["market_structure"]["structure_bias"]
        assert second["fibonacci"].keys() >= {"4h", "1h", "15m"}
        assert second["order_flow"]["evaluation_timeframe"] == "1h"
        assert second["order_flow"]["inputs_used"] == 0  # Never invent CVD from gamma.

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"closed": True}, "stock_exchange_closed"),
        ({"early_close": "11:00"}, "stock_regular_session_closed"),
        ({"mutation": "stale"}, "1m_candles_stale"),
    ],
)
def test_stock_holidays_early_closes_and_stale_lower_layers_fail_closed(
    options, reason
):
    result = asyncio.run(
        AssetHierarchyAnalysis(alpaca=Alpaca(**options)).analyse(
            FTMO_REGISTRY.resolve("AAPL"), now=NOW
        )
    )
    assert (
        not result["publication_valid"]
        and result["decision"] == "INSUFFICIENT_MARKET_DATA"
    )
    assert reason in result["reason_code"]


@pytest.mark.parametrize("mutation", ["missing", "future", "duplicate", "nan", "bool"])
def test_invalid_candles_cannot_become_shared_evidence(mutation):
    data = rows("1m")
    if mutation == "missing":
        data = data[:20]
    elif mutation == "future":
        data[-1]["t"] = (NOW + timedelta(minutes=5)).isoformat()
    elif mutation == "duplicate":
        data[-1]["t"] = data[-2]["t"]
    elif mutation == "nan":
        data[-1]["c"] = float("nan")
    else:
        data[-1]["v"] = True
    with pytest.raises(ValueError):
        _candles(data, "1m", NOW)


@pytest.mark.parametrize(
    "mutation", ["account", "symbol", "expired", "missing_layer", "replay", "future"]
)
def test_broker_history_is_request_bound_and_fails_closed(mutation):
    async def scenario():
        control, store = service(active_environment())
        await control.accept_bridge_heartbeat(heartbeat(history_version=1), now=NOW)
        transport = BrokerCandleService(control)
        request_id = "1" * 32
        await store.put(
            DEMANDS,
            request_id,
            {
                "request_id": request_id,
                "symbol": "US100.cash",
                "limit": 200,
                "state": "pending",
                "account_id": control.configuration.account_id,
                "server": control.configuration.server,
                "requested_at": NOW.isoformat(),
                "expires_at": (NOW + timedelta(seconds=30)).isoformat(),
            },
        )
        payload = {
            "request_id": request_id,
            "symbol": "US100.cash",
            "account_id": control.configuration.account_id,
            "server": control.configuration.server,
            "captured_at": NOW.isoformat(),
            "timeframes": {tf: rows(tf) for tf in DURATIONS},
            "trade_mode": "4",
            "session_open": True,
            "session_close": (NOW + timedelta(hours=4)).isoformat(),
        }
        if mutation == "account":
            payload["account_id"] = "another-account"
        elif mutation == "symbol":
            payload["symbol"] = "US500.cash"
        elif mutation == "expired":
            record = await store.get(DEMANDS, request_id)
            record.value["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
        elif mutation == "missing_layer":
            del payload["timeframes"]["1m"]
        elif mutation == "future":
            payload["captured_at"] = (NOW + timedelta(seconds=1)).isoformat()
        elif mutation == "replay":
            assert (await transport.accept(payload, NOW))["execution_enabled"] is False
        with pytest.raises(ValueError):
            await transport.accept(payload, NOW)
        assert await control.repository.pending_commands() == ()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mutation",
    ["missing", "policy", "parent", "expiry", "invalidation", "changed_stop"],
)
def test_approval_requires_durable_current_hierarchy(mutation):
    async def scenario():
        control, store = service(active_environment())
        instrument = FTMO_REGISTRY.resolve("US100.cash")
        envelope = await persist_proof(control, instrument.ftmo_symbol, NOW)
        assert await validate_shared_evidence(store, instrument, envelope, NOW)
        when = NOW
        if mutation == "missing":
            envelope = {}
        elif mutation == "policy":
            envelope["evidence_bundle"]["trigger_timeframe"] = "15m"
        elif mutation == "parent":
            envelope["evidence_bundle"]["contexts"][-1]["parent_context_id"] = "wrong"
        elif mutation == "expiry":
            when = NOW + timedelta(minutes=15)
        elif mutation == "invalidation":
            await store.put(CURRENT, instrument.ftmo_symbol, {"state": "invalidated"})
        else:
            await control.accept_bridge_heartbeat(
                heartbeat(quotes={"US100.cash": heartbeat()["quotes"]["XAUUSD"]}),
                now=NOW,
            )
            await control.repository.update_control(kill_switch=False)
            with pytest.raises(Exception, match="levels differ"):
                await control.create_signal_proposal(
                    signal_id="bad-level",
                    symbol=instrument.ftmo_symbol,
                    direction="LONG",
                    analysis_entry="2500",
                    analysis_stop="2480",
                    analysis_target="2520",
                    analysis_state="LONG",
                    confirmation_status="confirmed",
                    source="test",
                    evidence_bundle=envelope,
                    now=NOW,
                )
            return
        with pytest.raises(ValueError):
            await validate_shared_evidence(store, instrument, envelope, when)

    asyncio.run(scenario())


def directional_layers(monkeypatch, *, entry_top=140.2):
    """Deterministic engine assessments; keep real coordination/risk/TP/scoring."""
    from dataclasses import replace
    from monatise.application.hierarchy.evaluator import LayerAnalysis
    from monatise.engines.market_structure.models import (
        StructureBias,
        StructureState,
        StructureEvent,
        BreakType,
    )
    from monatise.engines.supply_demand.models import (
        SupplyDemandZone,
        ZoneType,
        ZoneDirection,
        ZoneStrength,
        ZoneFreshness,
    )
    from monatise.engines.liquidity.models import (
        LiquidityLevel,
        LiquiditySide,
        LiquidityLevelType,
        LiquidityStrength,
    )

    original = HierarchyLayerEvaluator._analyse_structure

    def assess(self, snapshot, regime):
        layer = original(self, snapshot, regime)
        if layer is None:
            return None
        tf = snapshot.timeframe
        stop = {"4h": 100, "1h": 110, "15m": 136, "5m": 130, "1m": 139}[tf]
        destination = {"4h": 170, "1h": 165, "15m": 160, "5m": 155, "1m": 155}[tf]
        zone = SupplyDemandZone(
            ZoneType.DEMAND,
            ZoneDirection.RALLY_BASE_RALLY,
            entry_top,
            139.2,
            90,
            88,
            89,
            90,
            ZoneStrength.HIGH,
            ZoneFreshness.FRESH,
            2,
            0,
            0,
            True,
            (),
        )
        level = LiquidityLevel(
            destination,
            LiquiditySide.BUY_SIDE,
            LiquidityLevelType.SWING_HIGH,
            LiquidityStrength.HIGH,
            3,
            0.1,
            10,
            80,
        )
        event = StructureEvent(BreakType.BULLISH_BOS, 138, 99, 140.2, 0.8, True, ())
        return LayerAnalysis(
            market=replace(layer.market, price=140.2 if tf == "1m" else 149.0),
            liquidity=replace(
                layer.liquidity,
                buy_side_levels=(level,),
                sell_side_levels=(),
                nearest_buy_side=level,
                nearest_sell_side=None,
            ),
            sweep=layer.sweep,
            reclaim=layer.reclaim,
            zones=replace(
                layer.zones,
                demand_zones=(zone,),
                supply_zones=(),
                active_demand=zone,
                nearest_demand=zone,
                active_supply=None,
                nearest_supply=None,
            ),
            structure=replace(
                layer.structure,
                bias=StructureBias.BULLISH,
                state=StructureState.BULLISH_CONTINUATION,
                events=(event,),
                latest_event=event,
                swing_lows=((98, stop),),
                swing_highs=((10, destination),),
                confidence=0.9,
            ),
        )

    monkeypatch.setattr(HierarchyLayerEvaluator, "_analyse_structure", assess)


@pytest.mark.parametrize("symbol", ["AAPL", "US100.cash"])
@pytest.mark.parametrize("multi_tp", [False, True])
def test_confirmed_shared_setup_flows_through_approval_and_invalidation(
    monkeypatch, symbol, multi_tp
):
    from monatise.application.ftmo_master import FTMOMasterError
    from monatise.application.take_profit import TakeProfitPlan
    import monatise.application.ftmo_master as master_module

    directional_layers(monkeypatch)

    async def scenario():
        env = active_environment(
            FTMO_TEMPORARY_ARM_REQUIRED="false",
            MULTI_TP_ENABLED=str(multi_tp).lower(),
            MULTI_TP_STOCKS_ENABLED="true",
            MULTI_TP_INDICES_ENABLED="true",
        )
        control, store = service(env)
        engine = AssetHierarchyAnalysis(
            alpaca=Alpaca(), master=control, environment=env
        )
        instrument = FTMO_REGISTRY.resolve(symbol)

        async def history(self, requested, limit):
            assert requested == instrument
            return {
                "timeframes": {tf: rows(tf) for tf in POLICY.timeframes},
                "session_open": True,
                "trade_mode": "4",
                "session_close": (NOW + timedelta(minutes=2)).isoformat(),
                "captured_at": NOW.isoformat(),
            }

        monkeypatch.setattr(BrokerCandleService, "fetch", history)
        for seconds in (0, 6, 12, 18):
            result = await engine.analyse(
                instrument, now=NOW + timedelta(seconds=seconds)
            )
            if seconds < 18:
                assert not result["publication_valid"]
        assert result["publication_valid"], result
        assert result["signal_core_score"] >= 3 and result["score_scale"] == 4
        assert result["entry"] == 140.2  # M1 refinement, not the M5 price of 149.
        assert result["structural_invalidation"] == 136  # M15, not the M1 low.
        assert result["stop_loss"] < 136
        assert list(result["fibonacci"]) == list(POLICY.timeframes)
        assert result["evidence_bundle"]["entry_candle"]["timeframe"] == "1m"
        assert await validate_shared_evidence(
            store, instrument, result, NOW + timedelta(seconds=18)
        )
        if symbol == "US100.cash":
            assert result["expires_at"] == (NOW + timedelta(minutes=2)).isoformat()
        if multi_tp:
            plan = TakeProfitPlan.from_dict(result["take_profit_plan"])
            assert len(plan.targets) == 4
            assert plan.expires_at.isoformat() == result["expires_at"]
            assert {t.source_provider for t in plan.targets} == {
                "monatise_stocks" if symbol == "AAPL" else "monatise_indices"
            }
        current = NOW + timedelta(seconds=18)
        monkeypatch.setattr(master_module, "_utc", lambda value=None: value or current)
        quote = {
            **heartbeat()["quotes"]["XAUUSD"],
            "bid": "140.19",
            "ask": "140.20",
            "timestamp": current.isoformat(),
        }
        await control.accept_bridge_heartbeat(
            heartbeat(quotes={symbol: quote}, multi_tp_version=1), now=current
        )
        await control.repository.update_control(kill_switch=False)
        proposal = await control.create_signal_proposal(
            signal_id=result["setup_id"],
            symbol=symbol,
            direction="LONG",
            analysis_entry=result["entry"],
            analysis_stop=result["stop_loss"],
            analysis_target=result["target"],
            analysis_state="LONG",
            confirmation_status="confirmed",
            source="test.shared-analysis",
            evidence_bundle=result,
            take_profit_plan=result.get("take_profit_plan"),
            now=current,
        )
        command = await control.approve(proposal["proposal_id"], "42", now=current)
        assert command["payload"]["symbol"] == symbol
        await engine.invalidate(instrument)
        assert await control.commands_for_bridge(now=current) == ()
        rejected = (await control.repository.command(command["command_id"]))[0]
        assert rejected["status"] == "rejected" and "invalidated" in rejected["reason"]
        with pytest.raises(FTMOMasterError, match="invalidated"):
            await control.create_signal_proposal(
                signal_id="stale-copy",
                symbol=symbol,
                direction="LONG",
                analysis_entry=result["entry"],
                analysis_stop=result["stop_loss"],
                analysis_target=result["target"],
                analysis_state="LONG",
                confirmation_status="confirmed",
                source="test.shared-analysis",
                evidence_bundle=result,
                take_profit_plan=result.get("take_profit_plan"),
                now=current,
            )

    asyncio.run(scenario())


def test_closed_candle_revision_invalidates_cached_parents(monkeypatch):
    async def scenario():
        alpaca = Alpaca()
        control, store = service(active_environment())
        engine = AssetHierarchyAnalysis(alpaca=alpaca, master=control)
        instrument = FTMO_REGISTRY.resolve("AAPL")
        await engine.analyse(instrument, now=NOW)
        original = alpaca.stock_bars

        def revised(*args):
            data = original(*args)
            data[-1]["v"] += 1
            return data

        monkeypatch.setattr(alpaca, "stock_bars", revised)
        result = await engine.analyse(instrument, now=NOW + timedelta(seconds=6))
        assert result["reason_code"] == "closed_candle_revision"
        assert instrument.ftmo_symbol not in engine._engines
        assert (await store.get(CURRENT, instrument.ftmo_symbol)).value[
            "state"
        ] == "invalidated"

    asyncio.run(scenario())


def test_candle_endpoint_retains_hmac_nonce_and_response_identity_checks():
    import json
    import secrets
    from monatise.application.ftmo_master import FTMOBridgeAuthenticator
    from monatise.application.production import ProductionASGI

    async def scenario():
        observed = datetime.now(timezone.utc)
        control, store = service()
        await control.accept_bridge_heartbeat(
            heartbeat(history_version=1), now=observed
        )
        request_id = "a" * 32
        await store.put(
            DEMANDS,
            request_id,
            {
                "request_id": request_id,
                "symbol": "US100.cash",
                "limit": 200,
                "state": "pending",
                "account_id": control.configuration.account_id,
                "server": control.configuration.server,
                "requested_at": observed.isoformat(),
                "expires_at": (observed + timedelta(seconds=30)).isoformat(),
            },
        )
        advertised = await BrokerCandleService(control).next_request(observed)
        assert advertised == request_id + "|US100.cash|200|" + ",".join(
            POLICY.timeframes
        )
        payload = {
            "request_id": request_id,
            "symbol": "US100.cash",
            "account_id": control.configuration.account_id,
            "server": control.configuration.server,
            "captured_at": observed.isoformat(),
            "timeframes": {tf: rows(tf, observed) for tf in POLICY.timeframes},
            "trade_mode": "4",
            "session_open": True,
            "session_close": (observed + timedelta(hours=2)).isoformat(),
        }
        path = "/api/ftmo/bridge/candles"
        body = json.dumps(payload).encode()
        stamp, nonce = str(int(observed.timestamp())), secrets.token_hex(16)
        signature = FTMOBridgeAuthenticator.sign(
            control.configuration.bridge_secret, "POST", path, stamp, nonce, body
        )
        scope = {
            "method": "POST",
            "path": path,
            "headers": [
                (b"x-monatise-timestamp", stamp.encode()),
                (b"x-monatise-nonce", nonce.encode()),
                (b"x-monatise-signature", signature.encode()),
            ],
        }

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        app = ProductionASGI(SimpleNamespace(ftmo_master=control))
        code, result = await app._ftmo_bridge_request({**scope, "headers": []}, receive)
        assert code == 401
        assert (await store.get(DEMANDS, request_id)).value["state"] == "pending"
        code, result = await app._ftmo_bridge_request(scope, receive)
        assert code == 200 and result["execution_enabled"] is False
        assert (await app._ftmo_bridge_request(scope, receive))[0] == 401
        assert await control.repository.pending_commands() == ()

    asyncio.run(scenario())


def test_scanner_preserves_optional_provider_cycle_quotas():
    from monatise.application.market_intelligence import (
        StockMarketIntelligenceCoordinator,
    )
    from tests.test_market_intelligence import (
        FlashAlpha,
        Quiver,
        Finnhub,
        Alpaca,
        NOW as observed,
    )

    alpaca = Alpaca()
    result = asyncio.run(
        StockMarketIntelligenceCoordinator(
            alpaca,
            Quiver(),
            Finnhub(),
            FlashAlpha(),
            environment={
                "MONATISE_STOCK_QUIVER_CAP_PER_CYCLE": "1",
                "MONATISE_STOCK_FINNHUB_CAP_PER_CYCLE": "1",
            },
        ).analyse(
            "AAPL",
            instrument=FTMO_REGISTRY.resolve("AAPL"),
            now=observed,
            enrichment_index=1,
        )
    )
    sources = {row["provider"]: row for row in result["analysis_sources"]}
    assert (
        sources["quiver"]["failure_reason"]
        == sources["finnhub"]["failure_reason"]
        == "cycle_quota_reserved"
    )
    assert (
        sources["alpaca"]["status"] == "used"
        and sources["flashalpha"]["status"] == "used"
    )


def test_analysis_cancellation_invalidates_old_setup(monkeypatch):
    async def scenario():
        control, store = service()
        instrument = FTMO_REGISTRY.resolve("AAPL")
        await persist_proof(control, "AAPL", NOW)
        engine = AssetHierarchyAnalysis(master=control)

        async def cancelled(*args, **kwargs):
            raise asyncio.CancelledError()

        monkeypatch.setattr(engine, "_analyse", cancelled)
        with pytest.raises(asyncio.CancelledError):
            await engine.analyse(instrument, now=NOW)
        assert (await store.get(CURRENT, instrument.ftmo_symbol)).value[
            "state"
        ] == "invalidated"

    asyncio.run(scenario())


def test_concurrent_invalidation_cannot_be_overwritten_by_older_analysis(monkeypatch):
    async def scenario():
        control, store = service()
        envelope = await persist_proof(control, "AAPL", NOW)
        instrument = FTMO_REGISTRY.resolve("AAPL")
        engine = AssetHierarchyAnalysis(master=control)

        async def interrupted(*args, **kwargs):
            await store.put(
                CURRENT,
                instrument.ftmo_symbol,
                {"state": "invalidated", "bundle_id": None},
            )
            return {
                **envelope,
                "publication_valid": True,
                "entry": "2500",
                "stop_loss": "2490",
                "target": "2520",
                "direction": "LONG",
                "expires_at": (NOW + timedelta(minutes=15)).isoformat(),
            }

        monkeypatch.setattr(engine, "_analyse", interrupted)
        result = await engine.analyse(instrument, now=NOW)
        assert result["publication_valid"] is False
        assert (await store.get(CURRENT, instrument.ftmo_symbol)).value[
            "state"
        ] == "invalidated"

    asyncio.run(scenario())


def test_closed_m1_price_outside_entry_zone_cannot_be_replaced_by_clamped_entry(
    monkeypatch,
):
    directional_layers(monkeypatch, entry_top=140.0)

    async def scenario():
        control, store = service()
        engine = AssetHierarchyAnalysis(alpaca=Alpaca(), master=control)
        instrument = FTMO_REGISTRY.resolve("AAPL")
        for seconds in (0, 6, 12, 18):
            result = await engine.analyse(
                instrument, now=NOW + timedelta(seconds=seconds)
            )
        assert result["publication_valid"] is False
        assert result["setup_status"] == "awaiting_entry_zone"
        assert result["current_price"] == pytest.approx(140.2)
        assert result.get("entry") is None
        assert (await store.get(CURRENT, instrument.ftmo_symbol)).value[
            "state"
        ] == "invalidated"

    asyncio.run(scenario())
