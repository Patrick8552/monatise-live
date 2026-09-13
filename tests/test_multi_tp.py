from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

from monatise.application.take_profit import (
    MultiTPConfiguration,
    TakeProfitPlan,
    TargetCandidate,
    allocate_volume,
    build_plan,
    convert_plan,
    revalidate_plan,
    route_for,
)
from monatise.application.target_evidence import (
    apply_flashalpha_plan,
    crypto_layer_candidates,
    flashalpha_candidates,
    apply_crypto_output_plan,
    format_crypto_output_plan,
)
from monatise.application.position_management import (
    ManagedPosition,
    PositionManagementService,
    protective_stop,
)
from monatise.application.ftmo_master import (
    FTMOMasterControlService,
    FTMOMasterError,
    format_proposal,
)
from tests.test_ftmo_master import NOW, heartbeat
from tests.test_trade_publication import setup


def config(**changes):
    return replace(
        MultiTPConfiguration(
            enabled=True,
            routes=frozenset({"gold", "stocks", "futures", "indices", "crypto"}),
        ),
        **changes,
    )


def evidence(price, kind="CALL_WALL", provider="flashalpha", **kwargs):
    return TargetCandidate(
        D(str(price)),
        "observed test structure",
        provider,
        kind,
        D(".8"),
        "15m",
        NOW,
        **kwargs,
    )


def plan(n=4, short=False, **kwargs):
    levels = [90, 85, 80, 76] if short else [110, 115, 120, 124]
    return build_plan(
        candidates=[evidence(v) for v in levels[:n]],
        direction="short" if short else "long",
        entry=100,
        stop=105 if short else 95,
        now=NOW,
        expires_at=NOW + timedelta(minutes=30),
        config=config(),
        **kwargs,
    )


@pytest.mark.parametrize("short", [False, True])
@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_evidence_ladders_and_allocation(short, count):
    result = plan(count, short)
    assert len(result.targets) == count
    assert sum(t.allocation_pct for t in result.targets) == 100
    assert result.targets[0].rr == 2
    assert result.legacy_take_profit == result.targets[-1].price
    assert TakeProfitPlan.from_dict(json.loads(json.dumps(result.to_dict()))) == result
    assert result.blended_expected_rr <= result.maximum_available_rr


def test_duplicates_merge_at_nearer_obstacle_and_add_independent_confluence():
    result = build_plan(
        candidates=[
            evidence(110),
            evidence("110.02", provider="alpaca"),
            evidence(115),
        ],
        direction="long",
        entry=100,
        stop=95,
        now=NOW,
        expires_at=NOW + timedelta(minutes=30),
        config=config(),
    )
    assert [t.price for t in result.targets] == [D(110), D(115)]
    assert result.targets[0].agreement == ("alpaca",)
    assert "merged_nearby" in result.rejection_log[0]


@pytest.mark.parametrize("prices", [[99], [105, 120], [float("nan")], [150]])
def test_bad_candidates_and_weak_first_objective_rejected(prices):
    with pytest.raises((ValueError, ArithmeticError)):
        build_plan(
            candidates=[evidence(v) for v in prices],
            direction="long",
            entry=100,
            stop=95,
            now=NOW,
            expires_at=NOW + timedelta(minutes=30),
            config=config(),
        )


@pytest.mark.parametrize(
    "mutation",
    ["reverse", "duplicate", "allocation", "provenance", "rr", "unknown_version"],
)
def test_untrusted_ladder_schema_rejected(mutation):
    payload = plan().to_dict()
    if mutation == "reverse":
        payload["targets"].reverse()
    if mutation == "duplicate":
        payload["targets"][1]["price"] = payload["targets"][0]["price"]
    if mutation == "allocation":
        payload["targets"][0]["allocation_pct"] = "0"
    if mutation == "provenance":
        payload["targets"][0]["evidence_type"] = ""
    if mutation == "rr":
        payload["targets"][0]["rr"] = "100"
    if mutation == "unknown_version":
        payload["version"] = 2
    with pytest.raises(ValueError):
        TakeProfitPlan.from_dict(payload)


@pytest.mark.parametrize(
    "root,analysis_entry,execution_entry",
    [("GC", 2500, 2480), ("ES", 6000, 5980), ("NQ", 21000, 20950)],
)
def test_relative_conversion_every_level(root, analysis_entry, execution_entry):
    original = build_plan(
        candidates=[
            evidence(D(analysis_entry) * v)
            for v in map(D, ["1.02", "1.03", "1.04", "1.05"])
        ],
        direction="long",
        entry=analysis_entry,
        stop=D(analysis_entry) * D(".99"),
        now=NOW,
        expires_at=NOW + timedelta(minutes=30),
        config=config(),
    )
    result = convert_plan(
        original,
        broker_entry=execution_entry,
        broker_stop=D(execution_entry) * D(".99"),
        tick_size=".01",
        now=NOW,
    )
    for target, factor in zip(result.targets, map(D, ["1.02", "1.03", "1.04", "1.05"])):
        assert target.price == D(execution_entry) * factor
        assert target.analysis_price != target.broker_price
    assert route_for(
        SimpleNamespace(asset_class="futures_linked", futures_symbol=root)
    ) == ("gold" if root == "GC" else "indices")


def test_conversion_and_revalidation_reject_invalid_mapping_expiry_and_price_move():
    with pytest.raises(ValueError, match="ratio"):
        convert_plan(plan(), broker_entry=1000, broker_stop=950, tick_size=".01")
    with pytest.raises(ValueError, match="SETUP_STALE"):
        plan().validate(now=NOW + timedelta(hours=1))
    with pytest.raises(ValueError):
        revalidate_plan(plan(), entry=109, stop=95, tick_size=".01", now=NOW)
    result = revalidate_plan(plan(), entry=101, stop=95, tick_size=".01", now=NOW)
    assert [t.price for t in result.targets] == [t.price for t in plan().targets]
    with pytest.raises(ValueError):
        convert_plan(plan(), broker_entry=100, broker_stop=95, tick_size=10)


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_volume_rounding_conserves_every_lot(count):
    result = allocate_volume(plan(count), volume=".17", minimum=".01", step=".01")
    assert sum(t.allocated_volume for t in result.targets) == D(".17")
    assert all(t.allocated_volume >= D(".01") for t in result.targets)


