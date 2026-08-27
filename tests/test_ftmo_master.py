from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from monatise.application.ftmo_master import (
    CommandStatus,
    FTMOBridgeAuthenticator,
    FTMOMasterConfiguration,
    FTMOMasterControlService,
    FTMOMasterError,
    FTMOMasterRepository,
)
from monatise.application.persistence import DurableRecord
from monatise.application.production import ProductionASGI


NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.values = {}
        self.streams = {}

    async def get(self, namespace, key):
        return self.values.get((namespace, key))

    async def put(self, namespace, key, value, *, expected_version=None):
        current = self.values.get((namespace, key))
        if current is None and expected_version not in {None, 0}:
            raise RuntimeError("version conflict")
        if current is not None and expected_version is not None and expected_version != current.version:
            raise RuntimeError("version conflict")
        version = 1 if current is None else current.version + 1
        record = DurableRecord(namespace, key, value, version)
        self.values[(namespace, key)] = record
        return record

    async def list_namespace(self, namespace):
        return tuple(value for (item_namespace, _), value in self.values.items() if item_namespace == namespace)

    async def append(self, stream, value):
        self.streams.setdefault(stream, []).append(value)


def active_environment(**changes):
    value = {
        "FTMO_ACCOUNT_ID": "12345678",
        "FTMO_SERVER": "FTMO-Server",
        "FTMO_ACCOUNT_CURRENCY": "USD",
        "FTMO_EXECUTION_ENABLED": "true",
        "FTMO_EXECUTION_ENVIRONMENT": "master",
        "FTMO_MASTER_ACCOUNT_APPROVED": "true",
        "FTMO_TELEGRAM_EXECUTION_ARMED": "true",
        "FTMO_AUTONOMOUS_EXECUTION": "false",
        "FTMO_TELEGRAM_CONFIRMATION_REQUIRED": "true",
        "FTMO_TELEGRAM_AUTHORIZED_USER_IDS": "42",
        "FTMO_BRIDGE_SECRET": "a" * 64,
    }
    value.update(changes)
    return value


def heartbeat(**changes):
    value = {
        "account_id": "12345678",
        "server": "FTMO-Server",
        "currency": "USD",
        "balance": "10000",
        "equity": "10000",
        "daily_start_equity": "10000",
        "daily_loss_limit": "500",
        "total_loss_limit": "1000",
        "terminal_connected": True,
        "trade_allowed": True,
        "ea_attached": True,
        "terminal_build": "6140",
        "ea_version": "1.0.0",
        "positions": [],
        "orders": [],
        "quotes": {
            "XAUUSD": {
                "bid": "2500.00", "ask": "2500.20", "timestamp": NOW.isoformat(),
                "digits": 2, "tick_size": "0.01", "tick_value": "1",
                "volume_min": "0.01", "volume_max": "50", "volume_step": "0.01", "stops_level": "50",
            }
        },
    }
    value.update(changes)
    return value


def service(environment=None):
    store = Store()
    configuration = FTMOMasterConfiguration.from_environment(environment or active_environment())
    return FTMOMasterControlService(configuration, FTMOMasterRepository(store)), store


def test_configuration_requires_independent_master_gates_and_forbids_autonomy():
    disabled = FTMOMasterConfiguration.from_environment({})
    assert disabled.activation_configured is False
    assert disabled.public_status()["account"] is None
    configured = FTMOMasterConfiguration.from_environment(active_environment())
    assert configured.activation_configured is True
    assert configured.public_status()["account"] == "****5678"
    with pytest.raises(ValueError, match="autonomous"):
        FTMOMasterConfiguration.from_environment(active_environment(FTMO_AUTONOMOUS_EXECUTION="true"))
    with pytest.raises(ValueError, match="bridge secret"):
        FTMOMasterConfiguration.from_environment(active_environment(FTMO_BRIDGE_SECRET=""))


