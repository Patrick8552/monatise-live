"""Durable, fail-closed FTMO master-account control plane.

Telegram can propose and approve work, but it cannot speak to the broker.
Render persists signed commands and an outbound-polling MT5 EA is the sole
broker boundary.  Every write path requires independent activation gates,
an unexpired arm session, a healthy account-bound bridge, and a final EA-side
validation.  Autonomous execution is intentionally unsupported.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from enum import StrEnum
from typing import Any, Mapping


ZERO = Decimal("0")


def _true(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on", "enabled"}


def _env(environment: Mapping[str, str], key: str, default: str = "") -> str:
    """Accept the specification's names and existing MONATISE-prefixed names."""
    return str(environment.get(key, environment.get(f"MONATISE_{key}", default))).strip()


def _utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return result.astimezone(timezone.utc)


def _decimal(value: Any, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not result.is_finite() or (positive and result <= ZERO):
        raise ValueError(f"{name} must be positive" if positive else f"{name} must be finite")
    return result


def _mask_account(value: str | None) -> str | None:
    if not value:
        return None
    return "*" * max(0, len(value) - 4) + value[-4:]


class FTMOMasterError(RuntimeError):
    """A deterministic execution safety check failed."""


class ProposalStatus(StrEnum):
    PENDING = "pending_confirmation"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    COMMAND_CREATED = "command_created"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    RECONCILED = "reconciled"


class CommandStatus(StrEnum):
    READY = "ready"
    DELIVERED = "delivered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUBMITTING = "submitting"
    BROKER_UNCERTAIN = "broker_uncertain"
    RECONCILED = "reconciled"


@dataclass(frozen=True)
class FTMOMasterConfiguration:
    account_id: str | None
    server: str | None
    currency: str
    execution_enabled: bool
    master_account_approved: bool
    telegram_execution_armed_by_configuration: bool
    autonomous_execution: bool
    telegram_confirmation_required: bool
    execution_environment: str
    bridge_secret: str | None
    authorized_user_ids: frozenset[str]
    maximum_risk_amount: Decimal = Decimal("100")
    risk_fraction: Decimal = Decimal("0.01")
    maximum_daily_loss_amount: Decimal = Decimal("500")
    maximum_open_exposures: int = 1
    arm_max_seconds: int = 900
    heartbeat_max_age_seconds: int = 30
    quote_max_age_seconds: int = 5
    maximum_spread_ticks: Decimal = Decimal("80")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "FTMOMasterConfiguration":
        users = frozenset(part.strip() for part in _env(environment, "FTMO_TELEGRAM_AUTHORIZED_USER_IDS").split(",") if part.strip())
        configuration = cls(
            account_id=_env(environment, "FTMO_ACCOUNT_ID") or None,
            server=_env(environment, "FTMO_SERVER") or None,
            currency=_env(environment, "FTMO_ACCOUNT_CURRENCY", "USD").upper(),
            execution_enabled=_true(_env(environment, "FTMO_EXECUTION_ENABLED", "false")),
            master_account_approved=_true(_env(environment, "FTMO_MASTER_ACCOUNT_APPROVED", "false")),
            telegram_execution_armed_by_configuration=_true(_env(environment, "FTMO_TELEGRAM_EXECUTION_ARMED", "false")),
            autonomous_execution=_true(_env(environment, "FTMO_AUTONOMOUS_EXECUTION", "false")),
            telegram_confirmation_required=_true(_env(environment, "FTMO_TELEGRAM_CONFIRMATION_REQUIRED", "true")),
            execution_environment=_env(environment, "FTMO_EXECUTION_ENVIRONMENT", "demo").casefold(),
            bridge_secret=_env(environment, "FTMO_BRIDGE_SECRET") or None,
            authorized_user_ids=users,
            maximum_risk_amount=_decimal(_env(environment, "FTMO_MAXIMUM_RISK_AMOUNT", "100"), "maximum risk amount", positive=True),
            risk_fraction=_decimal(_env(environment, "FTMO_RISK_FRACTION", "0.01"), "risk fraction", positive=True),
            maximum_daily_loss_amount=_decimal(
                _env(environment, "FTMO_MAXIMUM_DAILY_LOSS_AMOUNT", "500"),
                "maximum daily loss amount",
                positive=True,
            ),
            maximum_open_exposures=int(_env(environment, "FTMO_MAXIMUM_OPEN_EXPOSURES", "1")),
            arm_max_seconds=max(60, min(3600, int(_env(environment, "FTMO_ARM_MAX_SECONDS", "900")))),
            heartbeat_max_age_seconds=max(5, min(120, int(_env(environment, "FTMO_HEARTBEAT_MAX_AGE_SECONDS", "30")))),
            quote_max_age_seconds=max(1, min(30, int(_env(environment, "FTMO_QUOTE_MAX_AGE_SECONDS", "5")))),
            maximum_spread_ticks=_decimal(_env(environment, "FTMO_MAXIMUM_SPREAD_TICKS", "80"), "maximum spread ticks", positive=True),
        )
        if configuration.risk_fraction > Decimal("0.01"):
            raise ValueError("FTMO risk fraction cannot exceed 1%")
        if configuration.maximum_open_exposures < 1:
            raise ValueError("FTMO maximum open exposures must be at least one")
        if configuration.execution_environment not in {"demo", "master"}:
            raise ValueError("FTMO execution environment must be demo or master")
        if configuration.autonomous_execution:
            raise ValueError("autonomous FTMO execution is not supported")
        if configuration.execution_enabled and not configuration.telegram_confirmation_required:
            raise ValueError("FTMO execution requires Telegram confirmation")
        if configuration.execution_enabled and not configuration.bridge_secret:
            raise ValueError("FTMO execution requires a bridge secret")
        return configuration

    @property
    def identity_configured(self) -> bool:
        return bool(self.account_id and self.server and self.currency)

    @property
    def activation_configured(self) -> bool:
        base = all((
            self.execution_enabled,
            self.telegram_execution_armed_by_configuration,
            self.telegram_confirmation_required,
            self.identity_configured,
            self.bridge_secret,
            self.authorized_user_ids,
            not self.autonomous_execution,
        ))
        return bool(base and (self.execution_environment == "demo" or self.master_account_approved))

    def public_status(self) -> dict[str, Any]:
        return {
            "environment": self.execution_environment,
            "account": _mask_account(self.account_id),
            "server_configured": bool(self.server),
            "identity_configured": self.identity_configured,
            "execution_enabled": self.execution_enabled,
            "master_account_approved": self.master_account_approved,
            "telegram_gate_enabled": self.telegram_execution_armed_by_configuration,
            "confirmation_required": self.telegram_confirmation_required,
            "autonomous_execution": False,
            "activation_configured": self.activation_configured,
            "risk_fraction": str(self.risk_fraction),
            "maximum_risk_amount": str(self.maximum_risk_amount),
            "maximum_daily_loss_amount": str(self.maximum_daily_loss_amount),
            "maximum_open_exposures": self.maximum_open_exposures,
        }


class FTMOBridgeAuthenticator:
    """HMAC-SHA256 request authentication with timestamp and replay nonce."""

    @staticmethod
    def body_hash(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()

    @classmethod
    def canonical(cls, method: str, path: str, timestamp: str, nonce: str, body: bytes) -> bytes:
        return "\n".join((method.upper(), path, timestamp, nonce, cls.body_hash(body))).encode()

    @classmethod
    def sign(cls, secret: str, method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
        return hmac.new(secret.encode(), cls.canonical(method, path, timestamp, nonce, body), hashlib.sha256).hexdigest()

    @classmethod
    def verify(
        cls,
        secret: str,
        method: str,
        path: str,
        timestamp: str,
        nonce: str,
        body: bytes,
        signature: str,
        *,
        now: datetime | None = None,
        maximum_skew_seconds: int = 30,
    ) -> None:
        if not timestamp or not nonce or len(nonce) < 16 or len(nonce) > 128:
            raise FTMOMasterError("bridge authentication metadata is invalid")
        try:
            observed = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError) as exc:
            raise FTMOMasterError("bridge timestamp is invalid") from exc
        if abs((_utc(now) - observed).total_seconds()) > maximum_skew_seconds:
            raise FTMOMasterError("bridge request timestamp is stale")
        expected = cls.sign(secret, method, path, timestamp, nonce, body)
        if not hmac.compare_digest(expected, signature.casefold()):
            raise FTMOMasterError("bridge signature is invalid")


class FTMOMasterRepository:
    """Durable proposal, command, arm, kill, heartbeat, nonce, and audit state."""

    BRIDGE = "ftmo_master_bridge"
    PROPOSALS = "ftmo_master_proposals"
    COMMANDS = "ftmo_master_commands"
    CONTROL = "ftmo_master_control"
    NONCES = "ftmo_master_nonces"
    AUDIT = "ftmo_master_audit"

    def __init__(self, store: Any) -> None:
        self.store = store

    async def _put(self, namespace: str, key: str, value: dict[str, Any], *, expected_version: int | None = None) -> Any:
        options = {} if expected_version is None else {"expected_version": expected_version}
        return await self.store.put(namespace, key, value, **options)

    async def claim_nonce(self, nonce: str, *, now: datetime | None = None) -> bool:
        if await self.store.get(self.NONCES, nonce) is not None:
            return False
        try:
            await self._put(self.NONCES, nonce, {"observed_at": _utc(now).isoformat()}, expected_version=0)
        except RuntimeError:
            return False
        return True

    async def save_bridge(self, value: dict[str, Any]) -> None:
        current = await self.store.get(self.BRIDGE, "current")
        await self._put(self.BRIDGE, "current", value, expected_version=current.version if current else 0)

    async def bridge(self) -> dict[str, Any] | None:
        record = await self.store.get(self.BRIDGE, "current")
        return dict(record.value) if record else None

    async def control(self) -> dict[str, Any]:
        record = await self.store.get(self.CONTROL, "state")
        return dict(record.value) if record else {"kill_switch": True, "armed_until": None, "armed_by": None}

    async def update_control(self, **changes: Any) -> dict[str, Any]:
        record = await self.store.get(self.CONTROL, "state")
        value = dict(record.value) if record else {"kill_switch": True, "armed_until": None, "armed_by": None}
        value.update(changes)
        value["updated_at"] = _utc().isoformat()
        await self._put(self.CONTROL, "state", value, expected_version=record.version if record else 0)
        return value

    async def save_proposal(self, proposal: dict[str, Any]) -> bool:
        try:
            await self._put(self.PROPOSALS, proposal["proposal_id"], proposal, expected_version=0)
        except RuntimeError:
            return False
        await self.audit("proposal_created", proposal["proposal_id"], {"kind": proposal["kind"], "symbol": proposal.get("symbol")})
        return True

    async def proposal(self, proposal_id: str) -> tuple[dict[str, Any], int] | None:
        record = await self.store.get(self.PROPOSALS, proposal_id)
        return (dict(record.value), record.version) if record else None

    async def update_proposal(self, proposal_id: str, value: dict[str, Any], version: int) -> None:
        await self._put(self.PROPOSALS, proposal_id, value, expected_version=version)

    async def save_command(self, command: dict[str, Any]) -> bool:
        try:
            await self._put(self.COMMANDS, command["command_id"], command, expected_version=0)
        except RuntimeError:
            return False
        await self.audit("command_created", command["command_id"], {"proposal_id": command["proposal_id"], "operation": command["operation"]})
        return True

    async def pending_commands(self, limit: int = 10) -> tuple[dict[str, Any], ...]:
        records = await self.store.list_namespace(self.COMMANDS)
        commands = [dict(record.value) for record in records if record.value.get("status") in {CommandStatus.READY.value, CommandStatus.DELIVERED.value}]
        commands.sort(key=lambda item: (item.get("created_at", ""), item["command_id"]))
        return tuple(commands[: max(1, min(20, limit))])

    async def update_command(self, command_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        record = await self.store.get(self.COMMANDS, command_id)
        if record is None:
            raise KeyError("unknown bridge command")
        value = dict(record.value)
        value.update(changes)
        value["updated_at"] = _utc().isoformat()
        await self._put(self.COMMANDS, command_id, value, expected_version=record.version)
        return value

    async def audit(self, event: str, subject: str, fields: dict[str, Any]) -> None:
        await self.store.append(self.AUDIT, {
            "event": event,
            "subject": subject,
            "fields": fields,
            "observed_at": _utc().isoformat(),
        })

    async def retention_sweep(self, *, now: datetime | None = None) -> dict[str, int]:
        observed = _utc(now)
        removed = {"nonces": 0, "proposals": 0, "commands": 0}
        for record in await self.store.list_namespace(self.NONCES):
            try:
                created = datetime.fromisoformat(str(record.value.get("observed_at")))
            except ValueError:
                created = datetime.min.replace(tzinfo=timezone.utc)
            if observed - created > timedelta(hours=1):
                await self.store.delete(self.NONCES, record.key)
                removed["nonces"] += 1
        cutoff = observed - timedelta(days=90)
        for namespace, label in ((self.PROPOSALS, "proposals"), (self.COMMANDS, "commands")):
            for record in await self.store.list_namespace(namespace):
                try:
                    created = datetime.fromisoformat(str(record.value.get("created_at")))
                except ValueError:
                    continue
                if created < cutoff:
                    await self.store.delete(namespace, record.key)
                    removed[label] += 1
        return removed


class FTMOMasterControlService:
    def __init__(self, configuration: FTMOMasterConfiguration, repository: FTMOMasterRepository) -> None:
        self.configuration = configuration
        self.repository = repository

    def authorized(self, user_id: str | None, chat_type: str | None) -> bool:
        return bool(user_id and chat_type == "private" and user_id in self.configuration.authorized_user_ids)

    async def accept_bridge_heartbeat(self, payload: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        observed = _utc(now)
        account_id = str(payload.get("account_id") or "").strip()
        server = str(payload.get("server") or "").strip()
        currency = str(payload.get("currency") or "").strip().upper()
        if not account_id or not server or not currency:
            raise FTMOMasterError("bridge account identity is incomplete")
        identity_match = bool(
            self.configuration.identity_configured
            and account_id == self.configuration.account_id
            and server.casefold() == str(self.configuration.server).casefold()
            and currency == self.configuration.currency
        )
        quotes = payload.get("quotes") or {}
        if not isinstance(quotes, dict):
            raise FTMOMasterError("bridge quotes must be an object")
        normalized_quotes: dict[str, dict[str, Any]] = {}
        for raw_symbol, raw_quote in list(quotes.items())[:256]:
            if not isinstance(raw_quote, Mapping):
                continue
            symbol = str(raw_symbol).strip().upper()
            bid = _decimal(raw_quote.get("bid"), "bid", positive=True)
            ask = _decimal(raw_quote.get("ask"), "ask", positive=True)
            if ask < bid:
                raise FTMOMasterError("bridge ask cannot be below bid")
            quote_at = datetime.fromisoformat(str(raw_quote.get("timestamp") or "").replace("Z", "+00:00"))
            normalized_quotes[symbol] = {
                "bid": str(bid), "ask": str(ask), "timestamp": _utc(quote_at).isoformat(),
                "digits": int(raw_quote.get("digits", 0)),
                "tick_size": str(_decimal(raw_quote.get("tick_size"), "tick size", positive=True)),
                "tick_value": str(_decimal(raw_quote.get("tick_value"), "tick value", positive=True)),
                "volume_min": str(_decimal(raw_quote.get("volume_min"), "minimum volume", positive=True)),
                "volume_max": str(_decimal(raw_quote.get("volume_max"), "maximum volume", positive=True)),
                "volume_step": str(_decimal(raw_quote.get("volume_step"), "volume step", positive=True)),
                "stops_level": str(_decimal(raw_quote.get("stops_level", 0), "stops level")),
            }
        snapshot = {
            "account_id": account_id,
            "server": server,
            "currency": currency,
            "balance": str(_decimal(payload.get("balance"), "balance", positive=True)),
            "equity": str(_decimal(payload.get("equity"), "equity", positive=True)),
            "initial_balance": str(_decimal(payload.get("initial_balance", payload.get("balance")), "initial balance", positive=True)),
            "daily_start_equity": str(_decimal(payload.get("daily_start_equity", payload.get("equity")), "daily start equity", positive=True)),
            "daily_loss_limit": str(_decimal(payload.get("daily_loss_limit"), "daily loss limit", positive=True)),
            "total_loss_limit": str(_decimal(payload.get("total_loss_limit"), "total loss limit", positive=True)),
            "terminal_connected": bool(payload.get("terminal_connected")),
            "trade_allowed": bool(payload.get("trade_allowed")),
            "ea_attached": bool(payload.get("ea_attached")),
            "identity_match": identity_match,
            "terminal_build": str(payload.get("terminal_build") or ""),
            "ea_version": str(payload.get("ea_version") or ""),
            "positions": list(payload.get("positions") or [])[:256],
            "orders": list(payload.get("orders") or [])[:256],
            "quotes": normalized_quotes,
            "observed_at": observed.isoformat(),
        }
        await self.repository.save_bridge(snapshot)
        await self.repository.audit("bridge_heartbeat", _mask_account(account_id) or "unknown", {
            "identity_match": identity_match, "terminal_connected": snapshot["terminal_connected"],
            "trade_allowed": snapshot["trade_allowed"], "quote_count": len(normalized_quotes),
        })
        if not identity_match:
            raise FTMOMasterError("FTMO bridge account/server/currency mismatch")
        return {"status": "accepted", "identity_match": True, "execution_enabled": self.configuration.activation_configured}

    async def status(self, *, now: datetime | None = None) -> dict[str, Any]:
        observed = _utc(now)
        bridge = await self.repository.bridge()
        control = await self.repository.control()
        heartbeat_age = None
        bridge_healthy = False
        if bridge and bridge.get("observed_at"):
            heartbeat_age = max(0.0, (observed - datetime.fromisoformat(bridge["observed_at"])).total_seconds())
            bridge_healthy = bool(
                heartbeat_age <= self.configuration.heartbeat_max_age_seconds
                and bridge.get("identity_match")
                and bridge.get("terminal_connected")
                and bridge.get("ea_attached")
            )
        armed_until = control.get("armed_until")
        armed = False
        if armed_until:
            try:
                armed = datetime.fromisoformat(str(armed_until)) > observed
            except ValueError:
                armed = False
        kill_switch = bool(control.get("kill_switch", True))
        execution_ready = bool(
            self.configuration.activation_configured
            and bridge_healthy
            and bridge and bridge.get("trade_allowed")
            and armed
            and not kill_switch
        )
        return {
            **self.configuration.public_status(),
            "bridge_healthy": bridge_healthy,
            "heartbeat_age_seconds": heartbeat_age,
            "terminal_connected": bool(bridge and bridge.get("terminal_connected")),
            "trade_allowed": bool(bridge and bridge.get("trade_allowed")),
            "ea_attached": bool(bridge and bridge.get("ea_attached")),
            "quote_symbols": sorted((bridge or {}).get("quotes", {})),
            "armed": armed,
            "armed_until": armed_until if armed else None,
            "kill_switch": kill_switch,
            "execution_ready": execution_ready,
        }

    async def arm(self, actor: str, seconds: int | None = None, *, now: datetime | None = None) -> dict[str, Any]:
        if actor not in self.configuration.authorized_user_ids:
            raise FTMOMasterError("Telegram user is not authorized")
        status = await self.status(now=now)
        if status["kill_switch"]:
            raise FTMOMasterError("kill switch is active; reset it out-of-band before arming")
        if not self.configuration.activation_configured:
            raise FTMOMasterError("master activation configuration is incomplete")
        duration = min(max(60, int(seconds or self.configuration.arm_max_seconds)), self.configuration.arm_max_seconds)
        until = _utc(now) + timedelta(seconds=duration)
        await self.repository.update_control(armed_until=until.isoformat(), armed_by=actor)
        await self.repository.audit("execution_armed", actor, {"armed_until": until.isoformat()})
        return await self.status(now=now)

    async def disarm(self, actor: str) -> dict[str, Any]:
        await self.repository.update_control(armed_until=None, armed_by=None)
        await self.repository.audit("execution_disarmed", actor, {})
        return await self.status()

    async def kill(self, actor: str) -> dict[str, Any]:
        await self.repository.update_control(kill_switch=True, armed_until=None, armed_by=None)
        await self.repository.audit("kill_switch_activated", actor, {})
        return await self.status()

    async def create_trade_proposal(
        self,
        *,
        actor: str,
        symbol: str,
        side: str,
        order_type: str,
        stop_loss: Any,
        take_profit: Any,
        entry: Any | None = None,
        now: datetime | None = None,
        _proposal_id: str | None = None,
    ) -> dict[str, Any]:
        observed = _utc(now)
        if actor not in self.configuration.authorized_user_ids and actor != "monatise-scanner":
            raise FTMOMasterError("Telegram user is not authorized")
        symbol = symbol.strip().upper()
        side = side.strip().casefold()
        order_type = order_type.strip().casefold()
        if side not in {"buy", "sell"} or order_type not in {"market", "limit", "stop"}:
            raise FTMOMasterError("trade side/type must be buy|sell and market|limit|stop")
        bridge = await self._healthy_bridge(observed)
        quote = (bridge.get("quotes") or {}).get(symbol)
        if quote is None:
            raise FTMOMasterError("FTMO bridge has no current quote for that symbol")
        quote_at = datetime.fromisoformat(quote["timestamp"])
        if (observed - quote_at).total_seconds() > self.configuration.quote_max_age_seconds:
            raise FTMOMasterError("FTMO quote is stale")
        bid, ask = Decimal(quote["bid"]), Decimal(quote["ask"])
        tick_size, tick_value = Decimal(quote["tick_size"]), Decimal(quote["tick_value"])
        spread_ticks = (ask - bid) / tick_size
        if spread_ticks > self.configuration.maximum_spread_ticks:
            raise FTMOMasterError("FTMO spread exceeds policy")
        requested_entry = (ask if side == "buy" else bid) if order_type == "market" else _decimal(entry, "entry", positive=True)
        stop = _decimal(stop_loss, "stop loss", positive=True)
        target = _decimal(take_profit, "take profit", positive=True)
        if side == "buy" and not stop < requested_entry < target:
            raise FTMOMasterError("buy levels require stop < entry < target")
        if side == "sell" and not target < requested_entry < stop:
            raise FTMOMasterError("sell levels require target < entry < stop")
        if order_type == "limit" and ((side == "buy" and requested_entry >= ask) or (side == "sell" and requested_entry <= bid)):
            raise FTMOMasterError("limit entry is on the wrong side of the FTMO market")
        if order_type == "stop" and ((side == "buy" and requested_entry <= ask) or (side == "sell" and requested_entry >= bid)):
            raise FTMOMasterError("stop entry is on the wrong side of the FTMO market")
        minimum_stop = Decimal(quote["stops_level"]) * tick_size
        stop_distance = abs(requested_entry - stop)
        if stop_distance < minimum_stop:
            raise FTMOMasterError("stop distance is below the FTMO symbol minimum")
        equity = Decimal(bridge["equity"])
        loss_today = max(ZERO, Decimal(bridge["daily_start_equity"]) - equity)
        daily_remaining = min(
            Decimal(bridge["daily_loss_limit"]),
            self.configuration.maximum_daily_loss_amount,
        ) - loss_today
        total_loss = max(ZERO, Decimal(bridge["initial_balance"]) - equity)
        total_remaining = Decimal(bridge["total_loss_limit"]) - total_loss
        open_exposures = sum(
            1 for item in (*tuple(bridge.get("positions") or ()), *tuple(bridge.get("orders") or ()))
            if isinstance(item, Mapping)
        )
        if open_exposures >= self.configuration.maximum_open_exposures:
            raise FTMOMasterError("maximum open position/pending-order exposure limit is reached")
        existing_open_risk = ZERO
        for position in bridge.get("positions") or []:
            if not isinstance(position, Mapping):
                continue
            position_symbol = str(position.get("symbol") or "").upper()
            position_quote = (bridge.get("quotes") or {}).get(position_symbol)
            position_stop = _decimal(position.get("sl", 0), "position stop")
            if position_stop <= ZERO:
                raise FTMOMasterError("an open position has no protective stop; new risk is blocked")
            if position_quote is None:
                raise FTMOMasterError("open-position risk cannot be priced from the FTMO heartbeat")
            position_entry = _decimal(position.get("price_open"), "position entry", positive=True)
            position_volume = _decimal(position.get("volume"), "position volume", positive=True)
            existing_open_risk += (
                abs(position_entry - position_stop)
                / Decimal(position_quote["tick_size"])
                * Decimal(position_quote["tick_value"])
                * position_volume
            )
        available_loss_capacity = min(daily_remaining, total_remaining) - existing_open_risk
        risk_budget = min(equity * self.configuration.risk_fraction, self.configuration.maximum_risk_amount, available_loss_capacity)
        if risk_budget <= ZERO:
            raise FTMOMasterError("FTMO daily/total loss capacity is exhausted")
        loss_per_lot = (stop_distance / tick_size) * tick_value
        step = Decimal(quote["volume_step"])
        volume = ((risk_budget / loss_per_lot) / step).to_integral_value(rounding=ROUND_FLOOR) * step
        volume = min(volume, Decimal(quote["volume_max"]))
        if volume < Decimal(quote["volume_min"]):
            raise FTMOMasterError("calculated FTMO volume is below the symbol minimum")
        actual_risk = loss_per_lot * volume
        if existing_open_risk + actual_risk > equity * Decimal("0.03"):
            raise FTMOMasterError("FTMO total open risk limit would be exceeded")
        proposal_id = _proposal_id or secrets.token_hex(6)
        expires_at = observed + timedelta(minutes=5)
        proposal = {
            "proposal_id": proposal_id,
            "kind": "open_trade",
            "status": ProposalStatus.PENDING.value,
            "actor": actor,
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "entry": str(requested_entry),
            "stop_loss": str(stop),
            "take_profit": str(target),
            "volume": str(volume),
            "risk_amount": str(actual_risk),
            "risk_fraction": str(actual_risk / equity),
            "quote_bid": str(bid),
            "quote_ask": str(ask),
            "quote_timestamp": quote["timestamp"],
            "created_at": observed.isoformat(),
            "expires_at": expires_at.isoformat(),
            "confirmation_required": True,
        }
        if not await self.repository.save_proposal(proposal):
            raise FTMOMasterError("proposal identity collision")
        return proposal

    async def create_signal_proposal(
        self,
        *,
        signal_id: str,
        symbol: str,
        direction: str,
        analysis_entry: Any,
        analysis_stop: Any,
        analysis_target: Any,
        source: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Translate external structure into FTMO-native levels.

        External prices define only relative risk/reward distances. The current
        FTMO Bid/Ask is always the executable reference price.
        """
        entry = _decimal(analysis_entry, "analysis entry", positive=True)
        stop = _decimal(analysis_stop, "analysis stop", positive=True)
        target = _decimal(analysis_target, "analysis target", positive=True)
        normalized = direction.strip().casefold()
        if normalized in {"long", "buy"}:
            side = "buy"
            if not stop < entry < target:
                raise FTMOMasterError("external long signal levels are invalid")
        elif normalized in {"short", "sell"}:
            side = "sell"
            if not target < entry < stop:
                raise FTMOMasterError("external short signal levels are invalid")
        else:
            raise FTMOMasterError("external signal direction is invalid")
        observed = _utc(now)
        bridge = await self._healthy_bridge(observed)
        quote = (bridge.get("quotes") or {}).get(symbol.strip().upper())
        if quote is None:
            raise FTMOMasterError("FTMO bridge has no current quote for the signal symbol")
        ftmo_entry = Decimal(quote["ask"] if side == "buy" else quote["bid"])
        risk_fraction = abs(entry - stop) / entry
        reward_fraction = abs(target - entry) / entry
        if side == "buy":
            ftmo_stop = ftmo_entry * (Decimal("1") - risk_fraction)
            ftmo_target = ftmo_entry * (Decimal("1") + reward_fraction)
        else:
            ftmo_stop = ftmo_entry * (Decimal("1") + risk_fraction)
            ftmo_target = ftmo_entry * (Decimal("1") - reward_fraction)
        tick = Decimal(quote["tick_size"])
        ftmo_stop = (ftmo_stop / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
        ftmo_target = (ftmo_target / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
        proposal_id = hashlib.sha256(f"{signal_id}:{symbol}:{side}:{quote['timestamp']}".encode()).hexdigest()[:12]
        proposal = await self.create_trade_proposal(
            actor="monatise-scanner", symbol=symbol, side=side, order_type="market",
            stop_loss=ftmo_stop, take_profit=ftmo_target, now=observed, _proposal_id=proposal_id,
        )
        proposal.update({
            "signal_id": signal_id,
            "analysis_source": source,
            "analysis_entry": str(entry),
            "analysis_stop": str(stop),
            "analysis_target": str(target),
            "level_conversion": "external_relative_structure_to_ftmo_bid_ask",
        })
        stored = await self.repository.proposal(proposal_id)
        if stored is not None:
            _, version = stored
            await self.repository.update_proposal(proposal_id, proposal, version)
        return proposal

    async def create_management_proposal(self, *, actor: str, operation: str, target_id: str, value: str | None = None) -> dict[str, Any]:
        if actor not in self.configuration.authorized_user_ids:
            raise FTMOMasterError("Telegram user is not authorized")
        if operation not in {"close", "cancel", "sl", "tp", "breakeven"}:
            raise FTMOMasterError("unsupported position-management operation")
        if not target_id.isdigit() or int(target_id) <= 0:
            raise FTMOMasterError("position/order ticket must be a positive integer")
        if operation in {"sl", "tp"}:
            _decimal(value, f"{operation} level", positive=True)
        bridge = await self._healthy_bridge(_utc())
        collection = bridge.get("orders" if operation == "cancel" else "positions") or []
        if not any(str(item.get("ticket")) == target_id for item in collection if isinstance(item, Mapping)):
            raise FTMOMasterError("position/order ticket is not present in the current MT5 heartbeat")
        now = _utc()
        proposal = {
            "proposal_id": secrets.token_hex(6), "kind": "manage_trade", "status": ProposalStatus.PENDING.value,
            "actor": actor, "operation": operation, "target_id": target_id, "value": value,
            "created_at": now.isoformat(), "expires_at": (now + timedelta(minutes=3)).isoformat(),
            "confirmation_required": True,
        }
        if not await self.repository.save_proposal(proposal):
            raise FTMOMasterError("proposal identity collision")
        return proposal

    async def approve(self, proposal_id: str, actor: str, *, now: datetime | None = None) -> dict[str, Any]:
        observed = _utc(now)
        if actor not in self.configuration.authorized_user_ids:
            raise FTMOMasterError("Telegram user is not authorized")
        stored = await self.repository.proposal(proposal_id)
        if stored is None:
            raise FTMOMasterError("unknown proposal")
        proposal, version = stored
        if proposal.get("status") != ProposalStatus.PENDING.value:
            raise FTMOMasterError(f"proposal is already {proposal.get('status')}")
        if datetime.fromisoformat(proposal["expires_at"]) <= observed:
            proposal["status"] = ProposalStatus.EXPIRED.value
            await self.repository.update_proposal(proposal_id, proposal, version)
            raise FTMOMasterError("proposal has expired")
        readiness = await self.status(now=observed)
        if not readiness["execution_ready"]:
            blockers = [name for name, blocked in (
                ("activation configuration", not self.configuration.activation_configured),
                ("bridge", not readiness["bridge_healthy"]),
                ("MT5 trade permission", not readiness["trade_allowed"]),
                ("temporary arm", not readiness["armed"]),
                ("kill switch", readiness["kill_switch"]),
            ) if blocked]
            await self.repository.audit("approval_blocked", proposal_id, {"actor": actor, "blockers": blockers})
            raise FTMOMasterError("execution is blocked by: " + ", ".join(blockers))
        # Revalidate the bridge and quote immediately before command creation.
        bridge = await self._healthy_bridge(observed)
        if proposal["kind"] == "open_trade":
            quote = (bridge.get("quotes") or {}).get(proposal["symbol"])
            if not quote or (observed - datetime.fromisoformat(quote["timestamp"])).total_seconds() > self.configuration.quote_max_age_seconds:
                raise FTMOMasterError("FTMO quote is stale at approval")
            open_exposures = sum(
                1 for item in (*tuple(bridge.get("positions") or ()), *tuple(bridge.get("orders") or ()))
                if isinstance(item, Mapping)
            )
            if open_exposures >= self.configuration.maximum_open_exposures:
                raise FTMOMasterError("maximum open position/pending-order exposure limit is reached at approval")
            equity = Decimal(bridge["equity"])
            loss_today = max(ZERO, Decimal(bridge["daily_start_equity"]) - equity)
            daily_remaining = min(
                Decimal(bridge["daily_loss_limit"]),
                self.configuration.maximum_daily_loss_amount,
            ) - loss_today
            total_loss = max(ZERO, Decimal(bridge["initial_balance"]) - equity)
            total_remaining = Decimal(bridge["total_loss_limit"]) - total_loss
            if Decimal(proposal["risk_amount"]) > min(daily_remaining, total_remaining):
                raise FTMOMasterError("configured daily/total loss capacity is insufficient at approval")
        command_id = hashlib.sha256(f"{proposal_id}:{proposal['kind']}:{proposal.get('operation', 'open')}".encode()).hexdigest()
        command = {
            "command_id": command_id,
            "proposal_id": proposal_id,
            "operation": proposal.get("operation", "open"),
            "payload": {key: proposal.get(key) for key in (
                "symbol", "side", "order_type", "entry", "stop_loss", "take_profit", "volume", "target_id", "value"
            ) if proposal.get(key) is not None},
            "expected_account_id": self.configuration.account_id,
            "expected_server": self.configuration.server,
            "expected_currency": self.configuration.currency,
            "status": CommandStatus.READY.value,
            "created_at": observed.isoformat(),
            "expires_at": min(datetime.fromisoformat(proposal["expires_at"]), observed + timedelta(seconds=30)).isoformat(),
            "automatic_resend": "same_command_id_only",
        }
        if not await self.repository.save_command(command):
            raise FTMOMasterError("duplicate execution command")
        proposal.update({"status": ProposalStatus.COMMAND_CREATED.value, "approved_by": actor, "approved_at": observed.isoformat(), "command_id": command_id})
        await self.repository.update_proposal(proposal_id, proposal, version)
        await self.repository.audit("proposal_approved", proposal_id, {"actor": actor, "command_id": command_id})
        return command

    async def reject(self, proposal_id: str, actor: str) -> dict[str, Any]:
        stored = await self.repository.proposal(proposal_id)
        if stored is None:
            raise FTMOMasterError("unknown proposal")
        proposal, version = stored
        if proposal.get("status") != ProposalStatus.PENDING.value:
            raise FTMOMasterError(f"proposal is already {proposal.get('status')}")
        proposal.update({"status": ProposalStatus.REJECTED.value, "rejected_by": actor, "rejected_at": _utc().isoformat()})
        await self.repository.update_proposal(proposal_id, proposal, version)
        await self.repository.audit("proposal_rejected", proposal_id, {"actor": actor})
        return proposal

    async def commands_for_bridge(self, *, now: datetime | None = None, limit: int = 5) -> tuple[dict[str, Any], ...]:
        observed = _utc(now)
        readiness = await self.status(now=observed)
        if not readiness["execution_ready"]:
            return ()
        commands = []
        for command in await self.repository.pending_commands(limit):
            if datetime.fromisoformat(command["expires_at"]) <= observed:
                await self.repository.update_command(command["command_id"], {"status": CommandStatus.REJECTED.value, "reason": "expired before delivery"})
                continue
            if command["expected_account_id"] != self.configuration.account_id or command["expected_server"] != self.configuration.server:
                await self.repository.update_command(command["command_id"], {"status": CommandStatus.REJECTED.value, "reason": "configured identity changed"})
                continue
            delivered = await self.repository.update_command(command["command_id"], {
                "status": CommandStatus.DELIVERED.value,
                "last_delivered_at": observed.isoformat(),
                "delivery_count": int(command.get("delivery_count", 0)) + 1,
            })
            commands.append(delivered)
        return tuple(commands)

    async def acknowledge(self, command_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        raw_status = str(payload.get("status") or "").strip().casefold()
        allowed = {item.value for item in CommandStatus} - {CommandStatus.READY.value, CommandStatus.DELIVERED.value}
        if raw_status not in allowed:
            raise FTMOMasterError("invalid bridge acknowledgement status")
        changes = {
            "status": raw_status,
            "broker_ticket": str(payload.get("broker_ticket") or "") or None,
            "broker_retcode": str(payload.get("broker_retcode") or "") or None,
            "message": str(payload.get("message") or "")[:500],
            "broker_observed_at": str(payload.get("broker_observed_at") or _utc().isoformat()),
        }
        if raw_status == CommandStatus.BROKER_UNCERTAIN.value:
            changes["automatic_resend"] = False
        command = await self.repository.update_command(command_id, changes)
        await self.repository.audit("bridge_acknowledgement", command_id, {"status": raw_status, "broker_ticket": changes["broker_ticket"]})
        return command

    async def _healthy_bridge(self, now: datetime) -> dict[str, Any]:
        bridge = await self.repository.bridge()
        if bridge is None:
            raise FTMOMasterError("FTMO bridge has never connected")
        if not bridge.get("identity_match"):
            raise FTMOMasterError("FTMO bridge identity mismatch")
        if not bridge.get("terminal_connected") or not bridge.get("ea_attached"):
            raise FTMOMasterError("FTMO bridge is disconnected")
        if (now - datetime.fromisoformat(bridge["observed_at"])).total_seconds() > self.configuration.heartbeat_max_age_seconds:
            raise FTMOMasterError("FTMO bridge heartbeat is stale")
        return bridge


def format_proposal(proposal: Mapping[str, Any]) -> str:
    if proposal.get("kind") == "open_trade":
        return "\n".join((
            "MONATISE FTMO TRADE PREVIEW",
            f"ID: {proposal['proposal_id']}",
            f"{str(proposal['side']).upper()} {proposal['symbol']} · {str(proposal['order_type']).upper()}",
            f"Entry: {proposal['entry']} | SL: {proposal['stop_loss']} | TP: {proposal['take_profit']}",
            f"Volume: {proposal['volume']} | Risk: ${proposal['risk_amount']} ({Decimal(str(proposal['risk_fraction'])) * 100:.2f}%)",
            f"FTMO Bid/Ask: {proposal['quote_bid']} / {proposal['quote_ask']}",
            f"Expires: {proposal['expires_at']}",
            f"Approve: /approve {proposal['proposal_id']} | Reject: /reject {proposal['proposal_id']}",
            "No order has been sent.",
        ))
    return "\n".join((
        "MONATISE FTMO MANAGEMENT PREVIEW",
        f"ID: {proposal['proposal_id']}",
        f"Operation: {str(proposal['operation']).upper()} · target {proposal['target_id']}",
        *((f"Value: {proposal['value']}",) if proposal.get("value") else ()),
        f"Approve: /approve {proposal['proposal_id']} | Reject: /reject {proposal['proposal_id']}",
        "No broker change has been sent.",
    ))


def format_status(status: Mapping[str, Any]) -> str:
    return "\n".join((
        "MONATISE FTMO STATUS",
        f"Account: {status.get('account') or 'not configured'} · {status.get('environment', 'unknown')}",
        f"Bridge: {'HEALTHY' if status.get('bridge_healthy') else 'OFFLINE/STALE'}",
        f"MT5 connected: {bool(status.get('terminal_connected'))} | EA: {bool(status.get('ea_attached'))} | Trade permission: {bool(status.get('trade_allowed'))}",
        f"Kill switch: {'ON' if status.get('kill_switch') else 'OFF'} | Armed: {bool(status.get('armed'))}",
        f"Master gates: {'READY' if status.get('activation_configured') else 'BLOCKED'}",
        f"Execution: {'READY' if status.get('execution_ready') else 'BLOCKED'}",
    ))