def test_tiny_position_rejected_without_silent_fallback():
    with pytest.raises(ValueError, match="too small"):
        allocate_volume(plan(), volume=".01", minimum=".01", step=".01")
    assert allocate_volume(plan(1), volume=".01", minimum=".01", step=".01").targets[
        0
    ].allocated_volume == D(".01")


def test_flashalpha_missing_secondary_levels_and_disagreement():
    context = dict(as_of=NOW.isoformat(), call_wall=110, put_wall=90, gamma_flip=95)
    assert len(flashalpha_candidates(context)) == 3
    analysis = dict(
        direction="LONG",
        entry=100,
        stop_loss=95,
        target=110,
        setup_status="confirmed",
        score=8,
    )
    result = apply_flashalpha_plan(
        dict(analysis), context, config=config(), route="stocks", now=NOW
    )
    assert len(result["take_profit_plan"]["targets"]) == 1
    conflict = apply_flashalpha_plan(
        dict(analysis, provider_consensus="CONFLICT"),
        context,
        config=config(),
        route="stocks",
        now=NOW,
    )
    assert conflict["decision"] == "NO_TRADE"
    malformed = apply_flashalpha_plan(
        dict(analysis),
        dict(context, positioning_levels={"resistance_levels": "garbage"}),
        config=config(),
        route="stocks",
        now=NOW,
    )
    assert malformed["setup_status"] == "invalid_targets"
    assert (
        apply_flashalpha_plan(
            dict(analysis),
            context,
            config=MultiTPConfiguration(),
            route="stocks",
            now=NOW,
        )
        == analysis
    )


def test_candidate_freshness():
    with pytest.raises(ValueError, match="evidence"):
        build_plan(
            candidates=[replace(evidence(110), observed_at=NOW - timedelta(days=1))],
            direction="long",
            entry=100,
            stop=95,
            now=NOW,
            expires_at=NOW + timedelta(minutes=30),
            config=config(),
        )


def test_configuration_defaults_and_invalid_allocations():
    c = MultiTPConfiguration.from_environment({})
    assert not any([c.enabled, c.auto_partial_close, c.auto_breakeven, c.auto_trailing])
    assert not c.routes and c.breakeven_mode == "NONE" and c.trail_mode == "OFF"
    with pytest.raises(ValueError):
        MultiTPConfiguration.from_environment({"MULTI_TP_ALLOCATIONS": "25,25,25,20"})


def managed(short=False):
    p = allocate_volume(plan(short=short), volume=1, minimum=".01", step=".01")
    return ManagedPosition(
        "trade",
        "123",
        "1001",
        p,
        p.to_dict(),
        p.stop,
        p.stop,
        D(1),
        D(1),
        entry=p.entry,
    )


def deal(number, volume=".25", reason="EXPERT", **changes):
    return dict(
        deal_id=str(number),
        position_id="1001",
        entry="out",
        reason=reason,
        volume=volume,
        profit="10",
        commission="-.1",
        time=NOW.isoformat(),
        **changes,
    )


@pytest.mark.parametrize("short", [False, True])
def test_all_target_fills_and_duplicate_deals(short):
    state = managed(short)
    for i, target in enumerate(state.plan.targets):
        row = deal(i, reason="TP" if i == 3 else "EXPERT")
        state.apply_deal(row, NOW, target_name=target.name)
        state.apply_deal(row, NOW, target_name=target.name)
        assert state.plan.targets[i].status == "HIT"
    assert (
        state.state == "POSITION_CLOSED" and state.terminal_reason == "FINAL_TARGET_HIT"
    )
    assert state.remaining_volume == 0 and state.realized_pnl == D("39.6")
    assert len(state.seen_deals) == 4
    recovered = ManagedPosition.from_dict(json.loads(json.dumps(state.to_dict())))
    assert recovered.to_dict() == state.to_dict()


@pytest.mark.parametrize(
    "after_tp,breakeven", [(False, False), (True, False), (True, True)]
)
def test_stop_before_or_after_tp_and_breakeven(after_tp, breakeven):
    state = managed()
    if after_tp:
        state.apply_deal(deal(1), NOW, target_name="tp1")
    if breakeven:
        state.current_sl = state.entry
    state.apply_deal(deal(2, str(state.remaining_volume), "SL"), NOW)
    assert state.state == "POSITION_CLOSED"
    assert state.terminal_reason == ("BREAKEVEN_STOPPED" if breakeven else "STOPPED")


def test_broker_final_tp_can_bypass_checkpoints_and_close_all():
    state = managed()
    state.apply_deal(deal(1, "1", "TP"), NOW)
    assert state.plan.targets[-1].closed_volume == 1
    assert [t.status for t in state.plan.targets] == ["BYPASSED"] * 3 + ["HIT"]
    assert state.remaining_volume == 0


def test_partial_fill_is_not_a_hit_and_invalid_fill_does_not_mutate():
    state = managed()
    state.apply_deal(deal(1, ".1"), NOW, target_name="tp1")
    assert state.plan.targets[0].status == "PARTIAL_FILL"
    before = state.to_dict()
    with pytest.raises(ValueError):
        state.apply_deal(deal(2, ".2"), NOW, target_name="tp1")
    assert state.to_dict() == before


@pytest.mark.parametrize("short", [False, True])
def test_breakeven_and_structure_management_require_fresh_confirmed_structure(short):
    state = managed(short)
    evidence = dict(
        confirmed=True,
        direction=state.plan.direction,
        observed_at=NOW.isoformat(),
        confirmed_higher_low=103,
        confirmed_lower_high=97,
    )
    q = dict(
        now=NOW,
        bid=110 if not short else 89,
        ask=111 if not short else 90,
        minimum_distance=1,
        tick_size=".01",
    )
    assert protective_stop(state, policy="AFTER_TP1", evidence=evidence, **q) == 100
    structure = protective_stop(state, policy="STRUCTURE_TRAIL", evidence=evidence, **q)
    assert structure == D("97.01" if short else "102.99")
    for invalid in [
        dict(evidence, confirmed=False),
        dict(evidence, invalidated=True),
        dict(evidence, observed_at=(NOW - timedelta(hours=1)).isoformat()),
    ]:
        assert protective_stop(state, policy="AFTER_TP1", evidence=invalid, **q) is None
    state.current_sl = structure
    assert protective_stop(state, policy="AFTER_TP1", evidence=evidence, **q) is None