def test_bridge_hmac_rejects_tampering_staleness_and_replay_nonce():
    secret = "secret"
    body = b'{"ok":true}'
    timestamp = str(int(NOW.timestamp()))
    nonce = "0123456789abcdef"
    signature = FTMOBridgeAuthenticator.sign(secret, "POST", "/bridge", timestamp, nonce, body)
    FTMOBridgeAuthenticator.verify(secret, "POST", "/bridge", timestamp, nonce, body, signature, now=NOW)
    with pytest.raises(FTMOMasterError, match="signature"):
        FTMOBridgeAuthenticator.verify(secret, "POST", "/bridge", timestamp, nonce, body + b"x", signature, now=NOW)
    with pytest.raises(FTMOMasterError, match="stale"):
        FTMOBridgeAuthenticator.verify(secret, "POST", "/bridge", timestamp, nonce, body, signature, now=NOW + timedelta(seconds=31))

    async def scenario():
        repository = FTMOMasterRepository(Store())
        assert await repository.claim_nonce(nonce, now=NOW) is True
        assert await repository.claim_nonce(nonce, now=NOW) is False

    asyncio.run(scenario())


def test_heartbeat_is_account_bound_and_public_status_masks_identity():
    async def scenario():
        control, _ = service()
        accepted = await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        assert accepted["identity_match"] is True
        status = await control.status(now=NOW)
        assert status["account"] == "****5678"
        assert status["bridge_healthy"] is True
        assert status["execution_ready"] is False  # durable kill switch defaults on
        with pytest.raises(FTMOMasterError, match="mismatch"):
            await control.accept_bridge_heartbeat(heartbeat(account_id="99999999"), now=NOW)
        status = await control.status(now=NOW)
        assert status["bridge_healthy"] is False

    asyncio.run(scenario())


def test_manual_trade_previews_at_exact_three_percent_without_a_fixed_dollar_cap():
    async def scenario():
        control, _ = service()
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        proposal = await control.create_trade_proposal(
            actor="42", symbol="XAUUSD", side="buy", order_type="market",
            stop_loss="2490.20", take_profit="2520.20", now=NOW,
        )
        assert proposal["status"] == "pending_confirmation"
        assert proposal["entry"] == "2500.20"
        assert proposal["volume"] == "0.30"
        assert proposal["risk_amount"] == "300.00"
        assert proposal["risk_fraction"] == "0.03"
        assert not [value for (namespace, _), value in control.repository.store.values.items() if namespace == control.repository.COMMANDS]

    asyncio.run(scenario())


def test_obsolete_dollar_caps_do_not_control_risk_but_broker_drawdown_and_exposure_do():
    async def scenario():
        environment = active_environment(
            FTMO_RISK_FRACTION="0.03",
            FTMO_MAXIMUM_RISK_AMOUNT="5",
            FTMO_MAXIMUM_DAILY_LOSS_AMOUNT="10",
            FTMO_MAXIMUM_OPEN_EXPOSURES="1",
        )
        control, _ = service(environment)
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        proposal = await control.create_trade_proposal(
            actor="42", symbol="XAUUSD", side="buy", order_type="market",
            stop_loss="2495.20", take_profit="2510.20", now=NOW,
        )
        assert Decimal(proposal["risk_amount"]) == Decimal("300.00")
        assert "maximum_risk_amount" not in control.configuration.public_status()
        assert "maximum_daily_loss_amount" not in control.configuration.public_status()
        assert control.configuration.public_status()["maximum_risk_percent_per_trade"] == "3.0"
        assert control.configuration.public_status()["maximum_open_exposures"] == 1

        await control.accept_bridge_heartbeat(heartbeat(equity="9499"), now=NOW)
        with pytest.raises(FTMOMasterError, match="loss capacity"):
            await control.create_trade_proposal(
                actor="42", symbol="XAUUSD", side="buy", order_type="market",
                stop_loss="2495.20", take_profit="2510.20", now=NOW,
            )

        occupied = heartbeat(positions=[{
            "ticket": "1", "symbol": "XAUUSD", "volume": "0.01",
            "price_open": "2500.20", "sl": "2490.20", "tp": "2520.20",
        }])
        await control.accept_bridge_heartbeat(occupied, now=NOW)
        with pytest.raises(FTMOMasterError, match="exposure limit"):
            await control.create_trade_proposal(
                actor="42", symbol="XAUUSD", side="buy", order_type="market",
                stop_loss="2495.20", take_profit="2510.20", now=NOW,
            )
        await control.repository.update_control(kill_switch=False)
        await control.arm("42", now=NOW)
        with pytest.raises(FTMOMasterError, match="exposure limit.*approval"):
            await control.approve(proposal["proposal_id"], "42", now=NOW)

    asyncio.run(scenario())


