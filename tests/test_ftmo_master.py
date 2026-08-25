from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone

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
        "FTMO_MAXIMUM_RISK_AMOUNT": "100",
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


def test_manual_trade_always_previews_and_risk_is_minimum_of_one_percent_and_100():
    async def scenario():
        control, _ = service()
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        proposal = await control.create_trade_proposal(
            actor="42", symbol="XAUUSD", side="buy", order_type="market",
            stop_loss="2490.20", take_profit="2520.20", now=NOW,
        )
        assert proposal["status"] == "pending_confirmation"
        assert proposal["entry"] == "2500.20"
        assert proposal["volume"] == "0.10"
        assert proposal["risk_amount"] == "100.00"
        assert not [value for (namespace, _), value in control.repository.store.values.items() if namespace == control.repository.COMMANDS]

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
            source="external futures context", now=NOW,
        )
        assert proposal["entry"] == "2500.20"
        assert proposal["stop_loss"] == "2490.19"
        assert proposal["take_profit"] == "2520.20"
        assert proposal["analysis_entry"] == "3500"
        assert proposal["status"] == "pending_confirmation"
        assert proposal["level_conversion"] == "external_relative_structure_to_ftmo_bid_ask"
        assert await control.repository.pending_commands() == ()

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
        command = await control.approve(proposal["proposal_id"], "42", now=NOW)
        assert command["status"] == CommandStatus.READY.value
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