async def execution_setup(monkeypatch, auto=False, count=4):
    control, store = await setup(
        monkeypatch,
        MULTI_TP_ENABLED="true",
        MULTI_TP_GOLD_ENABLED="true",
        AUTO_PARTIAL_CLOSE_ENABLED=str(auto).lower(),
    )
    await control.accept_bridge_heartbeat(
        heartbeat(multi_tp_version=1, account_margin_mode=0), now=NOW
    )
    p = build_plan(
        candidates=[evidence(v) for v in [2520, 2530, 2540, 2550][:count]],
        direction="long",
        entry=2500,
        stop=2490,
        now=NOW,
        expires_at=NOW + timedelta(minutes=30),
        config=config(auto_partial_close=auto),
    )
    proposal = await control.create_signal_proposal(
        signal_id="multi-test",
        symbol="XAUUSD",
        direction="LONG",
        analysis_entry=2500,
        analysis_stop=2490,
        analysis_target=p.legacy_take_profit,
        source="monatise.test",
        analysis_state="LONG",
        confirmation_status="confirmed",
        now=NOW,
        take_profit_plan=p.to_dict(),
    )
    return control, store, proposal


async def open_position(control, proposal):
    command = await control.approve(proposal["proposal_id"], "42", now=NOW)
    await control.acknowledge(
        command["command_id"],
        dict(
            status="reconciled",
            broker_retcode="10009",
            broker_ticket="123",
            fill_price=command["payload"]["entry"],
            executed_volume=command["payload"]["volume"],
            submission_attempted=True,
        ),
    )
    position = dict(
        ticket="123",
        identifier="1001",
        symbol="XAUUSD",
        magic="26082501",
        type=0,
        volume=command["payload"]["volume"],
        price_open=command["payload"]["entry"],
        sl=command["payload"]["stop_loss"],
        tp=command["payload"]["take_profit"],
        profit="0",
        comment="MNT:" + command["command_id"][:16],
    )
    await control.accept_bridge_heartbeat(
        heartbeat(multi_tp_version=1, positions=[position]), now=NOW
    )
    return position, command


def test_telegram_preview_approval_ladder_and_duplicate_intent(monkeypatch):
    async def run():
        control, _, p = await execution_setup(monkeypatch)
        text = format_proposal(p)
        assert all(
            k in text
            for k in [
                "TP1:",
                "TP2:",
                "TP3:",
                "Final:",
                "close 25.00%",
                "CALL_WALL",
                "APPROVAL_PER_EXIT",
            ]
        )
        command = await control.approve(p["proposal_id"], "42", now=NOW)
        assert command["payload"]["target_count"] == "4"
        assert command["payload"]["take_profit"] == command["payload"]["tp_3_price"]
        with pytest.raises(FTMOMasterError):
            await control.approve(p["proposal_id"], "42", now=NOW)
        assert len(await control.repository.pending_commands()) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "gate", ["kill", "execution", "master", "expiry", "movement", "capability", "route"]
)
def test_approval_gates_and_frozen_thesis(monkeypatch, gate):
    async def run():
        control, _, p = await execution_setup(monkeypatch)
        when = NOW
        if gate == "kill":
            await control.repository.update_control(kill_switch=True)
        if gate == "execution":
            control.configuration = replace(
                control.configuration, execution_enabled=False
            )
        if gate == "master":
            control.configuration = replace(
                control.configuration, master_account_approved=False
            )
        if gate == "expiry":
            when = NOW + timedelta(hours=1)
        if gate == "route":
            control.configuration = replace(
                control.configuration, multi_tp=MultiTPConfiguration()
            )
        if gate in {"movement", "capability"}:
            hb = heartbeat(multi_tp_version=0 if gate == "capability" else 1)
            if gate == "movement":
                hb["quotes"]["XAUUSD"].update(bid="2515", ask="2515.20")
            await control.accept_bridge_heartbeat(hb, now=NOW)
        with pytest.raises((FTMOMasterError, ValueError)):
            await control.approve(p["proposal_id"], "42", now=when)
        assert not await control.repository.pending_commands()

    asyncio.run(run())


def test_full_progressive_lifecycle_and_restart(monkeypatch):
    async def run():
        control, store, p = await execution_setup(monkeypatch, auto=True)
        position, opening = await open_position(control, p)
        deals = []
        manager = PositionManagementService(control)
        state, _ = await manager.get(p["proposal_id"])
        for i in range(3):
            target = state.plan.targets[i]
            hb = heartbeat(multi_tp_version=1, positions=[position], deals=deals)
            hb["quotes"]["XAUUSD"].update(
                bid=str(target.price), ask=str(target.price + D(".20"))
            )
            await control.accept_bridge_heartbeat(hb, now=NOW)
            state, _ = await manager.get(p["proposal_id"])
            pending = (await control.repository.proposal(state.pending_proposal_id))[0]
            assert pending["operation"] == "partial_close"
            command = (await control.repository.command(pending["command_id"]))[0]
            volume = D(command["payload"]["volume"])
            deals.append(
                deal(
                    i,
                    str(volume),
                    order_id=str(900 + i),
                    comment="MNT:" + command["command_id"][:16],
                )
            )
            position = dict(position, volume=str(D(position["volume"]) - volume))
            await control.acknowledge(
                command["command_id"],
                dict(
                    status="reconciled",
                    broker_retcode="10009",
                    broker_ticket=str(900 + i),
                    fill_price=str(target.price),
                    executed_volume=str(volume),
                    submission_attempted=True,
                ),
            )
            hb.update(positions=[position], deals=deals)
            await control.accept_bridge_heartbeat(hb, now=NOW)
            control = FTMOMasterControlService(
                control.configuration, control.repository
            )
            manager = PositionManagementService(control)
            state, _ = await manager.get(p["proposal_id"])
            assert state.plan.targets[i].status == "HIT"
        deals.append(deal(99, position["volume"], "TP"))
        await control.accept_bridge_heartbeat(
            heartbeat(multi_tp_version=1, positions=[], deals=deals),
            now=NOW + timedelta(hours=1),
        )
        state, _ = await manager.get(p["proposal_id"])
        assert state.state == "POSITION_CLOSED" and state.remaining_volume == 0
        assert len(state.seen_deals) == 4

    asyncio.run(run())