def test_wrong_pending_order_side_stale_quote_and_spread_fail_closed():
    async def scenario():
        control, _ = service()
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        with pytest.raises(FTMOMasterError, match="wrong side"):
            await control.create_trade_proposal(
                actor="42", symbol="XAUUSD", side="buy", order_type="limit", entry="2501",
                stop_loss="2490", take_profit="2520", now=NOW,
            )
        with pytest.raises(FTMOMasterError, match="stale"):
            await control.create_trade_proposal(
                actor="42", symbol="XAUUSD", side="buy", order_type="market",
                stop_loss="2490", take_profit="2520", now=NOW + timedelta(seconds=6),
            )
        wide = heartbeat()
        wide["quotes"]["XAUUSD"] = {**wide["quotes"]["XAUUSD"], "bid": "2490.00"}
        await control.accept_bridge_heartbeat(wide, now=NOW)
        with pytest.raises(FTMOMasterError, match="spread"):
            await control.create_trade_proposal(
                actor="42", symbol="XAUUSD", side="buy", order_type="market",
                stop_loss="2480", take_profit="2520", now=NOW,
            )

    asyncio.run(scenario())


def test_external_scanner_levels_are_translated_to_ftmo_bid_ask_and_still_require_approval():
    async def scenario():
        control, _ = service()
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        proposal = await control.create_signal_proposal(
            signal_id="gold-signal-1", symbol="XAUUSD", direction="long",
            analysis_entry="3500", analysis_stop="3486", analysis_target="3528",
            source="external futures context", analysis_state="LONG", confirmation_status="confirmed", now=NOW,
        )
        assert proposal["entry"] == "2500.20"
        assert proposal["stop_loss"] == "2490.19"
        assert proposal["take_profit"] == "2520.20"
        assert proposal["analysis_entry"] == "3500"
        assert proposal["status"] == "pending_confirmation"
        assert proposal["level_conversion"] == "external_relative_structure_to_ftmo_bid_ask"
        assert await control.repository.pending_commands() == ()

    asyncio.run(scenario())


def test_signal_specific_recommended_risk_is_respected_below_three_percent_ceiling():
    async def scenario():
        control, _ = service(active_environment(FTMO_RISK_FRACTION="0.03"))
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        proposal = await control.create_signal_proposal(
            telegram_request_id="tgr_1", analysis_id="ana_1", signal_id="sig_risk_1",
            symbol="XAUUSD", direction="long", analysis_entry="3500",
            analysis_stop="3486", analysis_target="3528", source="monatise.telegram.on_demand",
            analysis_state="LONG", confirmation_status="confirmed",
            recommended_risk_percent="1.25", now=NOW,
        )
        assert Decimal(proposal["recommended_risk_fraction"]) == Decimal("0.0125")
        assert Decimal(proposal["risk_amount"]) <= Decimal("125")
        assert proposal["telegram_request_id"] == "tgr_1"

        await control.repository.update_control(kill_switch=False)
        await control.arm("42", now=NOW)
        command = await control.approve(proposal["proposal_id"], "42", now=NOW)
        assert command["telegram_request_id"] == "tgr_1"
        assert Decimal(command["risk_policy"]["recommended_risk_fraction"]) == Decimal("0.0125")
        assert Decimal(command["risk_policy"]["actual_risk_fraction"]) <= Decimal("0.0125")
        assert command["execution_session"]["autonomous_execution_enabled"] is False

    asyncio.run(scenario())


def test_telegram_request_analysis_signal_command_audit_chain_is_durable():
    async def scenario():
        control, store = service()
        request = {
            "request_id": "tgr_audit", "analysis_id": "ana_audit", "telegram_user": "42",
            "requested_instrument": "XAUUSD", "requested_at": NOW.isoformat(), "status": "processing",
        }
        assert await control.repository.claim_telegram_analysis_request(request) is True
        assert await control.repository.claim_telegram_analysis_request(request) is False
        assert await control.repository.save_telegram_analysis({
            "analysis_id": "ana_audit", "telegram_request_id": "tgr_audit", "decision": "QUALIFIED LONG",
            "qualified": True, "market_data_provenance": {"provider": "FlashAlpha"}, "session": {"market_session": "NEW_YORK"},
        }) is True
        saved = await control.repository.telegram_analysis("ana_audit")
        assert saved["telegram_request_id"] == "tgr_audit"
        await control.repository.finish_telegram_analysis_request("tgr_audit", {"status": "completed"})
        events = store.streams[control.repository.AUDIT]
        assert [event["event"] for event in events] == ["telegram_analysis_requested", "telegram_analysis_completed"]

    asyncio.run(scenario())


