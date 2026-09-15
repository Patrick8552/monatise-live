import asyncio
from copy import deepcopy
from datetime import timedelta
import pytest
from monatise.application.gamma_evidence import certificate
from monatise.application.hierarchy.approval import SIGNALS, validate_shared_evidence
from monatise.application.ftmo_registry import FTMO_REGISTRY
from monatise.application.ftmo_master import FTMOMasterError, format_proposal
from monatise.application.workflows import TelegramNotifier
from tests.test_waiting_entry import prepare, NOW
from tests.shared_hierarchy_fixtures import persist_proof
from tests.test_trade_publication import Transport


async def gamma_proof(control, symbol, now, **kwargs):
    proof = await persist_proof(control, symbol, now, **kwargs)
    gamma = certificate(
        "CERTIFIED_RECONSTRUCTED",
        {
            "gamma_flip": 98.75,
            "underlying_price": 105,
            "provider": "independent_test_chain",
            "as_of": now.isoformat(),
            "expires_at": (now + timedelta(seconds=60)).isoformat(),
            "methodology": "black_scholes_constant_iv_v1",
            "quality": {"oi_coverage": 1},
        },
        symbol=symbol,
        attempts=[],
        quarantined={"value": 98.74, "quality": "sensitive_root", "trusted": False},
    )
    proof["evidence_bundle"]["gamma_evidence"] = gamma
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


def test_gamma_proof_survives_storage_telegram_approval_and_execution_intent(
    monkeypatch,
):
    monkeypatch.setattr("tests.test_waiting_entry.persist_proof", gamma_proof)

    async def run():
        control, store, proposal, payload, _ = await prepare(monkeypatch)
        gamma = proposal["evidence_bundle"]["evidence_bundle"]["gamma_evidence"]
        assert gamma["state"] == "CERTIFIED_RECONSTRUCTED"
        notifier = TelegramNotifier(Transport(), "42", proposal_service=control)
        await notifier.trade_proposal(
            format_proposal(proposal), proposal["proposal_id"]
        )
        saved = (await control.repository.proposal(proposal["proposal_id"]))[0]
        assert saved["approval_keyboard_attached"]
        assert "98.7500 — CERTIFIED_RECONSTRUCTED" in format_proposal(saved)
        command = await control.approve(proposal["proposal_id"], "42", now=NOW)
        assert (
            command["analysis_provenance"]["evidence_bundle"]["evidence_bundle"][
                "gamma_evidence"
            ]
            == gamma
        )
        assert (
            command["payload"]["side"] == "buy"
            and command["payload"]["order_type"] == "limit"
        )
        assert proposal["quote_ask"] == "105" and command["payload"]["entry"] == "100"
        await control.commands_for_bridge(now=NOW)
        payload["orders"] = [
            dict(
                ticket="7788",
                symbol=proposal["symbol"],
                magic="26082501",
                type=2,
                comment="MNP:" + command["command_id"][:16],
                price_open=proposal["entry"],
                sl=proposal["stop_loss"],
                tp=proposal["take_profit"],
                volume=proposal["volume"],
                expiration_epoch=command["payload"]["pending_native_expires_epoch"],
            )
        ]
        result = await control.accept_bridge_heartbeat(payload, now=NOW)
        assert result["pending_entry_leases"].startswith("7788|")
        later = NOW + timedelta(seconds=61)
        payload["quotes"]["AAPL"]["timestamp"] = later.isoformat()
        result = await control.accept_bridge_heartbeat(payload, now=later)
        assert result["pending_entry_leases"] == ""
        assert (await control.repository.proposal(proposal["proposal_id"]))[0].get(
            "pending_cancellation_reason"
        )

    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["changed", "expired", "uncertified"])
def test_gamma_proof_rejected_before_any_order_on_change_or_expiry(
    monkeypatch, mutation
):
    monkeypatch.setattr("tests.test_waiting_entry.persist_proof", gamma_proof)

    async def run():
        control, store, proposal, _, _ = await prepare(monkeypatch)
        proof = deepcopy(proposal["evidence_bundle"])
        at = NOW
        if mutation == "changed":
            proof["evidence_bundle"]["gamma_evidence"]["gamma_flip"] = 322.704
        if mutation == "uncertified":
            proof["evidence_bundle"]["gamma_evidence"]["state"] = "UNCERTIFIED"
        if mutation == "expired":
            at += timedelta(seconds=61)
        with pytest.raises(ValueError):
            await validate_shared_evidence(
                store, FTMO_REGISTRY.resolve("AAPL"), proof, at
            )
        if mutation != "expired":
            saved, version = await control.repository.proposal(proposal["proposal_id"])
            await control.repository.update_proposal(
                proposal["proposal_id"], {**saved, "evidence_bundle": proof}, version
            )
        with pytest.raises(FTMOMasterError):
            await control.approve(proposal["proposal_id"], "42", now=at)
        assert await control.repository.pending_commands() == ()

    asyncio.run(run())