def test_native_partial_and_ladder_validation(tmp_path):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    header = Path("mt5/Experts/MonatiseMultiTP.mqh").resolve()
    source = tmp_path / "multi.cpp"
    source.write_text(
        '#include <cmath>\n#include <algorithm>\n#include <cassert>\n#define MathIsValidNumber std::isfinite\n#define MathAbs std::abs\n#define MathRound std::round\n#define MathMax std::max\n#include "'
        + str(header)
        + '"\nint main(){\n'
        "assert(MultiTPVolumeValid(.25,1,.01,.01));\n"
        "assert(!MultiTPVolumeValid(1,1,.01,.01));\n"
        "assert(!MultiTPVolumeValid(.009,.02,.01,.01));\n"
        "assert(!MultiTPVolumeValid(.015,.03,.01,.01));\n"
        "assert(MultiTPLevelValid(100,95,110,100,true,.01,1,1.5,.1,true));\n"
        "assert(MultiTPLevelValid(100,105,90,100,false,.01,1,1.5,.1,true));\n"
        "assert(!MultiTPLevelValid(100,95,101,100,true,.01,1,1.5,.1,true));\n"
        "assert(!MultiTPLevelValid(100,95,110,110,true,.01,1,1.5,.1,false));\n}"
    )
    binary = tmp_path / "multi"
    subprocess.run(
        [compiler, "-std=c++17", str(source), "-o", str(binary)],
        check=True,
        capture_output=True,
    )
    subprocess.run([str(binary)], check=True)


def test_crypto_candidates_from_real_liquidity_and_fibonacci_engines():
    from tests.engines.test_fibonacci_liquidity_engine import (
        make_market,
        bullish_structure,
    )
    from monatise.engines.liquidity import LiquidityEngine, LiquidityRequest
    from monatise.engines.supply_demand import SupplyDemandEngine, ZoneRequest
    from monatise.engines.fibonacci_liquidity import (
        FibonacciLiquidityEngine,
        FibonacciRequest,
    )

    market = make_market()
    structure = bullish_structure()
    liquidity = LiquidityEngine().assess(LiquidityRequest(market, range_window=40))
    zones = SupplyDemandEngine().assess(ZoneRequest(market))
    raw_fib = FibonacciLiquidityEngine().assess(
        FibonacciRequest(
            market,
            structure,
            liquidity=liquidity,
            zones=zones,
            extension_ratios=(1.272, 1.414, 1.618),
        )
    )
    layer = SimpleNamespace(
        market=market,
        liquidity=liquidity,
        zones=zones,
        structure=structure,
        reclaim=None,
    )
    candidates = crypto_layer_candidates(layer, timeframe="1h", observed=NOW)
    assert any(c.evidence_type == "LIQUIDITY_POOL" for c in candidates)
    assert all(c.source_provider == "monatise_crypto" for c in candidates)
    fib_candidates = [c for c in candidates if c.evidence_type.startswith("FIB_")]
    expected = [
        v
        for v in raw_fib.extension_levels
        if v.liquidity_confluence or v.zone_confluence or v.structure_confluence
    ]
    assert {c.price for c in fib_candidates} == {D(str(v.price)) for v in expected}
    # Construct independent already-qualified directional examples from actual engine levels.
    levels = sorted({c.price for c in candidates})
    for short in (False, True):
        entry = levels[-1] + 1 if short else levels[0] - 1
        stop = entry + D(".1") if short else entry - D(".1")
        result = build_plan(
            candidates=candidates,
            direction="short" if short else "long",
            entry=entry,
            stop=stop,
            now=NOW,
            expires_at=NOW + timedelta(minutes=15),
            config=config(max_relative_target_distance=D("1")),
        )
        assert all(
            (t.price < entry if short else t.price > entry) for t in result.targets
        )
        assert all(t.source_provider != "flashalpha" for t in result.targets)
        raw = {
            "symbol": "BTC",
            "classification": "trend",
            "direction": "short" if short else "long",
            "entry_confirmation_status": "confirmed",
            "entry": str(entry),
            "invalidation": str(stop),
            "target": 999999,
            "generated_at": NOW.isoformat(),
            "market_observed_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(minutes=15)).isoformat(),
            "interval": "1h",
        }
        adapted = apply_crypto_output_plan(
            raw,
            {
                "market_data": market,
                "liquidity": liquidity,
                "market_structure": structure,
                "supply_demand": zones,
            },
            config=config(max_relative_target_distance=D(1)),
            now=NOW,
        )
        assert adapted["take_profit_plan"] and adapted["target"] != 999999
        assert "TP1" in format_crypto_output_plan(adapted)


@pytest.mark.parametrize(
    "classification,confirmation",
    [("grid", "confirmed"), ("trend", "pending"), ("no_trade", "confirmed")],
)
def test_crypto_multi_tp_does_not_promote_unqualified_or_grid_outputs(
    classification, confirmation
):
    result = apply_crypto_output_plan(
        {
            "classification": classification,
            "direction": "long",
            "entry_confirmation_status": confirmation,
            "target": 999,
        },
        {},
        config=config(),
        now=NOW,
    )
    assert (
        result["take_profit_plan"] is None
        and result["targets"] == []
        and result["target"] is None
    )


@pytest.mark.parametrize(
    "command",
    [
        "/targets 123",
        "/management 123",
        "/tp1 123 2522",
        "/tp2 123 2532",
        "/tp3 123 2542",
        "/finaltp 123 2560",
    ],
)
def test_telegram_commands_reach_managed_plan(monkeypatch, command):
    from monatise.application.production import ProductionASGI
    from datetime import datetime

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr("monatise.application.production.datetime", FrozenDateTime)

    async def run():
        control, _, p = await execution_setup(monkeypatch)
        await open_position(control, p)
        app = ProductionASGI(SimpleNamespace(ftmo_master=control, environment={}))
        app._telegram_command_context = {
            "user_id": "42",
            "chat_type": "private",
            "chat_id": "42",
        }
        response = await app._handle_ftmo_telegram_command(command)
        assert "BLOCKED" not in response and "TP1" in response
        state, _ = await PositionManagementService(control).get(p["proposal_id"])
        assert bool(state.pending_proposal_id) == (
            command.split()[0] not in {"/targets", "/management"}
        )

    asyncio.run(run())