def test_no_trade_incomplete_or_direction_conflicted_analysis_cannot_become_a_proposal():
    async def scenario():
        control, _ = service()
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        common = {
            "signal_id": "blocked-analysis", "symbol": "XAUUSD", "direction": "long",
            "analysis_entry": "3500", "analysis_stop": "3490", "analysis_target": "3520",
            "source": "monatise.pipeline", "now": NOW,
        }
        with pytest.raises(FTMOMasterError, match="state is not executable"):
            await control.create_signal_proposal(**common, analysis_state="NO_TRADE", confirmation_status="confirmed")
        with pytest.raises(FTMOMasterError, match="conflicts with direction"):
            await control.create_signal_proposal(**common, analysis_state="SHORT", confirmation_status="confirmed")
        with pytest.raises(FTMOMasterError, match="not fully confirmed"):
            await control.create_signal_proposal(**common, analysis_state="LONG", confirmation_status="pending")
        assert await control.repository.proposals() == ()

    asyncio.run(scenario())


def test_approval_requires_kill_reset_temporary_arm_and_current_bridge_then_queues_once():
    async def scenario():
        control, _ = service()
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        proposal = await control.create_trade_proposal(
            actor="42", symbol="XAUUSD", side="sell", order_type="market",
            stop_loss="2510", take_profit="2480", now=NOW,
        )
        with pytest.raises(FTMOMasterError, match="kill switch"):
            await control.approve(proposal["proposal_id"], "42", now=NOW)
        # Kill reset is deliberately an out-of-band administrative action.
        await control.repository.update_control(kill_switch=False)
        armed = await control.arm("42", 120, now=NOW)
        assert armed["execution_ready"] is True
        assert armed["execution_session_armed"] is True
        assert armed["execution_session_id"]
        assert armed["execution_session_started_at"] == NOW.isoformat()
        assert armed["execution_session_expiry"] == (NOW + timedelta(seconds=120)).isoformat()
        command = await control.approve(proposal["proposal_id"], "42", now=NOW)
        assert command["status"] == CommandStatus.READY.value
        assert command["execution_session"]["execution_session_id"] == armed["execution_session_id"]
        assert command["market_session"]["session_checked_at"] == NOW.isoformat()
        assert command["execution_session"]["autonomous_execution_enabled"] is False
        with pytest.raises(FTMOMasterError, match="already"):
            await control.approve(proposal["proposal_id"], "42", now=NOW)
        first = await control.commands_for_bridge(now=NOW)
        second = await control.commands_for_bridge(now=NOW)
        assert first[0]["command_id"] == second[0]["command_id"] == command["command_id"]
        assert second[0]["delivery_count"] == 2

    asyncio.run(scenario())


def test_unknown_broker_result_is_reconciliation_only_and_never_new_command():
    async def scenario():
        control, _ = service()
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        await control.repository.update_control(kill_switch=False)
        await control.arm("42", now=NOW)
        proposal = await control.create_trade_proposal(
            actor="42", symbol="XAUUSD", side="buy", order_type="market",
            stop_loss="2490.20", take_profit="2520.20", now=NOW,
        )
        command = await control.approve(proposal["proposal_id"], "42", now=NOW)
        result = await control.acknowledge(command["command_id"], {
            "status": "broker_uncertain", "message": "network timeout after submit",
        })
        assert result["automatic_resend"] is False
        assert await control.commands_for_bridge(now=NOW) == ()

    asyncio.run(scenario())


def test_arm_does_not_bypass_fresh_market_session_validation_at_approval():
    async def scenario():
        control, _ = service()
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        proposal = await control.create_trade_proposal(
            actor="42", symbol="XAUUSD", side="buy", order_type="market",
            stop_loss="2490.20", take_profit="2520.20", now=NOW,
        )
        closed = heartbeat()
        closed["quotes"]["XAUUSD"]["trade_mode"] = "0"
        await control.accept_bridge_heartbeat(closed, now=NOW + timedelta(seconds=1))
        await control.repository.update_control(kill_switch=False)
        await control.arm("42", now=NOW + timedelta(seconds=1))
        with pytest.raises(FTMOMasterError, match="market session"):
            await control.approve(proposal["proposal_id"], "42", now=NOW + timedelta(seconds=1))
        assert await control.repository.pending_commands() == ()

    asyncio.run(scenario())


