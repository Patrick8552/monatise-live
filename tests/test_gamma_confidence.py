import asyncio
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest

from monatise.application.gamma_confidence import (
    CHECKS,
    confidence_evidence,
    independent_checks,
    eligible_uncertified,
)
from monatise.application.gamma_reconstruction import GammaQualityError
from monatise.application.ftmo_master import FTMOMasterError, format_proposal
from monatise.application.hierarchy.approval import SIGNALS
from tests.shared_hierarchy_fixtures import persist_proof
from tests.test_waiting_entry import NOW, prepare, submitted
from tests.test_gamma_evidence import primary_context, resolve, GammaEvidenceLadder


def unavailable(symbol="AAPL", now=NOW):
    return {
        "version": "independent-gamma-v1",
        "state": "UNCERTIFIED",
        "symbol": symbol,
        "gamma_flip": None,
        "degradation_allowed": True,
        "as_of": now.isoformat(),
        "expires_at": (now + timedelta(seconds=90)).isoformat(),
        "quarantined_primary": {
            "value": 322.704,
            "quality": "sensitive_root",
            "trusted": False,
        },
    }


def full_checks():
    return {key: True for key in CHECKS}


async def degraded_proof(control, symbol, now, **kwargs):
    proof = await persist_proof(control, symbol, now, **kwargs)
    gamma = unavailable(symbol, now)
    confidence = confidence_evidence(
        gamma,
        strategy="hierarchy-shadow-v1",
        symbol=symbol,
        now=now,
        checks=full_checks(),
    )
    proof["evidence_bundle"].update(
        gamma_evidence=gamma, confidence_evidence=confidence
    )
    record = await control.repository.store.get(
        SIGNALS, proof["evidence_bundle"]["bundle_id"]
    )
    await control.repository.store.put(
        SIGNALS,
        record.key,
        {
            **record.value,
            "evidence": deepcopy(proof["evidence_bundle"]),
            "expires_at": gamma["expires_at"],
        },
        expected_version=record.version,
    )
    return proof


@pytest.mark.parametrize("missing", CHECKS)
def test_every_independent_check_is_required(missing):
    checks = full_checks()
    checks[missing] = False
    with pytest.raises(GammaQualityError, match="independent_confluence"):
        confidence_evidence(
            unavailable(),
            strategy="hierarchy-shadow-v1",
            symbol="AAPL",
            now=NOW,
            checks=checks,
        )


@pytest.mark.parametrize("direction,fib", [("long", "bullish"), ("short", "bearish")])
def test_confluence_requires_confirmed_liquidity_and_aligned_fibonacci(direction, fib):
    result = {
        "signal_core_evidence": full_checks(),
        "liquidity": {"confirmed_sweep": True},
        "trigger": {"confirmed_break": True},
        "fibonacci": {"15m": {"has_valid_anchor": True, "direction": fib}},
    }
    assert all(independent_checks(result, direction=direction).values())
    result["liquidity"] = {"possible_sweep": True}
    assert not independent_checks(result, direction=direction)["liquidity"]
    result["fibonacci"]["15m"]["direction"] = (
        "bearish" if fib == "bullish" else "bullish"
    )
    assert not independent_checks(result, direction=direction)["fibonacci"]


@pytest.mark.parametrize("strategy", ["gamma-primary-v1", "unknown", ""])
def test_gamma_primary_and_unknown_strategies_still_require_certification(strategy):
    assert not eligible_uncertified(
        unavailable(), strategy=strategy, symbol="AAPL", now=NOW
    )
    with pytest.raises(GammaQualityError):
        confidence_evidence(
            unavailable(),
            strategy=strategy,
            symbol="AAPL",
            now=NOW,
            checks=full_checks(),
        )


@pytest.mark.parametrize("status", ["stored_sign_mismatch", "unknown"])
def test_provider_integrity_errors_are_not_confidence_downgrades(status):
    proof, _, _ = resolve(GammaEvidenceLadder(), primary_context(status))
    assert not proof["degradation_allowed"]