def test_crypto_fib_extensions_require_engine_confluence(monkeypatch):
    class Engine:
        def assess(self, request):
            assert request.extension_ratios == (1.272, 1.414, 1.618)
            return SimpleNamespace(
                primary_anchor=SimpleNamespace(structure_confidence=0.8),
                extension_levels=[
                    SimpleNamespace(
                        ratio=r,
                        price=p,
                        liquidity_confluence=True,
                        zone_confluence=False,
                        structure_confluence=False,
                    )
                    for r, p in [(1.272, 110), (1.414, 115), (1.618, 120)]
                ],
            )

    monkeypatch.setattr(
        "monatise.engines.fibonacci_liquidity.FibonacciLiquidityEngine", Engine
    )
    layer = SimpleNamespace(
        market=None,
        structure=SimpleNamespace(swing_highs=(), swing_lows=()),
        liquidity=SimpleNamespace(buy_side_levels=(), sell_side_levels=()),
        zones=SimpleNamespace(supply_zones=(), demand_zones=()),
        reclaim=None,
    )
    candidates = crypto_layer_candidates(layer, timeframe="4h", observed=NOW)
    assert [c.evidence_type for c in candidates] == [
        "FIB_1_272",
        "FIB_1_414",
        "FIB_1_618",
    ]
    result = build_plan(
        candidates=candidates,
        direction="long",
        entry=100,
        stop=95,
        now=NOW,
        expires_at=NOW + timedelta(minutes=15),
        config=config(),
    )
    assert len(result.targets) == 3


async def trigger_first(control, p, position, auto=False):
    manager = PositionManagementService(control)
    state, _ = await manager.get(p["proposal_id"])
    hb = heartbeat(multi_tp_version=1, positions=[position])
    hb["quotes"]["XAUUSD"].update(
        bid=str(state.plan.targets[0].price),
        ask=str(state.plan.targets[0].price + D(".2")),
    )
    response = await control.accept_bridge_heartbeat(hb, now=NOW)
    state, _ = await manager.get(p["proposal_id"])
    proposed = (await control.repository.proposal(state.pending_proposal_id))[0]
    return manager, state, proposed, hb, response


def test_manual_partial_requires_second_approval_and_kill_blocks_delivery(monkeypatch):
    async def run():
        control, _, p = await execution_setup(monkeypatch)
        position, _ = await open_position(control, p)
        manager, state, partial, hb, response = await trigger_first(
            control, p, position
        )
        assert partial["proposal_id"] in response["management_proposal_ids"]
        assert not partial.get("command_id")
        assert "TP1" in format_proposal(partial)
        command = await control.approve(partial["proposal_id"], "42", now=NOW)
        await control.repository.update_control(kill_switch=True)
        assert not await control.commands_for_bridge(now=NOW)
        await control.repository.update_control(kill_switch=False)
        assert (await control.commands_for_bridge(now=NOW))[0]["command_id"] == command[
            "command_id"
        ]

    asyncio.run(run())


def test_broker_rejection_and_uncertain_partial_are_not_retried(monkeypatch):
    async def run():
        control, _, p = await execution_setup(monkeypatch, auto=True)
        position, _ = await open_position(control, p)
        manager, state, partial, hb, _ = await trigger_first(control, p, position, True)
        command_id = partial["command_id"]
        await control.acknowledge(
            command_id,
            dict(
                status="rejected",
                broker_retcode="10014",
                message="invalid volume",
                submission_attempted=True,
            ),
        )
        await control.accept_bridge_heartbeat(hb, now=NOW)
        state, _ = await manager.get(p["proposal_id"])
        assert state.state == "MANAGEMENT_FAILED"
        assert state.plan.targets[0].closed_volume == 0
        count = len(
            await control.repository.store.list_namespace(control.repository.COMMANDS)
        )
        await control.accept_bridge_heartbeat(hb, now=NOW)
        assert (
            len(
                await control.repository.store.list_namespace(
                    control.repository.COMMANDS
                )
            )
            == count
        )

    asyncio.run(run())


def test_lost_acknowledgement_recovered_from_position_bound_deal(monkeypatch):
    async def run():
        control, _, p = await execution_setup(monkeypatch, auto=True)
        position, _ = await open_position(control, p)
        manager, state, partial, hb, _ = await trigger_first(control, p, position, True)
        volume = partial["volume"]
        command_id = partial["command_id"]
        hb["positions"] = [
            dict(position, volume=str(D(position["volume"]) - D(volume)))
        ]
        hb["deals"] = [deal(900, volume, comment="MNT:" + command_id[:16])]
        await control.accept_bridge_heartbeat(hb, now=NOW)
        state, _ = await manager.get(p["proposal_id"])
        assert (
            state.plan.targets[0].status == "HIT" and state.pending_proposal_id is None
        )
        command = (await control.repository.command(command_id))[0]
        assert (
            command["status"] == "reconciled"
            and command["reconciliation_source"] == "mt5_deal_history"
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "operation", ["tp", "tp1", "tp2", "tp3", "finaltp", "sl", "breakeven", "close"]
)
def test_manual_target_stop_and_close_update_durable_state_only_after_approval(
    monkeypatch, operation
):
    async def run():
        control, _, p = await execution_setup(monkeypatch)
        position, _ = await open_position(control, p)
        manager = PositionManagementService(control)
        before, _ = await manager.get(p["proposal_id"])
        if operation == "breakeven":
            favorable = heartbeat(multi_tp_version=1, positions=[position])
            favorable["quotes"]["XAUUSD"].update(bid="2505", ask="2505.2")
            await control.accept_bridge_heartbeat(favorable, now=NOW)
        value = {
            "tp": "2560",
            "finaltp": "2560",
            "tp1": "2522",
            "tp2": "2532",
            "tp3": "2542",
            "sl": "2495",
        }.get(operation)
        proposed = await control.create_management_proposal(
            actor="42", target_id="123", operation=operation, value=value
        )
        state, _ = await manager.get(p["proposal_id"])
        assert state.plan == before.plan and not proposed.get("command_id")
        assert "TP1" in await manager.describe("123")
        command = await control.approve(proposed["proposal_id"], "42", now=NOW)
        if operation in {"tp", "tp1", "tp2", "tp3", "finaltp"}:
            position = dict(position, tp=proposed["value"])
        elif operation in {"sl", "breakeven"}:
            position = dict(position, sl=value or position["price_open"])
        await control.acknowledge(
            command["command_id"],
            dict(
                status="reconciled",
                broker_retcode="10009",
                broker_ticket="555",
                submission_attempted=True,
            ),
        )
        hb = heartbeat(
            multi_tp_version=1,
            positions=[] if operation == "close" else [position],
            deals=[deal(111, position["volume"], "CLIENT")]
            if operation == "close"
            else [],
        )
        await control.accept_bridge_heartbeat(hb, now=NOW)
        state, _ = await manager.get(p["proposal_id"])
        if operation == "close":
            assert (
                state.state == "POSITION_CLOSED"
                and state.terminal_reason == "MANUALLY_CLOSED"
            )
        elif operation in {"sl", "breakeven"}:
            assert state.current_sl == D(value or position["price_open"])
        else:
            name = (
                state.plan.targets[-1].name
                if operation in {"tp", "finaltp"}
                else operation
            )
            assert next(t for t in state.plan.targets if t.name == name).price == D(
                value
            )
            assert state.original_plan == before.original_plan

    asyncio.run(run())