def test_authorization_requires_exact_user_and_private_chat():
    control, _ = service()
    assert control.authorized("42", "private") is True
    assert control.authorized("41", "private") is False
    assert control.authorized("42", "group") is False


def test_production_bridge_endpoint_requires_valid_hmac_and_rejects_replay():
    async def scenario():
        control, _ = service()
        runtime = type("Runtime", (), {"ftmo_master": control})()
        app = ProductionASGI(runtime)
        payload = heartbeat()
        payload["quotes"]["XAUUSD"]["timestamp"] = datetime.now(timezone.utc).isoformat()
        body = json.dumps(payload, separators=(",", ":")).encode()
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        nonce = secrets.token_hex(16)
        path = "/api/ftmo/bridge/heartbeat"
        signature = FTMOBridgeAuthenticator.sign(control.configuration.bridge_secret, "POST", path, timestamp, nonce, body)
        scope = {
            "type": "http", "method": "POST", "path": path,
            "headers": [
                (b"x-monatise-timestamp", timestamp.encode()),
                (b"x-monatise-nonce", nonce.encode()),
                (b"x-monatise-signature", signature.encode()),
            ],
        }

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        assert (await app._ftmo_bridge_request(scope, receive))[0] == 200
        assert (await app._ftmo_bridge_request(scope, receive))[0] == 401
        bad = {**scope, "headers": [*scope["headers"][:-1], (b"x-monatise-signature", b"0" * 64)]}
        assert (await app._ftmo_bridge_request(bad, receive))[0] == 401

    asyncio.run(scenario())


def test_signal_approval_reprices_from_fresh_ftmo_ask_and_preserves_lineage():
    async def scenario():
        control, store = service(active_environment(
            FTMO_RISK_FRACTION="0.0005",
        ))
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        proposal = await control.create_signal_proposal(
            analysis_id="analysis-1", signal_id="signal-1", symbol="XAUUSD", direction="buy",
            analysis_entry="3500", analysis_stop="3493.1", analysis_target="3514",
            source="monatise.confirmed", analysis_state="LONG", confirmation_status="confirmed",
            strategy="Liquidity Reclaim", timeframe="15m",
            conviction=8, evidence_bundle={"market_structure": "confirmed"}, now=NOW,
        )
        moved = heartbeat()
        moved["quotes"]["XAUUSD"].update({"bid": "2501.00", "ask": "2501.20"})
        await control.accept_bridge_heartbeat(moved, now=NOW + timedelta(seconds=1))
        await control.repository.update_control(kill_switch=False)
        await control.arm("42", now=NOW + timedelta(seconds=1))

        command = await control.approve(proposal["proposal_id"], "42", now=NOW + timedelta(seconds=1))

        assert command["payload"]["entry"] == "2501.20"  # BUY uses the current FTMO Ask.
        assert command["analysis_id"] == "analysis-1"
        assert command["signal_id"] == "signal-1"
        assert command["approval_id"] and command["execution_id"]
        assert command["execution_snapshot"]["ftmo_bid"] == "2501.00"
        assert command["execution_snapshot"]["ftmo_ask"] == "2501.20"
        assert Decimal(command["risk_policy"]["actual_risk_amount"]) <= Decimal("5")
        stored = await control.repository.proposal(proposal["proposal_id"])
        assert stored[0]["lifecycle_state"] == "EXECUTION_QUEUED"
        assert any(event["event"] == "proposal_revalidating" for event in store.streams[control.repository.AUDIT])

    asyncio.run(scenario())