def test_half_monetary_risk_persists_through_approval_delivery_and_pending(monkeypatch):
    monkeypatch.setattr("tests.test_waiting_entry.persist_proof", degraded_proof)

    async def run():
        control, store, proposal, payload, command = await submitted(monkeypatch)
        assert proposal["risk_allocation"]["risk_multiplier"] == "0.50"
        assert Decimal(proposal["risk_amount"]) == Decimal("150")
        assert Decimal(proposal["volume"]) == Decimal("0.15")
        assert "REDUCED CONFIDENCE" in format_proposal(proposal)
        assert "0.50× standard allocation" in format_proposal(proposal)
        assert "322.704" not in format_proposal(proposal)
        assert command["risk_policy"]["risk_allocation"] == proposal["risk_allocation"]
        assert Decimal(command["risk_policy"]["actual_risk_amount"]) == 150
        assert (await control.accept_bridge_heartbeat(payload, now=NOW))[
            "pending_entry_leases"
        ].startswith("7788|")
        saved, version = await control.repository.proposal(proposal["proposal_id"])
        saved["risk_allocation"]["risk_multiplier"] = "1"
        await control.repository.update_proposal(
            proposal["proposal_id"], saved, version
        )
        assert (await control.accept_bridge_heartbeat(payload, now=NOW))[
            "pending_entry_leases"
        ] == ""

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutation", ["factor", "base", "missing_allocation", "missing_proof", "proof"]
)
@pytest.mark.parametrize("stage", ["publication", "approval", "delivery"])
def test_modified_risk_cannot_escape_durable_evidence(monkeypatch, mutation, stage):
    monkeypatch.setattr("tests.test_waiting_entry.persist_proof", degraded_proof)

    async def run():
        control, store, proposal, _, _ = await prepare(monkeypatch)
        if stage == "delivery":
            await control.approve(proposal["proposal_id"], "42", now=NOW)
        saved, version = await control.repository.proposal(proposal["proposal_id"])
        saved = deepcopy(saved)
        if mutation == "factor":
            saved["risk_allocation"]["risk_multiplier"] = "1"
        if mutation == "base":
            saved["risk_allocation"]["normal_risk_fraction"] = "0.1"
        if mutation == "missing_allocation":
            saved.pop("risk_allocation")
        if mutation == "missing_proof":
            saved.pop("evidence_bundle")
        if mutation == "proof":
            saved["evidence_bundle"]["evidence_bundle"]["confidence_evidence"][
                "risk_multiplier"
            ] = "1"
        await control.repository.update_proposal(
            proposal["proposal_id"], saved, version
        )
        if stage == "delivery":
            assert await control.commands_for_bridge(now=NOW) == ()
        else:
            with pytest.raises(FTMOMasterError):
                if stage == "publication":
                    await control.validate_proposal_publication(saved, now=NOW)
                else:
                    await control.approve(proposal["proposal_id"], "42", now=NOW)

    asyncio.run(run())


@pytest.mark.parametrize("stop", ["90", "95", "99"])
def test_risk_reduction_precedes_stop_distance_and_lot_rounding(monkeypatch, stop):
    async def run():
        control, _, _, _, _ = await prepare(monkeypatch)
        standard = await control._validated_open_fields(
            symbol="AAPL",
            side="buy",
            order_type="limit",
            entry="100",
            stop_loss=stop,
            take_profit="125",
            now=NOW,
            risk_fraction_limit="0.001",
        )
        reduced = await control._validated_open_fields(
            symbol="AAPL",
            side="buy",
            order_type="limit",
            entry="100",
            stop_loss=stop,
            take_profit="125",
            now=NOW,
            risk_fraction_limit="0.001",
            risk_multiplier=".5",
        )
        assert Decimal(reduced["risk_amount"]) <= 5
        assert Decimal(reduced["volume"]) <= Decimal(standard["volume"])

    if stop == "90":
        # $5 cannot buy the broker's .01 lot minimum with a $10 stop: reject.
        with pytest.raises(FTMOMasterError, match="minimum"):
            asyncio.run(run())
    else:
        asyncio.run(run())