def test_reversed_manual_target_rejected_without_reserving_position(monkeypatch):
    async def run():
        control, _, p = await execution_setup(monkeypatch)
        position, _ = await open_position(control, p)
        with pytest.raises(ValueError):
            await control.create_management_proposal(
                actor="42", target_id="123", operation="tp2", value="2501"
            )
        state, _ = await PositionManagementService(control).get(p["proposal_id"])
        assert state.pending_proposal_id is None

    asyncio.run(run())


def test_stop_proposal_uses_fresh_structure_and_preserves_approval(monkeypatch):
    async def run():
        control, _, p = await execution_setup(monkeypatch, auto=True)
        # Enable the policy on the reviewed plan before opening, as production config would.
        control.configuration = replace(
            control.configuration,
            multi_tp=config(
                auto_partial_close=True, auto_breakeven=True, breakeven_mode="AFTER_TP1"
            ),
        )
        stored, version = await control.repository.proposal(p["proposal_id"])
        ladder = replace(
            TakeProfitPlan.from_dict(stored["take_profit_plan"]),
            breakeven_policy="AFTER_TP1",
        )
        stored.update(
            take_profit_plan=ladder.to_dict(), preview_plan_digest=ladder.digest()
        )
        await control.repository.update_proposal(p["proposal_id"], stored, version)
        position, _ = await open_position(control, stored)
        manager, state, partial, hb, _ = await trigger_first(
            control, stored, position, True
        )
        hb["positions"] = [
            dict(position, volume=str(D(position["volume"]) - D(partial["volume"])))
        ]
        hb["deals"] = [
            deal(701, partial["volume"], comment="MNT:" + partial["command_id"][:16])
        ]
        await manager.record_structure(
            "XAUUSD",
            dict(
                source="monatise.test.structure",
                confirmed=True,
                direction="long",
                observed_at=NOW.isoformat(),
            ),
        )
        result = await control.accept_bridge_heartbeat(hb, now=NOW)
        state, _ = await manager.get(p["proposal_id"])
        stop = (await control.repository.proposal(state.pending_proposal_id))[0]
        assert stop["operation"] == "sl" and stop["value"] == position["price_open"]
        assert stop["proposal_id"] in result["management_proposal_ids"]
        assert stop.get("command_id") is None

    asyncio.run(run())


def test_postgres_position_state_survives_connection_restart():
    import os
    from uuid import uuid4
    from monatise.application.persistence import connect_postgres_store

    if not os.getenv("MONATISE_TEST_DATABASE_URL"):
        pytest.skip("local integration Postgres required")

    async def run():
        state = managed()
        state.logical_trade_id = str(uuid4())
        state.apply_deal(deal(1), NOW, target_name="tp1")
        store, connection = await connect_postgres_store(
            os.environ["MONATISE_TEST_DATABASE_URL"]
        )
        try:
            await store.put(
                "multi_tp_recovery_test",
                state.logical_trade_id,
                state.to_dict(),
                expected_version=0,
            )
        finally:
            await connection.close()
        store, connection = await connect_postgres_store(
            os.environ["MONATISE_TEST_DATABASE_URL"]
        )
        try:
            record = await store.get("multi_tp_recovery_test", state.logical_trade_id)
            recovered = ManagedPosition.from_dict(record.value)
            assert (
                recovered.remaining_volume == D(".75")
                and recovered.plan.targets[0].status == "HIT"
            )
            recovered.apply_deal(deal(1), NOW, target_name="tp1")
            assert recovered.remaining_volume == D(".75")
            with pytest.raises(RuntimeError):
                await store.put(
                    "multi_tp_recovery_test",
                    state.logical_trade_id,
                    recovered.to_dict(),
                    expected_version=0,
                )
        finally:
            await connection.close()

    asyncio.run(run())


@pytest.mark.parametrize("allocations", ["40,30,20,10", "20,20,20,40"])
def test_alternative_profiles_normalize_two_destinations(allocations):
    policy = MultiTPConfiguration.from_environment(
        {"MULTI_TP_ALLOCATIONS": allocations}
    )
    result = build_plan(
        candidates=[evidence(110), evidence(120)],
        direction="long",
        entry=100,
        stop=95,
        now=NOW,
        expires_at=NOW + timedelta(minutes=30),
        config=policy,
    )
    assert sum(t.allocation_pct for t in result.targets) == 100
    assert (
        result.targets[0].allocation_pct
        == policy.allocations[0] / sum(policy.allocations[:2]) * 100
    )


def test_same_provider_duplicate_is_not_independent_confirmation():
    result = build_plan(
        candidates=[evidence(110), evidence("110.02")],
        direction="long",
        entry=100,
        stop=95,
        now=NOW,
        expires_at=NOW + timedelta(minutes=30),
        config=config(),
    )
    assert result.targets[0].agreement == ()


def test_reservation_recovers_after_crash_before_proposal_save(monkeypatch):
    async def run():
        control, _, p = await execution_setup(monkeypatch)
        position, _ = await open_position(control, p)
        manager = PositionManagementService(control)
        original_save = control.repository.save_proposal
        crashed = False

        async def crash_once(proposal):
            nonlocal crashed
            if proposal.get("operation") == "partial_close" and not crashed:
                crashed = True
                raise RuntimeError(
                    "simulated process failure after durable reservation"
                )
            return await original_save(proposal)

        monkeypatch.setattr(control.repository, "save_proposal", crash_once)
        hb = heartbeat(multi_tp_version=1, positions=[position])
        hb["quotes"]["XAUUSD"].update(bid="2521", ask="2521.2")
        await control.accept_bridge_heartbeat(hb, now=NOW)
        reserved, _ = await manager.get(p["proposal_id"])
        assert reserved.pending_intent and not await control.repository.proposal(
            reserved.pending_proposal_id
        )
        await control.accept_bridge_heartbeat(hb, now=NOW)
        recovered = (await control.repository.proposal(reserved.pending_proposal_id))[0]
        assert recovered == reserved.pending_intent
        command = await control.approve(recovered["proposal_id"], "42", now=NOW)
        with pytest.raises(FTMOMasterError):
            await control.approve(recovered["proposal_id"], "42", now=NOW)
        assert (
            len(
                [
                    c
                    for c in await control.repository.pending_commands()
                    if c["operation"] == "partial_close"
                ]
            )
            == 1
        )
        assert command["payload"]["scope_approval_id"]

    asyncio.run(run())