def test_sell_approval_uses_current_ftmo_bid_and_excessive_move_invalidates_signal():
    async def scenario():
        control, _ = service(active_environment(FTMO_MAXIMUM_ENTRY_DEVIATION_BPS="5"))
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        proposal = await control.create_signal_proposal(
            signal_id="sell-signal", symbol="XAUUSD", direction="sell",
            analysis_entry="3500", analysis_stop="3510", analysis_target="3480",
            source="monatise.confirmed", analysis_state="SHORT", confirmation_status="confirmed", now=NOW,
        )
        moved = heartbeat()
        moved["quotes"]["XAUUSD"].update({"bid": "2510.00", "ask": "2510.20"})
        await control.accept_bridge_heartbeat(moved, now=NOW + timedelta(seconds=1))
        await control.repository.update_control(kill_switch=False)
        await control.arm("42", now=NOW + timedelta(seconds=1))

        with pytest.raises(FTMOMasterError, match="price moved"):
            await control.approve(proposal["proposal_id"], "42", now=NOW + timedelta(seconds=1))
        stored = await control.repository.proposal(proposal["proposal_id"])
        assert stored[0]["status"] == "invalidated"
        assert stored[0]["lifecycle_state"] == "INVALIDATED"

        control2, _ = service()
        await control2.accept_bridge_heartbeat(heartbeat(), now=NOW)
        proposal2 = await control2.create_signal_proposal(
            signal_id="sell-signal-2", symbol="XAUUSD", direction="sell",
            analysis_entry="3500", analysis_stop="3510", analysis_target="3480",
            source="monatise.confirmed", analysis_state="SHORT", confirmation_status="confirmed", now=NOW,
        )
        small_move = heartbeat()
        small_move["quotes"]["XAUUSD"].update({"bid": "2499.50", "ask": "2499.70"})
        await control2.accept_bridge_heartbeat(small_move, now=NOW + timedelta(seconds=1))
        await control2.repository.update_control(kill_switch=False)
        await control2.arm("42", now=NOW + timedelta(seconds=1))
        command = await control2.approve(proposal2["proposal_id"], "42", now=NOW + timedelta(seconds=1))
        assert command["payload"]["entry"] == "2499.50"  # SELL uses the current FTMO Bid.

    asyncio.run(scenario())


def test_coinglass_mapping_is_explicit_and_unsupported_crypto_fails_closed():
    async def scenario():
        control, _ = service(active_environment(FTMO_RISK_FRACTION="0.0005"))
        crypto_quote = heartbeat()
        crypto_quote["quotes"] = {
            "BTCUSD": {
                "bid": "63000", "ask": "63010", "timestamp": NOW.isoformat(),
                "digits": 2, "tick_size": "1", "tick_value": "1",
                "volume_min": "0.01", "volume_max": "10", "volume_step": "0.01", "stops_level": "1",
            }
        }
        await control.accept_bridge_heartbeat(crypto_quote, now=NOW)
        proposal = await control.create_signal_proposal(
            signal_id="btc-1", symbol="BTCUSD", direction="buy",
            analysis_entry="63124.50", analysis_stop="63024.50", analysis_target="63324.50",
            analysis_provider="coinglass", analysis_instrument="BTCUSDT", analysis_exchange="Binance",
            source="monatise.crypto", analysis_state="LONG", confirmation_status="confirmed", now=NOW,
        )
        assert proposal["analysis_price"] == "63124.50"
        assert proposal["mapping"]["canonical_instrument"] == "BTC"
        assert proposal["mapping"]["ftmo_execution_symbol"] == "BTCUSD"
        assert proposal["execution_snapshot"]["ftmo_ask"] == "63010"
        with pytest.raises(FTMOMasterError, match="mapping"):
            await control.create_signal_proposal(
                signal_id="pepe-1", symbol="PEPEUSD", direction="buy",
                analysis_entry="1", analysis_stop="0.9", analysis_target="1.2",
                analysis_provider="coinglass", analysis_instrument="PEPEUSDT",
                source="monatise.crypto", analysis_state="LONG", confirmation_status="confirmed", now=NOW,
            )

    asyncio.run(scenario())


