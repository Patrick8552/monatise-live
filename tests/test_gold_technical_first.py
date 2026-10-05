"""Synthetic, fixed-clock Gold acceptance tests. No market-data networking."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import sin
from types import SimpleNamespace

import pytest

from monatise.analysis.tradingview import normalize_tradingview_alert
from monatise.application.deployment import OrchestrationRuntime
from monatise.application.ftmo_master import FTMOMasterError
from monatise.application.ftmo_registry import FTMO_REGISTRY
from monatise.application.gold_analysis import (
    GoldAnalysisCoordinator,
    GoldHierarchyAnalysis,
    GoldPolicy,
    sweep_reversal,
)
from monatise.application.hierarchy.broker_candles import (
    DEMANDS,
    BrokerCandleService,
    is_xauusd,
    supports_broker_history,
)
from monatise.application.market_intelligence import (
    FuturesMarketIntelligenceCoordinator,
)
from monatise.core.models import Candle
from tests.test_application_hierarchy import MemoryStore
from tests.test_ftmo_master import active_environment, heartbeat, service

NOW = datetime(2026, 10, 5, 15, 0, 20, tzinfo=UTC)
GOLD = FTMO_REGISTRY.resolve("XAU/USD")
SECONDS = {"4h": 14400, "1h": 3600, "15m": 900, "5m": 300, "1m": 60}


def synthetic_candles(tf="15m", *, short=False):
    tail = [
        (2501, 2502, 2499, 2500),
        (2500, 2503, 2499, 2501),
        (2501, 2502, 2490, 2495),
        (2495, 2504, 2493, 2500),
        (2500, 2507, 2498, 2505),
        (2505, 2510, 2502, 2506),
        (2506, 2507, 2498, 2502),
        (2502, 2504, 2495, 2499),
        (2499, 2503, 2488, 2496),
        (2496, 2516, 2495, 2515),
        (2515, 2516, 2509, 2512),
        (2512, 2520, 2511, 2519),
    ]
    values = []
    for i in range(60):
        v = 2495 + sin(i * 0.7) * 8
        values.append((v, v + 2, v - 2, v + 0.5))
    values += tail
    boundary = datetime.fromtimestamp(
        int(NOW.timestamp()) // SECONDS[tf] * SECONDS[tf], UTC
    )
    candles = []
    for i, (o, h, l, c) in enumerate(values):
        if short:
            o, h, l, c = 5000 - o, 5000 - l, 5000 - h, 5000 - c
        candles.append(
            Candle(
                (
                    boundary - timedelta(seconds=SECONDS[tf] * (len(values) - i))
                ).isoformat(),
                o,
                h,
                l,
                c,
                1000 + i,
            )
        )
    return tuple(candles)


class FixtureTechnical(GoldHierarchyAnalysis):
    """Only transport is replaced; all analytical engines/risk/TP are real."""

    def __init__(self, *, mutation=None, **kwargs):
        super().__init__(**kwargs)
        self.mutation = mutation

    async def _batch(self, instrument, now):
        data = {
            tf: [
                {
                    "t": c.timestamp,
                    "o": c.open,
                    "h": c.high,
                    "l": c.low,
                    "c": c.close,
                    "v": c.volume,
                }
                for c in synthetic_candles(tf)
            ]
            for tf in SECONDS
        }
        for row in data["4h"]:
            for key in ("o", "h", "l", "c"):
                row[key] += 100  # independent H4 advisory
        if self.mutation == "duplicate":
            data["1m"][-1]["t"] = data["1m"][-2]["t"]
        if self.mutation == "future":
            data["1m"][-1]["t"] = (now + timedelta(minutes=1)).isoformat()
        if self.mutation == "revision":
            data["15m"][-1]["c"] -= 0.1
        if self.mutation == "no_sweep":
            data["15m"][-4]["l"] = 2491
        if self.mutation == "units":
            raise ValueError("gold_broker_units_unavailable")
        self._engines[instrument.ftmo_symbol][2].broker_units = {
            "point": 0.01,
            "tick_size": 0.01,
            "spread_price": 0.2,
        }
        return (
            data,
            now + timedelta(hours=3),
            {
                "provider": "ftmo_mt5",
                "volume_kind": "tick_volume",
                "timestamp_policy": "synthetic_UTC",
            },
            None,
        )


@pytest.mark.parametrize("short", [False, True])
def test_causal_pattern_positive_and_prefix_replay(short):
    candles = synthetic_candles(short=short)
    direction = "short" if short else "long"
    result = sweep_reversal(candles, direction, "15m")
    assert result["confirmed"]
    assert (
        result["liquidity_index"] + 2
        < result["sweep_index"]
        < result["displacement_index"]
        < result["retest_index"]
    )
    assert not sweep_reversal(candles[:-2], direction, "15m")["confirmed"]
    assert not sweep_reversal(candles, "long" if short else "short", "15m")["confirmed"]


@pytest.mark.parametrize(
    "change", ["wick", "no_displacement", "no_retest", "gap", "later_invalidation"]
)
def test_label_or_partial_pattern_never_qualifies(change):
    cs = list(synthetic_candles())
    if change == "wick":
        cs[-4] = replace(cs[-4], close=2489)
    elif change == "no_displacement":
        cs[-3] = replace(cs[-3], open=2514)
    elif change == "no_retest":
        cs[-2] = replace(cs[-2], low=2511)
    elif change == "gap":
        cs[-1] = replace(cs[-1], timestamp=(NOW - timedelta(minutes=1)).isoformat())
    else:
        cs[-1] = replace(cs[-1], low=2480, close=2487)
    assert not sweep_reversal(tuple(cs), "long", "15m")["confirmed"]


def test_actual_engine_integration_confirms_causal_setup_and_trigger_then_rejects_bad_rr():
    async def scenario():
        technical = FixtureTechnical()
        coordinator = GoldAnalysisCoordinator(technical=technical)
        first = await coordinator.analyse(GOLD, now=NOW)
        assert not first["analytical_qualified"]
        second = await coordinator.analyse(GOLD, now=NOW + timedelta(seconds=6))
        assert second["market_structure"]["structure_bias"] == "bullish"
        assert second["liquidity"]["gold_pattern"]["confirmed"]
        evaluator = technical._engines[GOLD.ftmo_symbol][2]
        assert (
            evaluator._state[GOLD.ftmo_symbol].setup_context.state.value
            == "setup_confirmed"
        )
        assert (
            evaluator._state[GOLD.ftmo_symbol].trigger_context.state.value
            == "trigger_confirmed"
        )
        assert second["fibonacci"]["15m"]["has_valid_anchor"]
        assert second["reasons"] == [
            "risk_proposal_rejected:tp1_reward_risk_below_minimum"
        ]
        assert second["current_price"] == 2519
        assert (
            second["signal_core_score"] == 3
            and not second["signal_core_evidence"]["value"]
        )
        assert not second["publication_valid"] and not second["approval_eligible"]

    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["duplicate", "future", "units", "no_sweep"])
def test_invalid_real_engine_inputs_fail_precisely(mutation):
    async def scenario():
        technical = FixtureTechnical(mutation=mutation)
        await technical.analyse(GOLD, now=NOW)
        result = await technical.analyse(GOLD, now=NOW + timedelta(seconds=6))
        assert not result["analytical_qualified"]
        if mutation == "no_sweep":
            assert not result["liquidity"]["gold_pattern"]["confirmed"]
        else:
            assert result["decision"] == "INSUFFICIENT_MARKET_DATA"

    asyncio.run(scenario())


def test_closed_revision_invalidates_real_engine_state():
    async def scenario():
        t = FixtureTechnical()
        await t.analyse(GOLD, now=NOW)
        await t.analyse(GOLD, now=NOW + timedelta(seconds=6))
        t.mutation = "revision"
        r = await t.analyse(GOLD, now=NOW + timedelta(seconds=12))
        assert (
            r["reason_code"] == "closed_candle_revision"
            and GOLD.ftmo_symbol not in t._engines
        )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "symbol", ["XAU/EUR", "XAU/AUD", "XAG/USD", "USOIL.cash", "EUR/USD", "BTCUSD"]
)
def test_registered_history_scope_excludes_other_markets(symbol):
    assert not supports_broker_history(FTMO_REGISTRY.resolve(symbol))
    assert not is_xauusd(FTMO_REGISTRY.resolve(symbol))


def test_exact_registered_identity_and_index_compatibility():
    assert supports_broker_history(GOLD)
    for i in FTMO_REGISTRY.all():
        if "Index" in i.display_name:
            assert supports_broker_history(i)
    assert not supports_broker_history(replace(GOLD, display_name="Gold Index"))
    assert not supports_broker_history(
        SimpleNamespace(ftmo_symbol="XAU/USD", enabled=True)
    )


def test_gold_transport_preserves_identity_nonce_lease_replay_units_and_cas():
    async def scenario():
        store = MemoryStore()

        class Master:
            repository = SimpleNamespace(store=store)
            configuration = SimpleNamespace(
                account_id="synthetic-account", server="synthetic-server"
            )
            _symbol_key = staticmethod(lambda x: x.replace("/", "").upper())

            async def _healthy_bridge(self, now):
                return {"history_version": 2}

        transport = BrokerCandleService(Master())
        request = {
            "state": "pending",
            "symbol": "XAU/USD",
            "limit": 200,
            "account_id": "synthetic-account",
            "server": "synthetic-server",
            "expires_at": (NOW + timedelta(seconds=30)).isoformat(),
            "requested_at": NOW.isoformat(),
            "gold": True,
        }
        await store.put(DEMANDS, "nonce", request, expected_version=0)
        payload = {
            "request_id": "nonce",
            "symbol": "XAUUSD",
            "account_id": "synthetic-account",
            "server": "synthetic-server",
            "captured_at": NOW.isoformat(),
            "session_open": True,
            "session_close": (NOW + timedelta(hours=1)).isoformat(),
            "trade_mode": "4",
            "point": 0.01,
            "tick_size": 0.01,
            "spread_price": 0.2,
            "timestamp_policy": "current_offset_uncertified_history",
            "timeframes": {
                tf: [
                    {
                        "t": c.timestamp,
                        "o": c.open,
                        "h": c.high,
                        "l": c.low,
                        "c": c.close,
                        "v": c.volume,
                    }
                    for c in synthetic_candles(tf)
                ]
                for tf in SECONDS
            },
        }
        for field, value in [
            ("account_id", "other"),
            ("symbol", "XAU/EUR"),
            ("request_id", "other"),
            ("point", None),
            ("tick_size", float("nan")),
            ("spread_price", -1),
        ]:
            with pytest.raises(ValueError):
                await transport.accept({**payload, field: value}, now=NOW)
        result = await transport.accept(payload, now=NOW)
        assert not result["execution_enabled"]
        assert (await store.get(DEMANDS, "nonce")).value["response"][
            "volume_kind"
        ] == "tick_volume"
        with pytest.raises(ValueError, match="consumed"):
            await transport.accept(payload, now=NOW)

    asyncio.run(scenario())


class StubTechnical:
    """Lifecycle fixture, separate from the real-engine integration above."""

    def __init__(self):
        self.invalidated = 0

    async def analyse(self, *args, now=None, **kwargs):
        return {
            "analytical_qualified": True,
            "setup_id": "synthetic-proof",
            "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
            "direction": "LONG",
            "analysis_sources": [],
            "reasons": [],
        }

    async def invalidate(self, *args):
        self.invalidated += 1


class Optional:
    def __init__(self):
        self.failed = False

    async def snapshot(self, *args, now=None):
        if self.failed:
            raise PermissionError("synthetic secret must never appear")
        return {
            "status": "usable",
            "symbol": "XAU/USD",
            "strategy_version": "xauusd-technical-v1",
            "as_of": NOW.isoformat(),
            "expires_at": (NOW + timedelta(seconds=30)).isoformat(),
            "gil_state": "CONFIRMED",
        }


def test_required_loss_invalidates_without_downgrade_or_expiry_renewal():
    async def scenario():
        technical = StubTechnical()
        provider = Optional()
        policy = GoldPolicy(
            strategy="gold-sweep-reversal-gc-v1",
            required_sources=("broker_candles", "gc_futures"),
        )
        coordinator = GoldAnalysisCoordinator(
            technical=technical, gc_provider=provider, policy=policy
        )
        r = await coordinator.analyse(GOLD, now=NOW)
        assert (
            r["analytical_qualified"]
            and r["expires_at"] == (NOW + timedelta(seconds=30)).isoformat()
        )
        provider.failed = True
        r = await coordinator.analyse(GOLD, now=NOW + timedelta(seconds=1))
        assert (
            not r["analytical_qualified"]
            and r["strategy"] == policy.strategy
            and technical.invalidated == 1
        )
        assert "synthetic secret" not in str(r)
        provider.failed = False
        r = await coordinator.analyse(GOLD, now=NOW + timedelta(seconds=2))
        assert (
            not r["analytical_qualified"]
            and "gold_setup_expired_or_invalidated" in r["reasons"]
        )

    asyncio.run(scenario())


def test_optional_loss_keeps_technical_qualification_and_no_publication():
    async def scenario():
        provider = Optional()
        provider.failed = True
        c = GoldAnalysisCoordinator(technical=StubTechnical(), gc_provider=provider)
        r = await c.analyse(GOLD, now=NOW)
        assert (
            r["analytical_qualified"]
            and not r["publication_valid"]
            and not r["execution"]["enabled"]
        )

    asyncio.run(scenario())


def test_runtime_scan_and_on_demand_share_gold_without_flashalpha():
    async def scenario():
        class NeverFlash:
            def context(self, *args):
                raise AssertionError("Gold must not call FlashAlpha")

        coordinator = GoldAnalysisCoordinator(technical=StubTechnical())
        runtime = OrchestrationRuntime(environment={}, flashalpha=NeverFlash())
        runtime.gold_analysis = coordinator
        result = await runtime.analyse_ftmo_futures_instrument(GOLD)
        assert result["strategy"] == coordinator.policy.strategy
        # The real scanner runs; shadow results must never reach Telegram.
        scan = await runtime._analyze_ftmo_futures((GOLD,), 300, "synthetic")
        assert scan["provider_roots"] == 0 and scan["telegram_published"] == 0
        assert scan["results"][0]["strategy"] == result["strategy"]
        result = await FuturesMarketIntelligenceCoordinator(
            NeverFlash(), environment={}, gold=coordinator
        ).analyse(GOLD, now=NOW)
        assert result["analytical_qualified"]

    asyncio.run(scenario())


@pytest.mark.parametrize("provider", ["ftmo_mt5", "databento"])
def test_new_gold_proposals_rejected_at_master_boundary(provider):
    async def scenario():
        control, _ = service(active_environment())
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        with pytest.raises(FTMOMasterError, match="gold approval disabled"):
            await control.create_signal_proposal(
                signal_id="synthetic",
                symbol="XAUUSD",
                direction="LONG",
                analysis_entry="2500",
                analysis_stop="2490",
                analysis_target="2520",
                source="test",
                analysis_state="LONG",
                confirmation_status="confirmed",
                analysis_provider=provider,
                now=NOW,
            )
        assert not await control.repository.pending_commands()

    asyncio.run(scenario())


def test_gold_reference_is_explicit_fresh_and_cannot_be_a_command():
    payload = {
        "symbol": "FXCM:XAUUSD",
        "action": "BUY",
        "price": 2519,
        "timestamp": NOW.isoformat(),
        "timeframe": "5",
        "entry": 2500,
        "sl": 2490,
        "tp1": 2600,
    }
    with pytest.raises(ValueError):
        normalize_tradingview_alert(payload, now=NOW.timestamp())
    r = normalize_tradingview_alert(
        payload, allow_gold_reference=True, now=NOW.timestamp()
    )
    assert r["reference_only"] and r["symbol"] == "XAUUSD" and r["action"] == "WAIT"
    assert r["setup"]["entry"] is None and r["setup"]["stop"] is None
    for change in (
        {"symbol": "GOLD"},
        {"timestamp": (NOW - timedelta(minutes=6)).isoformat()},
        {"timestamp": (NOW + timedelta(seconds=1)).isoformat()},
        {"price": "nan"},
        {"timeframe": "30"},
    ):
        with pytest.raises(ValueError):
            normalize_tradingview_alert(
                {**payload, **change}, allow_gold_reference=True, now=NOW.timestamp()
            )
    assert (
        normalize_tradingview_alert({"symbol": "COMEX:GC1!", "action": "WAIT"})[
            "symbol"
        ]
        == "GC"
    )


def test_reference_legacy_target_aliases_grid_and_hedge_fields_are_removed():
    r = normalize_tradingview_alert(
        {
            "symbol": "FXCM:XAUUSD",
            "action": "BUY",
            "timestamp": NOW.isoformat(),
            "timeframe": "5",
            "price": 2500,
            "targetOne": 2600,
            "targetTwo": 2700,
            "gridStep": 1,
            "gridLower": 2400,
            "gridUpper": 2600,
            "hedgeRatio": 1,
            "hedgeTrigger": 2500,
        },
        allow_gold_reference=True,
        now=NOW.timestamp(),
    )
    assert r["setup"]["targetOne"] is None and r["setup"]["targetTwo"] is None
    assert r["hedge"]["ratio"] is None and r["hedge"]["trigger"] is None
    assert r["receivedAt"] == NOW.timestamp()


def test_gold_report_normalization_preserves_unavailable_score_and_no_proposal():
    from monatise.application.telegram_analysis import (
        format_analysis,
        normalize_analysis,
        resolve_telegram_instrument,
    )

    raw = asyncio.run(GoldAnalysisCoordinator().analyse(GOLD, now=NOW))
    analysis = normalize_analysis(
        raw,
        resolve_telegram_instrument("XAUUSD", FTMO_REGISTRY),
        request_id="synthetic-request",
        analysis_id="synthetic-analysis",
        requested_at=NOW,
        started_at=NOW,
        completed_at=NOW,
        session={},
    )
    assert analysis["score"] is None and analysis["conviction"] is None
    assert analysis["optional_evidence"]["gc_futures"]["status"] == "unavailable"
    assert not analysis["proposal_eligible"] and not analysis["executable"]
    message = format_analysis(analysis)
    assert (
        "Evidence score: unavailable" in message and "Publication: disabled" in message
    )
    assert "gc_futures: unavailable" in message and "0/10" not in message


def test_shadow_qualification_never_promoted_by_report_normalization():
    from monatise.application.telegram_analysis import (
        normalize_analysis,
        resolve_telegram_instrument,
    )

    raw = {
        "gold_policy_version": "xauusd-technical-v1",
        "strategy": "gold-sweep-reversal-technical-v1",
        "analytical_qualified": True,
        "setup_status": "confirmed",
        "decision": "BUY_WATCH",
        "direction": "LONG",
        "score": 3,
        "entry": 2500,
        "entry_zone": {"low": 2499, "high": 2501},
        "current_price": 2500.5,
        "stop_loss": 2490,
        "targets": [2530],
        "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
    }
    analysis = normalize_analysis(
        raw,
        resolve_telegram_instrument("XAUUSD", FTMO_REGISTRY),
        request_id="synthetic-request",
        analysis_id="synthetic-analysis",
        requested_at=NOW,
        started_at=NOW,
        completed_at=NOW,
        session={},
    )
    assert (
        analysis["analytical_qualified"] and analysis["decision"] == "SHADOW_QUALIFIED"
    )
    assert analysis["current_reference_price"] == 2500.5 and analysis["entry"] == 2500
    assert not analysis["proposal_eligible"] and not analysis["pending_order_eligible"]