def test_closed_between_heartbeats_reconstructs_original_and_final_deals(monkeypatch):
    async def run():
        control, _, p = await execution_setup(monkeypatch)
        command = await control.approve(p["proposal_id"], "42", now=NOW)
        volume = command["payload"]["volume"]
        opening = dict(
            deal_id="9",
            position_id="1001",
            order_id="123",
            entry="in",
            volume=volume,
            price=command["payload"]["entry"],
            commission="-1",
            profit="0",
            time=NOW.isoformat(),
            comment="MNT:" + command["command_id"][:16],
        )
        closing = deal(10, volume, "TP")
        await control.accept_bridge_heartbeat(
            heartbeat(
                multi_tp_version=1, positions=[], deals=[closing, opening, opening]
            ),
            now=NOW,
        )
        state, _ = await PositionManagementService(control).get(p["proposal_id"])
        assert state.state == "POSITION_CLOSED"
        assert state.terminal_reason == "FINAL_TARGET_HIT"
        assert state.realized_pnl == D("8.9")
        assert state.plan.targets[-1].realized_pnl == D("8.9")
        assert state.plan.targets[0].status == "BYPASSED"
        assert len(state.seen_deals) == 2

    asyncio.run(run())


def test_definitively_rejected_partial_does_not_block_manual_close(monkeypatch):
    async def run():
        control, _, p = await execution_setup(monkeypatch, auto=True)
        position, _ = await open_position(control, p)
        manager, _, partial, hb, _ = await trigger_first(control, p, position, True)
        await control.acknowledge(
            partial["command_id"],
            dict(status="rejected", broker_retcode="10014", submission_attempted=True),
        )
        await control.accept_bridge_heartbeat(hb, now=NOW)
        state, _ = await manager.get(p["proposal_id"])
        assert state.state == "MANAGEMENT_FAILED" and state.pending_proposal_id is None
        proposal = await manager.manual_proposal(
            actor="42", ticket="123", operation="close", value=None, now=NOW
        )
        command = await control.approve(proposal["proposal_id"], "42", now=NOW)
        assert command["operation"] == "close"

    asyncio.run(run())


def test_structure_is_converted_before_protective_stop_policy(monkeypatch):
    async def run():
        control, _, _ = await execution_setup(monkeypatch)
        manager = PositionManagementService(control)
        evidence = dict(
            source="monatise.hierarchy",
            confirmed=True,
            direction="long",
            observed_at=NOW.isoformat(),
            confirmed_higher_low="2600",
            atr="10",
        )
        await manager.record_structure(
            "XAUUSD", evidence, analysis_entry="2650", now=NOW
        )
        record = await control.repository.store.get(
            "ftmo_management_structure_v1", "XAUUSD"
        )
        ratio = D("2500.20") / D(2650)
        assert D(record.value["confirmed_higher_low"]) == D(2600) * ratio
        assert D(record.value["atr"]) == D(10) * ratio
        assert record.value["analysis_evidence"]["confirmed_higher_low"] == "2600"

    asyncio.run(run())


@pytest.mark.parametrize("gate", ["route", "automatic"])
def test_disabling_partial_gate_blocks_already_queued_delivery(monkeypatch, gate):
    async def run():
        control, _, p = await execution_setup(monkeypatch, auto=True)
        position, _ = await open_position(control, p)
        _, _, partial, _, _ = await trigger_first(control, p, position, True)
        policy = control.configuration.multi_tp
        control.configuration = replace(
            control.configuration,
            multi_tp=replace(
                policy,
                routes=frozenset() if gate == "route" else policy.routes,
                auto_partial_close=False if gate == "automatic" else True,
            ),
        )
        assert partial["automatic_management"]
        assert not await control.commands_for_bridge(now=NOW)

    asyncio.run(run())


def test_manual_intermediate_target_revalidated_against_current_market(monkeypatch):
    async def run():
        control, _, p = await execution_setup(monkeypatch)
        position, _ = await open_position(control, p)
        manager = PositionManagementService(control)
        proposal = await manager.manual_proposal(
            actor="42", ticket="123", operation="tp1", value="2522", now=NOW
        )
        hb = heartbeat(multi_tp_version=1, positions=[position])
        hb["quotes"]["XAUUSD"].update(bid="2523", ask="2523.2")
        await control.accept_bridge_heartbeat(hb, now=NOW)
        with pytest.raises(FTMOMasterError, match="modified target"):
            await control.approve(proposal["proposal_id"], "42", now=NOW)

    asyncio.run(run())