def test_rejection_duplicate_supersession_minimum_lot_and_broker_evidence_are_fail_closed():
    async def scenario():
        control, store = service(active_environment(
            FTMO_RISK_FRACTION="0.0005",
        ))
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        rejected = await control.create_signal_proposal(
            signal_id="immutable-signal", symbol="XAUUSD", direction="buy",
            analysis_entry="3500", analysis_stop="3493.1", analysis_target="3514",
            source="monatise.confirmed", analysis_state="LONG", confirmation_status="confirmed", now=NOW,
        )
        await control.reject(rejected["proposal_id"], "42")
        with pytest.raises(FTMOMasterError, match="collision"):
            await control.create_signal_proposal(
                signal_id="immutable-signal", symbol="XAUUSD", direction="buy",
                analysis_entry="3500", analysis_stop="3493.1", analysis_target="3514",
                source="monatise.confirmed", analysis_state="LONG", confirmation_status="confirmed", now=NOW,
            )

        first = await control.create_signal_proposal(
            signal_id="old-signal", symbol="XAUUSD", direction="buy",
            analysis_entry="3500", analysis_stop="3493.1", analysis_target="3514",
            source="monatise.confirmed", analysis_state="LONG", confirmation_status="confirmed", now=NOW,
        )
        await control.create_signal_proposal(
            signal_id="new-signal", supersedes_signal_id="old-signal", symbol="XAUUSD", direction="buy",
            analysis_entry="3501", analysis_stop="3494.1", analysis_target="3515",
            source="monatise.confirmed", analysis_state="LONG", confirmation_status="confirmed", now=NOW,
        )
        assert (await control.repository.proposal(first["proposal_id"]))[0]["status"] == "invalidated"

        expensive = heartbeat()
        expensive["quotes"]["XAUUSD"].update({"tick_value": "1000", "volume_min": "0.10", "volume_step": "0.10"})
        await control.accept_bridge_heartbeat(expensive, now=NOW)
        with pytest.raises(FTMOMasterError, match="minimum FTMO volume"):
            await control.create_trade_proposal(
                actor="42", symbol="XAUUSD", side="buy", order_type="market",
                stop_loss="2499.20", take_profit="2502.20", now=NOW,
            )

        # Re-establish a normal snapshot and prove broker evidence updates the immutable lineage.
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        proposal = await control.create_trade_proposal(
            actor="42", symbol="XAUUSD", side="buy", order_type="market",
            stop_loss="2495.20", take_profit="2510.20", now=NOW,
        )
        await control.repository.update_control(kill_switch=False)
        await control.arm("42", now=NOW)
        command = await control.approve(proposal["proposal_id"], "42", now=NOW)
        result = await control.acknowledge(command["command_id"], {
            "status": "reconciled", "broker_ticket": "12345678", "broker_retcode": "10009",
            "requested_price": "2500.20", "fill_price": "2500.21", "slippage": "0.01",
            "executed_volume": command["payload"]["volume"],
            "executed_stop_loss": command["payload"]["stop_loss"],
            "executed_take_profit": command["payload"]["take_profit"],
            "broker_observed_at": NOW.isoformat(),
        })
        duplicate_result = await control.acknowledge(command["command_id"], {
            "status": "reconciled", "broker_ticket": "12345678", "broker_retcode": "10009",
            "requested_price": "2500.20", "fill_price": "2500.21", "slippage": "0.01",
            "executed_volume": command["payload"]["volume"],
            "executed_stop_loss": command["payload"]["stop_loss"],
            "executed_take_profit": command["payload"]["take_profit"],
            "broker_observed_at": NOW.isoformat(),
        })
        assert result["fill_price"] == "2500.21"
        assert result["notification_required"] is True
        assert duplicate_result["notification_required"] is False
        stored = (await control.repository.proposal(proposal["proposal_id"]))[0]
        assert stored["broker_ticket"] == "12345678"
        assert stored["execution_result"]["broker_retcode"] == "10009"
        assert any(event["event"] == "bridge_acknowledgement" for event in store.streams[control.repository.AUDIT])

    asyncio.run(scenario())