@pytest.mark.parametrize(
    "confirmed_sweep,recertified_flip", [(True, 130), (True, 150), (False, 130)]
)
def test_real_hierarchy_enforces_degraded_gate_and_recertification_identity(
    monkeypatch, confirmed_sweep, recertified_flip
):
    from dataclasses import replace
    from monatise.application.hierarchy.assets import AssetHierarchyAnalysis
    from monatise.application.hierarchy.evaluator import HierarchyLayerEvaluator
    from monatise.application.ftmo_registry import FTMO_REGISTRY
    from monatise.engines.liquidity_sweep.models import (
        SweepEvent,
        SweepDirection,
        SweepStatus,
    )
    from monatise.application.gamma_evidence import certificate
    from tests.test_shared_timeframe_hierarchy import directional_layers, Alpaca
    from tests.test_ftmo_master import service

    directional_layers(monkeypatch)
    original = HierarchyLayerEvaluator._analyse_structure

    def assess(self, snapshot, regime):
        layer = original(self, snapshot, regime)
        if layer:
            layer = replace(
                layer,
                structure=replace(
                    layer.structure,
                    swing_lows=((80, layer.structure.swing_lows[0][1]),),
                    swing_highs=((95, layer.structure.swing_highs[0][1]),),
                ),
            )
        if layer and confirmed_sweep:
            event = SweepEvent(
                layer.liquidity.nearest_buy_side,
                SweepDirection.SELL_SIDE_TAKEN,
                SweepStatus.CONFIRMED,
                99,
                139,
                140,
                0.001,
                0.8,
                True,
                (),
            )
            layer = replace(
                layer,
                sweep=replace(layer.sweep, events=(event,), strongest_event=event),
            )
        return layer

    monkeypatch.setattr(HierarchyLayerEvaluator, "_analyse_structure", assess)

    async def run():
        control, store = service()
        engine = AssetHierarchyAnalysis(alpaca=Alpaca(), master=control)
        instrument = FTMO_REGISTRY.resolve("AAPL")
        gamma = unavailable()
        for seconds in (0, 6, 12, 18):
            result = await engine.analyse(
                instrument,
                context={"gamma_evidence": gamma, "gamma_flip": None},
                now=NOW + timedelta(seconds=seconds),
            )
        if not confirmed_sweep:
            assert not result["publication_valid"]
            assert (
                "uncertified_gamma_requires_full_independent_confluence"
                in result["reasons"]
            )
            return
        assert result["publication_valid"], {
            k: result.get(k)
            for k in (
                "reasons",
                "signal_core_evidence",
                "liquidity",
                "fibonacci",
                "trigger",
            )
        }
        assert result["confidence_evidence"]["risk_multiplier"] == "0.50"
        assert result["signal_core_score"] == 4
        assert (
            result["gamma_evidence"]
            if "gamma_evidence" in result
            else result["evidence_bundle"]["gamma_evidence"] == gamma
        )
        first = result["evidence_bundle"]["bundle_id"]
        certified = certificate(
            "CERTIFIED_PRIMARY",
            {
                "gamma_flip": recertified_flip,
                "underlying_price": 140.2,
                "provider": "flashalpha",
                "as_of": (NOW + timedelta(seconds=19)).isoformat(),
                "expires_at": (NOW + timedelta(seconds=100)).isoformat(),
            },
            symbol="AAPL",
            attempts=[],
            quarantined=gamma["quarantined_primary"],
        )
        refreshed = AssetHierarchyAnalysis(alpaca=Alpaca(), master=control)
        for seconds in (24, 30, 36, 42):
            result = await refreshed.analyse(
                instrument,
                context={
                    "gamma_evidence": certified,
                    "symbol": "AAPL",
                    "gamma_flip": recertified_flip,
                    "underlying_price": 140.2,
                    "net_gex": 1,
                },
                now=NOW + timedelta(seconds=seconds),
            )
        if recertified_flip > 140.2:
            assert not result["publication_valid"]
            assert (
                "positioning_context_conflicts_with_shared_hierarchy"
                in result["reasons"]
            )
            return
        assert result["publication_valid"], {
            k: result.get(k)
            for k in (
                "reasons",
                "signal_core_evidence",
                "liquidity",
                "fibonacci",
                "trigger",
            )
        }
        assert (
            result["confidence_state"] == "NORMAL" and result["risk_multiplier"] == "1"
        )
        assert result["evidence_bundle"]["bundle_id"] != first
        # A fresh certified identity supersedes the old setup, never rewrites it.
        assert (await store.get(SIGNALS, first)).value["evidence"][
            "confidence_evidence"
        ]["risk_multiplier"] == "0.50"

    asyncio.run(run())


def test_half_risk_applies_after_remaining_drawdown_capacity(monkeypatch):
    async def run():
        control, _, _, payload, _ = await prepare(monkeypatch)
        payload["daily_loss_limit"] = "80"
        await control.accept_bridge_heartbeat(payload, now=NOW)
        fields = await control._validated_open_fields(
            symbol="AAPL",
            side="buy",
            order_type="limit",
            entry="100",
            stop_loss="90",
            take_profit="125",
            now=NOW,
            risk_multiplier=".5",
        )
        assert Decimal(fields["risk_amount"]) == 40

    asyncio.run(run())