def test_real_postgres_and_redis_process_restart_recovers_partial_ladder():
    """Own isolated processes only; never restarts a configured application DB."""
    import os
    import socket
    import tempfile
    from monatise.application.persistence import connect_postgres_store
    from redis import Redis

    pg_bin = Path(
        os.getenv("MONATISE_TEST_POSTGRES_BIN", "/opt/homebrew/opt/postgresql@18/bin")
    )
    redis_bin = shutil.which("redis-server")
    if not (pg_bin / "initdb").is_file() or not redis_bin:
        pytest.skip(
            "isolated restart test requires local PostgreSQL and Redis binaries"
        )

    def free_port():
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    pg_port, redis_port = free_port(), free_port()
    state = managed()
    state.apply_deal(deal(1), NOW, target_name="tp1")
    state.pending_proposal_id = "durable-reservation"
    state.pending_intent = {
        "proposal_id": "durable-reservation",
        "operation": "partial_close",
        "managed_target": "tp2",
    }
    dsn = f"postgresql://multi_tp_restart@127.0.0.1:{pg_port}/postgres"
    with tempfile.TemporaryDirectory(prefix="mnt-tp-") as directory:
        data = str(Path(directory) / "postgres")
        log = str(Path(directory) / "postgres.log")
        subprocess.run(
            [
                str(pg_bin / "initdb"),
                "-D",
                data,
                "-U",
                "multi_tp_restart",
                "-A",
                "trust",
                "--no-locale",
            ],
            check=True,
            capture_output=True,
        )
        started_pg = False
        redis_process = None

        def pg(action):
            args = [str(pg_bin / "pg_ctl"), "-D", data, "-w", action]
            args += (
                ["-o", f"-h 127.0.0.1 -p {pg_port} -k {directory}", "-l", log]
                if action == "start"
                else ["-m", "fast"]
            )
            subprocess.run(args, check=True, capture_output=True)

        def start_redis():
            process = subprocess.Popen(
                [
                    redis_bin,
                    "--bind",
                    "127.0.0.1",
                    "--port",
                    str(redis_port),
                    "--save",
                    "",
                    "--appendonly",
                    "no",
                    "--dir",
                    directory,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            import time

            for _ in range(100):
                try:
                    if Redis(host="127.0.0.1", port=redis_port).ping():
                        return process
                except ConnectionError:
                    pass
                except Exception:
                    if process.poll() is not None:
                        raise
                time.sleep(0.02)
            process.terminate()
            process.wait(timeout=5)
            raise AssertionError("isolated Redis did not start")

        async def persist():
            store, connection = await connect_postgres_store(dsn)
            try:
                await connection.execute(
                    Path(
                        "deploy/migrations/001_application_orchestration.sql"
                    ).read_text()
                )
                await store.put(
                    "ftmo_position_management_v1",
                    state.logical_trade_id,
                    state.to_dict(),
                    expected_version=0,
                )
            finally:
                await connection.close()

        async def recover():
            store, connection = await connect_postgres_store(dsn)
            try:
                record = await store.get(
                    "ftmo_position_management_v1", state.logical_trade_id
                )
                recovered = ManagedPosition.from_dict(record.value)
                assert recovered.remaining_volume == D(".75")
                assert recovered.plan.targets[0].status == "HIT"
                assert recovered.pending_intent == state.pending_intent
                recovered.apply_deal(deal(1), NOW, target_name="tp1")
                assert recovered.remaining_volume == D(".75")
                with pytest.raises(RuntimeError):
                    await store.put(
                        "ftmo_position_management_v1",
                        state.logical_trade_id,
                        recovered.to_dict(),
                        expected_version=0,
                    )
            finally:
                await connection.close()

        try:
            pg("start")
            started_pg = True
            redis_process = start_redis()
            cache = Redis(host="127.0.0.1", port=redis_port)
            cache.set("transient-target-cache", "not-authoritative")
            asyncio.run(persist())
            cache.shutdown(nosave=True)
            redis_process.wait(timeout=5)
            pg("stop")
            started_pg = False
            pg("start")
            started_pg = True
            redis_process = start_redis()
            assert cache.get("transient-target-cache") is None
            asyncio.run(recover())
        finally:
            if redis_process is not None and redis_process.poll() is None:
                redis_process.terminate()
                redis_process.wait(timeout=5)
            if started_pg:
                pg("stop")


@pytest.mark.parametrize("enabled", [True, False])
def test_on_demand_crypto_runtime_preserves_feature_gate_and_uses_ladder(
    monkeypatch, enabled
):
    from datetime import datetime, timezone
    from monatise.application.deployment import OrchestrationRuntime

    now = datetime.now(timezone.utc)
    raw = {
        "symbol": "BTC",
        "classification": "trend",
        "direction": "long",
        "entry": 100,
        "invalidation": 95,
        "target": 999,
        "entry_confirmation_status": "confirmed",
        "interval": "1h",
        "market_observed_at": now.isoformat(),
        "generated_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=15)).isoformat(),
    }
    outputs = {
        "market_data": object(),
        "liquidity": object(),
        "supply_demand": object(),
        "market_structure": SimpleNamespace(swing_lows=(), swing_highs=()),
    }
    result = SimpleNamespace(
        context=SimpleNamespace(outputs=outputs), symbol="BTC", run_id="runtime-test"
    )

    async def run_analysis(request):
        return result

    monkeypatch.setattr(
        "monatise.application.deployment.sanitized_result", lambda result: dict(raw)
    )
    monkeypatch.setattr(
        "monatise.application.target_evidence.crypto_layer_candidates",
        lambda *args, **kwargs: [
            replace(evidence(v), observed_at=now) for v in (110, 115, 120)
        ],
    )
    runtime = OrchestrationRuntime(
        environment={
            "MULTI_TP_ENABLED": str(enabled),
            "MULTI_TP_CRYPTO_ENABLED": str(enabled),
        },
        application=SimpleNamespace(orchestrator=SimpleNamespace(run=run_analysis)),
    )
    actual = asyncio.run(
        runtime.analyse("BTC", source="monatise.telegram.on_demand", notify=False)
    )
    assert bool(actual.get("take_profit_plan")) == enabled
    assert actual["target"] == (120 if enabled else 999)
    assert ("take_profit_plan" in outputs) == enabled


@pytest.mark.parametrize("final_fill", [False, True])
def test_stop_confirmation_lag_and_final_fill_race_recover(monkeypatch, final_fill):
    async def run():
        control, _, p = await execution_setup(monkeypatch)
        position, _ = await open_position(control, p)
        manager = PositionManagementService(control)
        proposal = await manager.manual_proposal(
            actor="42", ticket="123", operation="sl", value="2495", now=NOW
        )
        command = await control.approve(proposal["proposal_id"], "42", now=NOW)
        await control.acknowledge(
            command["command_id"],
            dict(
                status="reconciled", broker_retcode="10009", submission_attempted=True
            ),
        )
        await control.accept_bridge_heartbeat(
            heartbeat(multi_tp_version=1, positions=[position]), now=NOW
        )
        state, _ = await manager.get(p["proposal_id"])
        assert state.state == "RECONCILIATION_REQUIRED"
        hb = heartbeat(
            multi_tp_version=1,
            positions=[] if final_fill else [dict(position, sl="2495")],
            deals=[deal(555, position["volume"], "TP")] if final_fill else [],
        )
        await control.accept_bridge_heartbeat(hb, now=NOW)
        state, _ = await manager.get(p["proposal_id"])
        assert state.state == ("POSITION_CLOSED" if final_fill else "OPEN")
        assert state.pending_proposal_id is None
        assert "No managed" not in await manager.describe("123")

    asyncio.run(run())