def test_authenticated_heartbeat_reconciles_position_open_and_closed_lifecycle():
    async def scenario():
        control, store = service(active_environment(
            FTMO_RISK_FRACTION="0.0005",
        ))
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        proposal = await control.create_trade_proposal(
            actor="42", symbol="XAUUSD", side="buy", order_type="market",
            stop_loss="2495.20", take_profit="2510.20", now=NOW,
        )
        await control.repository.update_control(kill_switch=False)
        await control.arm("42", now=NOW)
        command = await control.approve(proposal["proposal_id"], "42", now=NOW)
        await control.acknowledge(command["command_id"], {
            "status": "accepted", "broker_ticket": "9001", "broker_retcode": "10009",
            "fill_price": "2500.20", "executed_volume": command["payload"]["volume"],
        })

        opened = heartbeat()
        opened["quotes"]["XAUUSD"]["timestamp"] = (NOW + timedelta(seconds=1)).isoformat()
        opened["positions"] = [{
            "ticket": "9001", "symbol": "XAUUSD", "volume": command["payload"]["volume"],
            "price_open": "2500.20", "price_current": "2500.40", "sl": "2495.20",
            "tp": "2510.20", "profit": "0.20", "comment": f"MNT:{command['command_id'][:16]}",
        }]
        opened_result = await control.accept_bridge_heartbeat(opened, now=NOW + timedelta(seconds=1))
        assert [event["lifecycle_state"] for event in opened_result["lifecycle_events"]] == ["POSITION_OPEN"]
        active = (await control.repository.proposal(proposal["proposal_id"]))[0]
        assert active["lifecycle_state"] == "POSITION_OPEN"
        assert active["position_snapshot"]["ticket"] == "9001"

        closed = heartbeat()
        closed["quotes"]["XAUUSD"]["timestamp"] = (NOW + timedelta(seconds=2)).isoformat()
        closed_result = await control.accept_bridge_heartbeat(closed, now=NOW + timedelta(seconds=2))
        assert [event["lifecycle_state"] for event in closed_result["lifecycle_events"]] == ["POSITION_CLOSED"]
        completed = (await control.repository.proposal(proposal["proposal_id"]))[0]
        assert completed["status"] == "reconciled"
        assert completed["lifecycle_state"] == "POSITION_CLOSED"
        assert [event["fields"]["state"] for event in store.streams[control.repository.AUDIT]
                if event["event"] == "position_lifecycle"] == ["POSITION_OPEN", "POSITION_CLOSED"]

    asyncio.run(scenario())


def test_expiry_restart_reconnect_and_broker_rejection_preserve_fail_closed_lineage():
    async def scenario():
        control, store = service(active_environment(
            FTMO_RISK_FRACTION="0.0005",
        ))
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        expired = await control.create_signal_proposal(
            signal_id="expires-before-approval", symbol="XAUUSD", direction="buy",
            analysis_entry="3500", analysis_stop="3493.1", analysis_target="3514",
            source="monatise.confirmed", analysis_state="LONG", confirmation_status="confirmed",
            signal_expires_at=NOW + timedelta(seconds=1), now=NOW,
        )
        with pytest.raises(FTMOMasterError, match="expired"):
            await control.approve(expired["proposal_id"], "42", now=NOW + timedelta(seconds=2))
        assert (await control.repository.proposal(expired["proposal_id"]))[0]["status"] == "expired"

        proposal = await control.create_trade_proposal(
            actor="42", symbol="XAUUSD", side="buy", order_type="market",
            stop_loss="2495.20", take_profit="2510.20", now=NOW,
        )
        await control.repository.update_control(kill_switch=False)
        await control.arm("42", now=NOW)
        command = await control.approve(proposal["proposal_id"], "42", now=NOW)

        # A Render process restart must read the same durable command instead
        # of constructing a second economic action.
        restarted = FTMOMasterControlService(control.configuration, FTMOMasterRepository(store))
        delivered = await restarted.commands_for_bridge(now=NOW)
        assert [item["command_id"] for item in delivered] == [command["command_id"]]

        disconnected = heartbeat(terminal_connected=False)
        disconnected["quotes"]["XAUUSD"]["timestamp"] = (NOW + timedelta(seconds=1)).isoformat()
        await restarted.accept_bridge_heartbeat(disconnected, now=NOW + timedelta(seconds=1))
        assert await restarted.commands_for_bridge(now=NOW + timedelta(seconds=1)) == ()
        reconnected = heartbeat()
        reconnected["quotes"]["XAUUSD"]["timestamp"] = (NOW + timedelta(seconds=2)).isoformat()
        await restarted.accept_bridge_heartbeat(reconnected, now=NOW + timedelta(seconds=2))
        assert (await restarted.commands_for_bridge(now=NOW + timedelta(seconds=2)))[0]["command_id"] == command["command_id"]

        rejected = await restarted.acknowledge(command["command_id"], {
            "status": "rejected", "broker_retcode": "10016", "message": "invalid stops",
        })
        assert rejected["lifecycle_state"] == "EXECUTION_FAILED"
        failed_proposal = (await restarted.repository.proposal(proposal["proposal_id"]))[0]
        assert failed_proposal["status"] == "execution_failed"
        assert failed_proposal["lifecycle_state"] == "EXECUTION_FAILED"
        assert await restarted.commands_for_bridge(now=NOW + timedelta(seconds=2)) == ()

    asyncio.run(scenario())
