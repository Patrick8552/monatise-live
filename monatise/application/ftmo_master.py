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
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from enum import StrEnum
from typing import Any, Mapping

from monatise.application.market_session import classify_market_session, session_allows_execution
from monatise.application.ftmo_registry import FTMOAssetClass, FTMOInstrument, FTMO_REGISTRY
from monatise.application.risk_policy import MAX_RISK_FRACTION_PER_TRADE, MAX_RISK_PERCENT_PER_TRADE, risk_ceiling


ZERO = Decimal("0")
LOGGER = logging.getLogger("monatise.ftmo_master")


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


def _timestamp(value: Any, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include an explicit UTC offset")
    return parsed.astimezone(timezone.utc)


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
    INVALIDATED = "invalidated"
    CANCELLED = "cancelled"
    EXECUTION_FAILED = "execution_failed"


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
    risk_fraction: Decimal = MAX_RISK_FRACTION_PER_TRADE
    maximum_open_exposures: int = 1
    arm_max_seconds: int = 900
    heartbeat_max_age_seconds: int = 30
    quote_max_age_seconds: int = 5
    quote_future_tolerance_seconds: Decimal = Decimal("0")
    maximum_spread_ticks: Decimal = Decimal("80")
    maximum_entry_deviation_bps: Decimal = Decimal("50")
    minimum_reward_risk: Decimal = Decimal("1")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "FTMOMasterConfiguration":
        raw_users = (
            _env(environment, "TELEGRAM_ALLOWED_USER_IDS")
            or _env(environment, "FTMO_TELEGRAM_AUTHORIZED_USER_IDS")
        )
        users = frozenset(part.strip() for part in raw_users.split(",") if part.strip())
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
            risk_fraction=_decimal(_env(environment, "FTMO_RISK_FRACTION", str(MAX_RISK_FRACTION_PER_TRADE)), "risk fraction", positive=True),
            maximum_open_exposures=int(_env(environment, "FTMO_MAXIMUM_OPEN_EXPOSURES", "1")),
            arm_max_seconds=max(60, min(3600, int(_env(environment, "FTMO_ARM_MAX_SECONDS", "900")))),
            heartbeat_max_age_seconds=max(5, min(120, int(_env(environment, "FTMO_HEARTBEAT_MAX_AGE_SECONDS", "30")))),
            quote_max_age_seconds=max(1, min(30, int(_env(environment, "FTMO_QUOTE_MAX_AGE_SECONDS", "5")))),
            quote_future_tolerance_seconds=min(
                Decimal("5"),
                max(ZERO, _decimal(_env(environment, "FTMO_QUOTE_FUTURE_TOLERANCE_SECONDS", "0"), "quote future tolerance")),
            ),
            maximum_spread_ticks=_decimal(_env(environment, "FTMO_MAXIMUM_SPREAD_TICKS", "80"), "maximum spread ticks", positive=True),
            maximum_entry_deviation_bps=_decimal(
                _env(environment, "FTMO_MAXIMUM_ENTRY_DEVIATION_BPS", "50"),
                "maximum entry deviation bps",
                positive=True,
            ),
            minimum_reward_risk=_decimal(
                _env(environment, "FTMO_MINIMUM_REWARD_RISK", "1"),
                "minimum reward/risk",
                positive=True,
            ),
        )
        if configuration.risk_fraction > MAX_RISK_FRACTION_PER_TRADE:
            raise ValueError("FTMO risk fraction cannot exceed 3%")
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
            "maximum_risk_percent_per_trade": str(MAX_RISK_PERCENT_PER_TRADE),
            "risk_policy": "percentage_only_current_equity",
            "maximum_open_exposures": self.maximum_open_exposures,
            "maximum_entry_deviation_bps": str(self.maximum_entry_deviation_bps),
            "minimum_reward_risk": str(self.minimum_reward_risk),
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
    TELEGRAM_REQUESTS = "telegram_analysis_requests"
    ANALYSES = "telegram_analyses"
    QUOTE_REQUESTS = "ftmo_quote_requests"

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
        return dict(record.value) if record else {
            "kill_switch": True, "armed_until": None, "armed_by": None,
            "execution_session_id": None, "execution_session_started_at": None,
        }

    async def update_control(self, **changes: Any) -> dict[str, Any]:
        record = await self.store.get(self.CONTROL, "state")
        value = dict(record.value) if record else {
            "kill_switch": True, "armed_until": None, "armed_by": None,
            "execution_session_id": None, "execution_session_started_at": None,
        }
        value.update(changes)
        value["updated_at"] = _utc().isoformat()
        await self._put(self.CONTROL, "state", value, expected_version=record.version if record else 0)
        return value

    async def save_proposal(self, proposal: dict[str, Any]) -> bool:
        try:
            await self._put(self.PROPOSALS, proposal["proposal_id"], proposal, expected_version=0)
        except RuntimeError:
            return False
        await self.audit("proposal_created", proposal["proposal_id"], {
            "kind": proposal["kind"], "symbol": proposal.get("symbol"),
            "analysis_id": proposal.get("analysis_id"), "quote_request_id": proposal.get("quote_request_id"),
            "proposal_id": proposal["proposal_id"], "signal_id": proposal.get("signal_id"),
        })
        return True

    async def proposal(self, proposal_id: str) -> tuple[dict[str, Any], int] | None:
        record = await self.store.get(self.PROPOSALS, proposal_id)
        return (dict(record.value), record.version) if record else None

    async def proposals(self) -> tuple[dict[str, Any], ...]:
        records = await self.store.list_namespace(self.PROPOSALS)
        values = [dict(record.value) for record in records]
        values.sort(key=lambda item: (item.get("created_at", ""), item.get("proposal_id", "")))
        return tuple(values)

    async def update_proposal(self, proposal_id: str, value: dict[str, Any], version: int) -> None:
        await self._put(self.PROPOSALS, proposal_id, value, expected_version=version)

    async def attach_proposal_telegram_message(self, proposal_id: str, message_id: int) -> dict[str, Any]:
        if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id <= 0:
            raise ValueError("Telegram message identity must be a positive integer")
        stored = await self.proposal(proposal_id)
        if stored is None:
            raise KeyError("unknown FTMO proposal")
        value, version = stored
        previous = value.get("telegram_message_id")
        if previous is not None and previous != message_id:
            raise RuntimeError("FTMO proposal Telegram identity is already immutable")
        value["telegram_message_id"] = message_id
        value["telegram_published_at"] = _utc().isoformat()
        await self.update_proposal(proposal_id, value, version)
        await self.audit("telegram_proposal_published", proposal_id, {
            "telegram_message_id": message_id,
            "analysis_id": value.get("analysis_id"),
            "signal_id": value.get("signal_id"),
        })
        return value

    async def save_command(self, command: dict[str, Any]) -> bool:
        try:
            await self._put(self.COMMANDS, command["command_id"], command, expected_version=0)
        except RuntimeError:
            return False
        await self.audit("command_created", command["command_id"], {
            "analysis_id": command.get("analysis_id"), "quote_request_id": command.get("quote_request_id"),
            "proposal_id": command["proposal_id"], "execution_id": command.get("execution_id"),
            "operation": command["operation"],
        })
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

    async def command(self, command_id: str) -> tuple[dict[str, Any], int] | None:
        record = await self.store.get(self.COMMANDS, command_id)
        return (dict(record.value), record.version) if record else None

    async def audit(self, event: str, subject: str, fields: dict[str, Any]) -> None:
        await self.store.append(self.AUDIT, {
            "event": event,
            "subject": subject,
            "fields": fields,
            "observed_at": _utc().isoformat(),
        })

    async def claim_telegram_analysis_request(self, request: dict[str, Any]) -> bool:
        """Claim one Telegram update across workers and Render restarts."""
        request_id = str(request.get("request_id") or "")
        if not request_id:
            raise ValueError("Telegram request identity is required")
        try:
            await self._put(self.TELEGRAM_REQUESTS, request_id, request, expected_version=0)
        except RuntimeError:
            return False
        await self.audit("telegram_analysis_requested", request_id, {
            "analysis_id": request.get("analysis_id"),
            "telegram_user": request.get("telegram_user"),
            "requested_instrument": request.get("requested_instrument"),
            "requested_at": request.get("requested_at"),
        })
        return True

    async def telegram_analysis_request(self, request_id: str) -> tuple[dict[str, Any], int] | None:
        record = await self.store.get(self.TELEGRAM_REQUESTS, request_id)
        return (dict(record.value), record.version) if record else None

    async def finish_telegram_analysis_request(self, request_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        record = await self.store.get(self.TELEGRAM_REQUESTS, request_id)
        if record is None:
            raise KeyError("unknown Telegram analysis request")
        value = dict(record.value)
        value.update(dict(changes))
        await self._put(self.TELEGRAM_REQUESTS, request_id, value, expected_version=record.version)
        return value

    async def save_telegram_analysis(self, analysis: dict[str, Any]) -> bool:
        analysis_id = str(analysis.get("analysis_id") or "")
        if not analysis_id:
            raise ValueError("analysis identity is required")
        try:
            await self._put(self.ANALYSES, analysis_id, analysis, expected_version=0)
        except RuntimeError:
            return False
        await self.audit("telegram_analysis_completed", analysis_id, {
            "telegram_request_id": analysis.get("telegram_request_id"),
            "decision": analysis.get("decision"),
            "qualified": analysis.get("qualified"),
            "market_data_provenance": analysis.get("market_data_provenance"),
            "session": analysis.get("session"),
        })
        return True

    async def telegram_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        record = await self.store.get(self.ANALYSES, analysis_id)
        return dict(record.value) if record else None

    async def update_telegram_analysis(self, analysis_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        record = await self.store.get(self.ANALYSES, analysis_id)
        if record is None:
            raise KeyError("unknown Telegram analysis")
        value = dict(record.value)
        value.update(dict(changes))
        value["updated_at"] = _utc().isoformat()
        await self._put(self.ANALYSES, analysis_id, value, expected_version=record.version)
        return value

    async def save_quote_request(self, request: dict[str, Any]) -> bool:
        quote_request_id = str(request.get("quote_request_id") or "")
        if not quote_request_id:
            raise ValueError("quote request identity is required")
        try:
            await self._put(self.QUOTE_REQUESTS, quote_request_id, request, expected_version=0)
        except RuntimeError:
            return False
        await self.audit("quote_requested", quote_request_id, {
            "analysis_id": request.get("analysis_id"),
            "quote_request_id": quote_request_id,
            "ftmo_symbol": request.get("ftmo_symbol"),
            "deadline": request.get("deadline"),
        })
        return True

    async def quote_request(self, quote_request_id: str) -> tuple[dict[str, Any], int] | None:
        record = await self.store.get(self.QUOTE_REQUESTS, quote_request_id)
        return (dict(record.value), record.version) if record else None

    async def quote_requests(self, *, states: frozenset[str] | None = None) -> tuple[dict[str, Any], ...]:
        records = await self.store.list_namespace(self.QUOTE_REQUESTS)
        values = [dict(record.value) for record in records]
        if states is not None:
            values = [value for value in values if str(value.get("state")) in states]
        values.sort(key=lambda item: (item.get("next_retry_at", ""), item.get("requested_at", "")))
        return tuple(values)

    async def update_quote_request(
        self, quote_request_id: str, changes: Mapping[str, Any], *, expected_version: int | None = None,
    ) -> dict[str, Any]:
        record = await self.store.get(self.QUOTE_REQUESTS, quote_request_id)
        if record is None:
            raise KeyError("unknown quote request")
        if expected_version is not None and record.version != expected_version:
            raise RuntimeError("version conflict")
        value = dict(record.value)
        value.update(dict(changes))
        value["updated_at"] = _utc().isoformat()
        await self._put(self.QUOTE_REQUESTS, quote_request_id, value, expected_version=record.version)
        return value

    async def claim_quote_attempt(
        self, quote_request_id: str, *, now: datetime, lease_seconds: int = 30,
    ) -> dict[str, Any] | None:
        stored = await self.quote_request(quote_request_id)
        if stored is None:
            return None
        value, version = stored
        if value.get("state") not in {"QUOTE_REQUESTED", "WAITING_FOR_QUOTE"}:
            return None
        if int(value.get("retry_count") or 0) >= int(value.get("maximum_attempts") or 4):
            return None
        deadline = _timestamp(value.get("deadline"), "quote request deadline")
        if now >= deadline:
            return None
        next_retry = _timestamp(value.get("next_retry_at") or value.get("requested_at"), "quote request retry time")
        lease_until_raw = value.get("lease_until")
        lease_until = _timestamp(lease_until_raw, "quote request lease") if lease_until_raw else None
        if now < next_retry or (lease_until is not None and now < lease_until):
            return None
        value.update({
            "state": "QUOTE_REQUESTED",
            "retry_count": int(value.get("retry_count") or 0) + 1,
            "last_attempt_at": now.isoformat(),
            "lease_until": (now + timedelta(seconds=lease_seconds)).isoformat(),
        })
        try:
            await self._put(self.QUOTE_REQUESTS, quote_request_id, value, expected_version=version)
        except RuntimeError:
            return None
        return value

    async def claim_quote_publication(self, quote_request_id: str, *, now: datetime) -> dict[str, Any] | None:
        stored = await self.quote_request(quote_request_id)
        if stored is None:
            return None
        value, version = stored
        state = value.get("state")
        if value.get("telegram_message_id"):
            return None
        if state == "PROPOSAL_PUBLISHING":
            claimed_at = _timestamp(value.get("publication_claimed_at"), "quote publication claim")
            if now - claimed_at < timedelta(minutes=2):
                return None
        elif state != "PROPOSAL_CREATED":
            return None
        value.update({"state": "PROPOSAL_PUBLISHING", "publication_claimed_at": now.isoformat()})
        try:
            await self._put(self.QUOTE_REQUESTS, quote_request_id, value, expected_version=version)
        except RuntimeError:
            return None
        return value

    async def retention_sweep(self, *, now: datetime | None = None) -> dict[str, int]:
        observed = _utc(now)
        removed = {"nonces": 0, "proposals": 0, "commands": 0, "quote_requests": 0}
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
        for record in await self.store.list_namespace(self.QUOTE_REQUESTS):
            try:
                created = datetime.fromisoformat(str(record.value.get("requested_at")))
            except ValueError:
                continue
            if created < cutoff:
                await self.store.delete(self.QUOTE_REQUESTS, record.key)
                removed["quote_requests"] += 1
        return removed


class FTMOMasterControlService:
    def __init__(self, configuration: FTMOMasterConfiguration, repository: FTMOMasterRepository) -> None:
        self.configuration = configuration
        self.repository = repository

    @staticmethod
    def quote_request_identity(analysis_id: str, ftmo_symbol: str) -> str:
        digest = hashlib.sha256(f"quote:{analysis_id}:{ftmo_symbol.upper()}".encode()).hexdigest()
        return f"qtr_{digest[:24]}"

    async def create_quote_request(
        self,
        *,
        analysis_id: str,
        telegram_request_id: str,
        canonical_instrument: str,
        ftmo_symbol: str,
        deadline: datetime,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        observed = _utc(now)
        expiry = _utc(deadline)
        if expiry <= observed:
            raise FTMOMasterError("signal has already expired")
        quote_request_id = self.quote_request_identity(analysis_id, ftmo_symbol)
        request = {
            "quote_request_id": quote_request_id,
            "analysis_id": analysis_id,
            "telegram_request_id": telegram_request_id,
            "canonical_instrument": canonical_instrument,
            "ftmo_symbol": ftmo_symbol,
            "expected_account": self.configuration.account_id,
            "expected_server": self.configuration.server,
            "expected_currency": self.configuration.currency,
            "requested_at": observed.isoformat(),
            "deadline": expiry.isoformat(),
            "retry_count": 0,
            "maximum_attempts": 4,
            "next_retry_at": observed.isoformat(),
            "state": "QUOTE_REQUESTED",
            "autonomous_execution": False,
        }
        if not await self.repository.save_quote_request(request):
            stored = await self.repository.quote_request(quote_request_id)
            if stored is None:
                raise FTMOMasterError("quote request identity collision")
            existing = stored[0]
            if existing.get("analysis_id") != analysis_id or self._symbol_key(str(existing.get("ftmo_symbol"))) != self._symbol_key(ftmo_symbol):
                raise FTMOMasterError("quote request identity collision")
            return existing
        await self.repository.update_telegram_analysis(analysis_id, {
            "lifecycle_state": "WAITING_FOR_QUOTE",
            "quote_request_id": quote_request_id,
            "ftmo_symbol": ftmo_symbol,
        })
        await self.repository.audit("waiting_for_quote", quote_request_id, {
            "analysis_id": analysis_id, "quote_request_id": quote_request_id,
        })
        return request

    async def pending_quote_requests(self) -> tuple[dict[str, Any], ...]:
        return await self.repository.quote_requests(states=frozenset({
            "QUOTE_REQUESTED", "WAITING_FOR_QUOTE", "PROPOSAL_CREATED", "PROPOSAL_PUBLISHING",
        }))

    @staticmethod
    def _terminal_quote_error(reason: str) -> bool:
        value = reason.casefold()
        return any(fragment in value for fragment in (
            "identity does not match", "identity mismatch", "account/server/currency mismatch",
            "account identity", "server identity", "currency identity",
            "no unique verified ftmo symbol mapping", "instrument does not match", "signal has already expired",
            "external signal", "not fully confirmed",
        ))

    async def process_quote_request(
        self, quote_request_id: str, *, now: datetime | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        observed = _utc(now)
        claimed = await self.repository.claim_quote_attempt(quote_request_id, now=observed)
        if claimed is None:
            stored = await self.repository.quote_request(quote_request_id)
            if stored is None:
                return {}, None
            current = stored[0]
            if current.get("state") in {"QUOTE_REQUESTED", "WAITING_FOR_QUOTE"} and observed >= _timestamp(current["deadline"], "quote request deadline"):
                current = await self.repository.update_quote_request(quote_request_id, {
                    "state": "EXPIRED", "expired_at": observed.isoformat(), "lease_until": None,
                })
                await self.repository.update_telegram_analysis(str(current["analysis_id"]), {"lifecycle_state": "EXPIRED"})
                await self.repository.audit("quote_rejected", quote_request_id, {
                    "analysis_id": current["analysis_id"], "quote_request_id": quote_request_id,
                    "reason": "analysis expired",
                })
            return current, None
        analysis_id = str(claimed["analysis_id"])
        analysis = await self.repository.telegram_analysis(analysis_id)
        if analysis is None:
            await self.repository.update_quote_request(quote_request_id, {
                "state": "FAILED", "failure_reason": "durable analysis is missing", "lease_until": None,
            })
            await self.repository.audit("quote_rejected", quote_request_id, {
                "analysis_id": analysis_id, "quote_request_id": quote_request_id,
                "reason": "durable analysis is missing",
            })
            return claimed, None
        deadline = min(
            _timestamp(claimed["deadline"], "quote request deadline"),
            _timestamp(analysis["expires_at"], "analysis expiry"),
        )
        if observed >= deadline:
            expired = await self.repository.update_quote_request(quote_request_id, {
                "state": "EXPIRED", "expired_at": observed.isoformat(), "lease_until": None,
            })
            await self.repository.update_telegram_analysis(analysis_id, {"lifecycle_state": "EXPIRED"})
            await self.repository.audit("quote_rejected", quote_request_id, {
                "analysis_id": analysis_id, "quote_request_id": quote_request_id, "reason": "analysis expired",
            })
            return expired, None
        try:
            bridge = await self._healthy_bridge(observed)
            if str(bridge.get("account_id")) != str(claimed.get("expected_account")):
                raise FTMOMasterError("FTMO account identity does not match quote request")
            if str(bridge.get("server", "")).casefold() != str(claimed.get("expected_server", "")).casefold():
                raise FTMOMasterError("FTMO server identity does not match quote request")
            if str(bridge.get("currency", "")).upper() != str(claimed.get("expected_currency", "")).upper():
                raise FTMOMasterError("FTMO currency identity does not match quote request")
            instrument = FTMO_REGISTRY.resolve(str(claimed["canonical_instrument"]))
            execution_symbol = await self.execution_symbol_for(instrument, now=observed)
            if self._symbol_key(execution_symbol) != self._symbol_key(str(claimed["ftmo_symbol"])):
                crypto_alias = instrument.asset_class is FTMOAssetClass.CRYPTO and self._symbol_key(execution_symbol) == self._symbol_key(f"{instrument.underlying_symbol}USD")
                if not crypto_alias:
                    raise FTMOMasterError("FTMO quote symbol does not match quote request")
            quote = (bridge.get("quotes") or {}).get(execution_symbol.upper())
            if quote is None:
                raise FTMOMasterError("FTMO bridge has no current quote for the requested symbol")
            await self.repository.update_quote_request(quote_request_id, {
                "state": "QUOTE_RECEIVED", "resolved_mt5_symbol": execution_symbol,
                "quote_received_at": observed.isoformat(), "quote": self._execution_snapshot(execution_symbol, quote, bridge),
                "lease_until": None,
            })
            await self.repository.audit("quote_received", quote_request_id, {
                "analysis_id": analysis_id, "quote_request_id": quote_request_id,
                "symbol": execution_symbol, "quote_observed_at_utc": quote.get("quote_observed_at_utc"),
            })
            expiry = _timestamp(analysis["expires_at"], "analysis expiry")
            zone = analysis.get("entry_zone") or {}
            try:
                proposal = await self.create_signal_proposal(
                    telegram_request_id=analysis["telegram_request_id"], analysis_id=analysis_id,
                    quote_request_id=quote_request_id, signal_id=analysis["signal_id"], symbol=execution_symbol,
                    direction=analysis["bias"], analysis_entry=analysis["entry"],
                    analysis_stop=analysis["stop_loss"], analysis_target=analysis["targets"][0],
                    source="monatise.telegram.on_demand", analysis_state=analysis["bias"],
                    confirmation_status="confirmed", analysis_provider=analysis["analysis_provider"],
                    analysis_instrument=analysis["analysis_instrument"], analysis_exchange=instrument.exchange,
                    analysis_observed_at=_timestamp(analysis["analysis_completed_at"], "analysis observation"),
                    signal_expires_at=expiry, entry_zone_low=zone.get("low"), entry_zone_high=zone.get("high"),
                    strategy=f"Monatise on-demand {analysis.get('market_state')}", timeframe=analysis["timeframe"],
                    conviction=analysis["conviction"], recommended_risk_percent=analysis["recommended_risk_percent"],
                    evidence_bundle={
                        "market_data_provenance": analysis["market_data_provenance"], "session": analysis["session"],
                        "liquidity": analysis["liquidity"], "market_structure": analysis["structure"],
                        "supply_demand": analysis["supply_demand"], "fibonacci": analysis["fibonacci"],
                        "order_flow": analysis["order_flow"],
                    }, now=observed,
                )
            except FTMOMasterError as exc:
                if "proposal identity collision" not in str(exc):
                    raise
                proposal_id = hashlib.sha256(f"signal:{analysis['signal_id']}".encode()).hexdigest()[:12]
                stored_proposal = await self.repository.proposal(proposal_id)
                if stored_proposal is None or stored_proposal[0].get("analysis_id") != analysis_id:
                    raise
                proposal = stored_proposal[0]
            await self.repository.update_quote_request(quote_request_id, {
                "state": "QUOTE_VALIDATED", "quote_validated_at": observed.isoformat(),
                "proposal_id": proposal["proposal_id"], "lease_until": None,
            })
            await self.repository.audit("quote_validated", quote_request_id, {
                "analysis_id": analysis_id, "quote_request_id": quote_request_id,
                "proposal_id": proposal["proposal_id"], "quote_age_ms": proposal.get("quote_age_ms"),
            })
            completed = await self.repository.update_quote_request(quote_request_id, {
                "state": "PROPOSAL_CREATED", "proposal_id": proposal["proposal_id"],
                "proposal_created_at": observed.isoformat(),
                "lease_until": None, "last_error": None,
            })
            await self.repository.update_telegram_analysis(analysis_id, {
                "lifecycle_state": "PROPOSAL_CREATED", "proposal_id": proposal["proposal_id"],
            })
            await self.repository.audit("quote_proposal_created", quote_request_id, {
                "analysis_id": analysis_id, "quote_request_id": quote_request_id,
                "proposal_id": proposal["proposal_id"],
            })
            return completed, proposal
        except (FTMOMasterError, KeyError, ValueError) as exc:
            reason = str(exc)
            attempts = int(claimed.get("retry_count") or 0)
            terminal = self._terminal_quote_error(reason) or attempts >= int(claimed.get("maximum_attempts") or 4)
            next_retry = observed + timedelta(seconds=(2, 5, 10, 20)[min(attempts - 1, 3)])
            failed = await self.repository.update_quote_request(quote_request_id, {
                "state": "FAILED" if terminal else "WAITING_FOR_QUOTE",
                "last_error": reason, "last_failure_at": observed.isoformat(),
                "next_retry_at": next_retry.isoformat(), "lease_until": None,
            })
            await self.repository.update_telegram_analysis(analysis_id, {
                "lifecycle_state": "QUOTE_FAILED" if terminal else "WAITING_FOR_QUOTE",
            })
            await self.repository.audit("quote_rejected", quote_request_id, {
                "analysis_id": analysis_id, "quote_request_id": quote_request_id,
                "reason": reason, "retryable": not terminal, "attempt": attempts,
            })
            return failed, None

    def authorized(self, user_id: str | None, chat_type: str | None) -> bool:
        return bool(user_id and chat_type == "private" and user_id in self.configuration.authorized_user_ids)

    @staticmethod
    def _symbol_key(value: str) -> str:
        return "".join(character for character in value.upper() if character.isalnum())

    def _verified_instrument_mapping(
        self,
        symbol: str,
        *,
        analysis_provider: str | None = None,
        analysis_instrument: str | None = None,
    ) -> FTMOInstrument:
        requested = self._symbol_key(symbol)
        candidates = [
            item for item in FTMO_REGISTRY.all(enabled_only=True)
            if self._symbol_key(item.ftmo_symbol) == requested
        ]
        if not candidates:
            candidates = [
                item for item in FTMO_REGISTRY.all(enabled_only=True)
                if self._symbol_key(item.underlying_symbol) == requested
            ]
        if len(candidates) != 1:
            raise FTMOMasterError("no unique verified FTMO symbol mapping exists")
        instrument = candidates[0]
        provider = str(analysis_provider or "").strip().casefold()
        provider_instrument = self._symbol_key(str(analysis_instrument or ""))
        if provider == "coinglass":
            if instrument.asset_class is not FTMOAssetClass.CRYPTO or instrument.market_data_provider.casefold() != "coinglass":
                raise FTMOMasterError("CoinGlass analysis is not mapped to an FTMO crypto instrument")
            base = self._symbol_key(instrument.provider_symbol or instrument.underlying_symbol)
            accepted = {base, f"{base}USDT", f"{base}USD"}
            if provider_instrument and provider_instrument not in accepted:
                raise FTMOMasterError("CoinGlass instrument does not match the verified FTMO mapping")
        return instrument

    async def execution_symbol_for(self, instrument: FTMOInstrument, *, now: datetime | None = None) -> str:
        """Resolve the exact symbol spelling exposed by the identity-matched EA."""
        bridge = await self._healthy_bridge(_utc(now))
        accepted = {self._symbol_key(instrument.ftmo_symbol)}
        if instrument.asset_class is FTMOAssetClass.CRYPTO:
            accepted.add(self._symbol_key(f"{instrument.underlying_symbol}USD"))
        matches = [symbol for symbol in (bridge.get("quotes") or {}) if self._symbol_key(symbol) in accepted]
        if len(matches) != 1:
            raise FTMOMasterError("FTMO execution symbol could not be verified from the current MT5 heartbeat")
        return matches[0]

    @staticmethod
    def _execution_snapshot(symbol: str, quote: Mapping[str, Any], bridge: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "execution_broker": "FTMO",
            "execution_symbol": symbol,
            "account_id": str(bridge.get("account_id") or ""),
            "server": str(bridge.get("server") or ""),
            "currency": str(bridge.get("currency") or ""),
            "terminal_build": str(bridge.get("terminal_build") or ""),
            "ea_version": str(bridge.get("ea_version") or ""),
            "identity_match": bool(bridge.get("identity_match")),
            "ftmo_bid": str(quote["bid"]),
            "ftmo_ask": str(quote["ask"]),
            "spread": str(Decimal(str(quote["ask"])) - Decimal(str(quote["bid"]))),
            "quote_timestamp": str(quote["timestamp"]),
            "quote_observed_at_utc": str(quote.get("quote_observed_at_utc") or quote["timestamp"]),
            "broker_time": quote.get("broker_time"),
            "broker_time_offset_seconds": int(quote.get("broker_time_offset_seconds", 0) or 0),
            "render_received_at_utc": quote.get("render_received_at_utc") or bridge.get("observed_at"),
            "computed_quote_age_ms": quote.get("computed_quote_age_ms"),
            "clock_skew_ms": quote.get("clock_skew_ms"),
            "quote_freshness_state": quote.get("quote_freshness_state"),
            "digits": int(quote.get("digits", 0)),
            "point": str(quote.get("point", quote["tick_size"])),
            "tick_size": str(quote["tick_size"]),
            "tick_value": str(quote["tick_value"]),
            "tick_value_loss": str(quote.get("tick_value_loss", quote["tick_value"])),
            "tick_value_profit": str(quote.get("tick_value_profit", quote["tick_value"])),
            "contract_size": str(quote.get("contract_size", "1")),
            "minimum_volume": str(quote["volume_min"]),
            "maximum_volume": str(quote["volume_max"]),
            "volume_step": str(quote["volume_step"]),
            "stop_level": str(quote.get("stops_level", "0")),
            "freeze_level": str(quote.get("freeze_level", "0")),
            "trading_status": str(quote.get("trade_mode", "full")),
            "account_equity": str(bridge["equity"]),
            "account_balance": str(bridge["balance"]),
            "free_margin": str(bridge.get("free_margin", bridge["equity"])),
            "existing_positions": len(bridge.get("positions") or ()),
            "existing_orders": len(bridge.get("orders") or ()),
        }

    async def _validated_open_fields(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        stop_loss: Any,
        take_profit: Any,
        entry: Any | None,
        now: datetime,
        reference_entry: Any | None = None,
        entry_zone_low: Any | None = None,
        entry_zone_high: Any | None = None,
        risk_fraction_limit: Any | None = None,
    ) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        side = side.strip().casefold()
        order_type = order_type.strip().casefold()
        if side not in {"buy", "sell"} or order_type not in {"market", "limit", "stop"}:
            raise FTMOMasterError("trade side/type must be buy|sell and market|limit|stop")
        bridge = await self._healthy_bridge(now)
        quote = (bridge.get("quotes") or {}).get(symbol)
        if quote is None:
            raise FTMOMasterError("FTMO bridge has no current quote for that symbol")
        quote_at = _timestamp(quote.get("quote_observed_at_utc") or quote.get("timestamp"), "FTMO quote timestamp")
        quote_age = (now - quote_at).total_seconds()
        if quote_age < -float(self.configuration.quote_future_tolerance_seconds):
            raise FTMOMasterError("FTMO quote timestamp is materially in the future (CLOCK_SKEW_DETECTED)")
        if quote_age > self.configuration.quote_max_age_seconds:
            raise FTMOMasterError("FTMO quote is stale")
        if str(quote.get("trade_mode", "full")).strip().casefold() not in {"full", "4", "symbol_trade_mode_full"}:
            raise FTMOMasterError("FTMO symbol is not fully enabled for trading")
        bid, ask = Decimal(str(quote["bid"])), Decimal(str(quote["ask"]))
        tick_size = Decimal(str(quote["tick_size"]))
        tick_value = Decimal(str(quote.get("tick_value_loss", quote["tick_value"])))
        spread_ticks = (ask - bid) / tick_size
        if spread_ticks > self.configuration.maximum_spread_ticks:
            raise FTMOMasterError("FTMO spread exceeds policy")
        requested_entry = (ask if side == "buy" else bid) if order_type == "market" else _decimal(entry, "entry", positive=True)
        if reference_entry is not None:
            reference = _decimal(reference_entry, "reference entry", positive=True)
            deviation_bps = abs(requested_entry - reference) / reference * Decimal("10000")
            if deviation_bps > self.configuration.maximum_entry_deviation_bps:
                raise FTMOMasterError("price moved outside the approved Monatise entry tolerance")
        if entry_zone_low is not None and requested_entry < _decimal(entry_zone_low, "entry zone low", positive=True):
            raise FTMOMasterError("price moved below the approved Monatise entry zone")
        if entry_zone_high is not None and requested_entry > _decimal(entry_zone_high, "entry zone high", positive=True):
            raise FTMOMasterError("price moved above the approved Monatise entry zone")
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
        minimum_stop = max(Decimal(str(quote.get("stops_level", 0))), Decimal(str(quote.get("freeze_level", 0)))) * tick_size
        stop_distance = abs(requested_entry - stop)
        if stop_distance < minimum_stop:
            raise FTMOMasterError("stop distance is below the FTMO symbol minimum")
        reward_distance = abs(target - requested_entry)
        if reward_distance / stop_distance < self.configuration.minimum_reward_risk:
            raise FTMOMasterError("reward/risk is below execution policy")
        equity = Decimal(str(bridge["equity"]))
        loss_today = max(ZERO, Decimal(str(bridge["daily_start_equity"])) - equity)
        daily_remaining = Decimal(str(bridge["daily_loss_limit"])) - loss_today
        total_loss = max(ZERO, Decimal(str(bridge["initial_balance"])) - equity)
        total_remaining = Decimal(str(bridge["total_loss_limit"])) - total_loss
        exposures = tuple(item for item in (*tuple(bridge.get("positions") or ()), *tuple(bridge.get("orders") or ())) if isinstance(item, Mapping))
        if len(exposures) >= self.configuration.maximum_open_exposures:
            raise FTMOMasterError("maximum open position/pending-order exposure limit is reached")
        if any(str(item.get("symbol") or "").upper() == symbol for item in exposures):
            raise FTMOMasterError("a conflicting FTMO exposure already exists for the symbol")
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
            existing_open_risk += abs(position_entry - position_stop) / Decimal(str(position_quote["tick_size"])) * Decimal(str(position_quote.get("tick_value_loss", position_quote["tick_value"]))) * position_volume
        available_loss_capacity = min(daily_remaining, total_remaining) - existing_open_risk
        requested_risk_fraction = self.configuration.risk_fraction if risk_fraction_limit is None else _decimal(
            risk_fraction_limit, "recommended risk fraction", positive=True,
        )
        requested_risk_fraction = min(requested_risk_fraction, self.configuration.risk_fraction, MAX_RISK_FRACTION_PER_TRADE)
        risk_budget = min(risk_ceiling(equity), equity * requested_risk_fraction, available_loss_capacity)
        if risk_budget <= ZERO:
            raise FTMOMasterError("FTMO daily/total loss capacity is exhausted")
        loss_per_lot = (stop_distance / tick_size) * tick_value
        step = Decimal(str(quote["volume_step"]))
        volume = ((risk_budget / loss_per_lot) / step).to_integral_value(rounding=ROUND_FLOOR) * step
        volume = min(volume, Decimal(str(quote["volume_max"])))
        if volume < Decimal(str(quote["volume_min"])):
            raise FTMOMasterError("minimum FTMO volume would exceed the permitted risk")
        actual_risk = loss_per_lot * volume
        if existing_open_risk + actual_risk > risk_ceiling(equity):
            raise FTMOMasterError("FTMO total open risk limit would be exceeded")
        return {
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "entry": str(requested_entry),
            "stop_loss": str(stop),
            "take_profit": str(target),
            "volume": str(volume),
            "risk_amount": str(actual_risk),
            "risk_fraction": str(actual_risk / equity),
            "recommended_risk_fraction": str(requested_risk_fraction),
            "quote_bid": str(bid),
            "quote_ask": str(ask),
            "quote_timestamp": str(quote["timestamp"]),
            "quote_observed_at_utc": str(quote.get("quote_observed_at_utc") or quote["timestamp"]),
            "quote_age_ms": str(int(round(quote_age * 1000))),
            "quote_freshness_state": "FRESH",
            "spread_ticks": str(spread_ticks),
            "reward_risk": str(reward_distance / stop_distance),
            "execution_snapshot": self._execution_snapshot(symbol, quote, bridge),
        }

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
            quote_at = _timestamp(
                raw_quote.get("quote_observed_at_utc") or raw_quote.get("observed_at_utc") or raw_quote.get("timestamp"),
                "bridge quote observation timestamp",
            )
            quote_age_ms = int(round((observed - quote_at).total_seconds() * 1000))
            if quote_age_ms < -int(self.configuration.quote_future_tolerance_seconds * 1000):
                freshness_state = "CLOCK_SKEW_DETECTED"
            elif quote_age_ms > self.configuration.quote_max_age_seconds * 1000:
                freshness_state = "STALE"
            else:
                freshness_state = "FRESH"
            normalized_quotes[symbol] = {
                "bid": str(bid), "ask": str(ask),
                "timestamp": quote_at.isoformat(),
                "quote_observed_at_utc": quote_at.isoformat(),
                "broker_time": str(raw_quote.get("broker_time") or "") or None,
                "broker_time_offset_seconds": int(
                    raw_quote.get("broker_time_offset_seconds", raw_quote.get("broker_time_offset", 0)) or 0
                ),
                "terminal_local_time": str(raw_quote.get("terminal_local_time") or "") or None,
                "render_received_at_utc": observed.isoformat(),
                "computed_quote_age_ms": quote_age_ms,
                "clock_skew_ms": max(0, -quote_age_ms),
                "quote_freshness_state": freshness_state,
                "digits": int(raw_quote.get("digits", 0)),
                "point": str(_decimal(raw_quote.get("point", raw_quote.get("tick_size")), "point size", positive=True)),
                "tick_size": str(_decimal(raw_quote.get("tick_size"), "tick size", positive=True)),
                "tick_value": str(_decimal(raw_quote.get("tick_value"), "tick value", positive=True)),
                "tick_value_loss": str(_decimal(raw_quote.get("tick_value_loss", raw_quote.get("tick_value")), "loss tick value", positive=True)),
                "tick_value_profit": str(_decimal(raw_quote.get("tick_value_profit", raw_quote.get("tick_value")), "profit tick value", positive=True)),
                "contract_size": str(_decimal(raw_quote.get("contract_size", 1), "contract size", positive=True)),
                "volume_min": str(_decimal(raw_quote.get("volume_min"), "minimum volume", positive=True)),
                "volume_max": str(_decimal(raw_quote.get("volume_max"), "maximum volume", positive=True)),
                "volume_step": str(_decimal(raw_quote.get("volume_step"), "volume step", positive=True)),
                "stops_level": str(_decimal(raw_quote.get("stops_level", 0), "stops level")),
                "freeze_level": str(_decimal(raw_quote.get("freeze_level", 0), "freeze level")),
                "trade_mode": str(raw_quote.get("trade_mode", "full")),
            }
        snapshot = {
            "account_id": account_id,
            "server": server,
            "currency": currency,
            "balance": str(_decimal(payload.get("balance"), "balance", positive=True)),
            "equity": str(_decimal(payload.get("equity"), "equity", positive=True)),
            "free_margin": str(_decimal(payload.get("free_margin", payload.get("equity")), "free margin")),
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
            "ea_observed_at_utc": str(payload.get("observed_at_utc") or "") or None,
            "broker_time": str(payload.get("broker_time") or "") or None,
            "broker_time_offset_seconds": int(payload.get("broker_time_offset", 0) or 0),
            "terminal_local_time": str(payload.get("terminal_local_time") or "") or None,
            "observed_at": observed.isoformat(),
        }
        await self.repository.save_bridge(snapshot)
        skewed_symbols = sorted(
            symbol for symbol, quote in normalized_quotes.items()
            if quote.get("quote_freshness_state") == "CLOCK_SKEW_DETECTED"
        )
        if skewed_symbols:
            LOGGER.warning(
                "FTMO bridge quote clock skew detected; execution will fail closed",
                extra={"symbol_count": len(skewed_symbols), "symbols": skewed_symbols},
            )
        lifecycle_events: tuple[dict[str, Any], ...] = ()
        if identity_match:
            lifecycle_events = await self._reconcile_proposals_from_heartbeat(snapshot, observed)
        await self.repository.audit("bridge_heartbeat", _mask_account(account_id) or "unknown", {
            "identity_match": identity_match, "terminal_connected": snapshot["terminal_connected"],
            "trade_allowed": snapshot["trade_allowed"], "quote_count": len(normalized_quotes),
            "clock_skew_quote_count": sum(
                quote.get("quote_freshness_state") == "CLOCK_SKEW_DETECTED"
                for quote in normalized_quotes.values()
            ),
        })
        if not identity_match:
            raise FTMOMasterError("FTMO bridge account/server/currency mismatch")
        return {
            "status": "accepted", "identity_match": True,
            "execution_enabled": self.configuration.activation_configured,
            "lifecycle_events": list(lifecycle_events),
        }

    async def _reconcile_proposals_from_heartbeat(
        self, snapshot: Mapping[str, Any], observed: datetime,
    ) -> tuple[dict[str, Any], ...]:
        positions = tuple(item for item in snapshot.get("positions") or () if isinstance(item, Mapping))
        orders = tuple(item for item in snapshot.get("orders") or () if isinstance(item, Mapping))
        events: list[dict[str, Any]] = []
        for proposal in await self.repository.proposals():
            command_id = str(proposal.get("command_id") or "")
            broker_ticket = str(proposal.get("broker_ticket") or "")
            if not command_id and not broker_ticket:
                continue
            command_prefix = command_id[:16]

            def matches(item: Mapping[str, Any]) -> bool:
                ticket = str(item.get("ticket") or "")
                comment = str(item.get("comment") or "")
                return bool((broker_ticket and ticket == broker_ticket) or (command_prefix and command_prefix in comment))

            position = next((item for item in positions if matches(item)), None)
            order = next((item for item in orders if matches(item)), None)
            lifecycle = str(proposal.get("lifecycle_state") or "")
            next_state = "POSITION_OPEN" if position is not None else "BROKER_ACCEPTED" if order is not None else None
            if next_state is None and lifecycle in {"POSITION_OPEN", "PARTIAL_CLOSE"}:
                next_state = "POSITION_CLOSED"
            if next_state is None or next_state == lifecycle:
                continue
            stored = await self.repository.proposal(str(proposal["proposal_id"]))
            if stored is None:
                continue
            value, version = stored
            value["lifecycle_state"] = next_state
            value["position_observed_at"] = observed.isoformat()
            if position is not None:
                value["position_snapshot"] = dict(position)
            if order is not None:
                value["order_snapshot"] = dict(order)
            if next_state == "POSITION_CLOSED":
                value["status"] = ProposalStatus.RECONCILED.value
                value["position_closed_at"] = observed.isoformat()
            await self.repository.update_proposal(value["proposal_id"], value, version)
            await self.repository.audit("position_lifecycle", value["proposal_id"], {"state": next_state})
            evidence = dict(position or order or value.get("position_snapshot") or value.get("order_snapshot") or {})
            events.append({
                "proposal_id": value["proposal_id"], "command_id": command_id,
                "lifecycle_state": next_state, "symbol": value.get("symbol"), "side": value.get("side"),
                "entry": evidence.get("price_open", value.get("entry")),
                "volume": evidence.get("volume", value.get("volume")),
                "stop_loss": evidence.get("sl", value.get("stop_loss")),
                "take_profit": evidence.get("tp", value.get("take_profit")),
                "broker_ticket": evidence.get("ticket", broker_ticket),
                "unrealized_profit": evidence.get("profit"),
                "analysis_provider": value.get("analysis_provider"),
            })
        return tuple(events)

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
        quote_freshness = {
            symbol: {
                "quote_observed_at_utc": quote.get("quote_observed_at_utc"),
                "render_received_at_utc": quote.get("render_received_at_utc"),
                "computed_quote_age_ms": quote.get("computed_quote_age_ms"),
                "clock_skew_ms": quote.get("clock_skew_ms"),
                "quote_freshness_state": quote.get("quote_freshness_state"),
            }
            for symbol, quote in ((bridge or {}).get("quotes") or {}).items()
        }
        quote_clock_skew_detected = any(
            item.get("quote_freshness_state") == "CLOCK_SKEW_DETECTED"
            for item in quote_freshness.values()
        )
        execution_ready = bool(
            self.configuration.activation_configured
            and bridge_healthy
            and bridge and bridge.get("trade_allowed")
            and armed
            and not kill_switch
            and not quote_clock_skew_detected
        )
        return {
            **self.configuration.public_status(),
            "bridge_healthy": bridge_healthy,
            "heartbeat_age_seconds": heartbeat_age,
            "terminal_connected": bool(bridge and bridge.get("terminal_connected")),
            "trade_allowed": bool(bridge and bridge.get("trade_allowed")),
            "ea_attached": bool(bridge and bridge.get("ea_attached")),
            "quote_symbols": sorted((bridge or {}).get("quotes", {})),
            "quote_freshness": quote_freshness,
            "quote_clock_skew_detected": quote_clock_skew_detected,
            "armed": armed,
            "armed_until": armed_until if armed else None,
            "execution_session_armed": armed,
            "execution_session_id": control.get("execution_session_id") if armed else None,
            "execution_session_started_at": control.get("execution_session_started_at") if armed else None,
            "execution_session_expiry": armed_until if armed else None,
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
        started = _utc(now)
        until = started + timedelta(seconds=duration)
        session_id = secrets.token_hex(16)
        await self.repository.update_control(
            armed_until=until.isoformat(), armed_by=actor,
            execution_session_id=session_id, execution_session_started_at=started.isoformat(),
        )
        await self.repository.audit("execution_armed", actor, {
            "execution_session_id": session_id, "started_at": started.isoformat(), "armed_until": until.isoformat(),
        })
        return await self.status(now=now)

    async def disarm(self, actor: str) -> dict[str, Any]:
        await self.repository.update_control(
            armed_until=None, armed_by=None, execution_session_id=None, execution_session_started_at=None,
        )
        await self.repository.audit("execution_disarmed", actor, {})
        return await self.status()

    async def kill(self, actor: str) -> dict[str, Any]:
        await self.repository.update_control(
            kill_switch=True, armed_until=None, armed_by=None,
            execution_session_id=None, execution_session_started_at=None,
        )
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
        metadata: Mapping[str, Any] | None = None,
        expires_at: datetime | None = None,
        risk_fraction_limit: Any | None = None,
    ) -> dict[str, Any]:
        observed = _utc(now)
        if actor not in self.configuration.authorized_user_ids and actor != "monatise-scanner":
            raise FTMOMasterError("Telegram user is not authorized")
        fields = await self._validated_open_fields(
            symbol=symbol, side=side, order_type=order_type, stop_loss=stop_loss,
            take_profit=take_profit, entry=entry, now=observed,
            risk_fraction_limit=risk_fraction_limit,
        )
        instrument = self._verified_instrument_mapping(symbol)
        session_context = classify_market_session(
            observed,
            instrument=instrument,
            trade_mode=fields["execution_snapshot"]["trading_status"],
        )
        if not session_allows_execution(session_context):
            raise FTMOMasterError("current market session does not permit an executable proposal")
        proposal_id = _proposal_id or secrets.token_hex(6)
        proposal_expiry = _utc(expires_at) if expires_at is not None else observed + timedelta(minutes=5)
        if proposal_expiry <= observed:
            raise FTMOMasterError("signal has already expired")
        details = dict(metadata or {})
        proposal = {
            "proposal_id": proposal_id,
            "kind": "open_trade",
            "status": ProposalStatus.PENDING.value,
            "lifecycle_state": "AWAITING_APPROVAL",
            "actor": actor,
            **fields,
            **details,
            **session_context.to_dict(),
            "session_context": session_context.to_dict(),
            "created_at": observed.isoformat(),
            "expires_at": proposal_expiry.isoformat(),
            "confirmation_required": True,
            "approval_id": None,
            "command_id": None,
            "execution_id": None,
            "broker_ticket": None,
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
        analysis_state: str | None = None,
        confirmation_status: str | None = None,
        now: datetime | None = None,
        analysis_id: str | None = None,
        analysis_provider: str | None = None,
        analysis_instrument: str | None = None,
        analysis_exchange: str | None = None,
        analysis_observed_at: datetime | None = None,
        signal_expires_at: datetime | None = None,
        entry_zone_low: Any | None = None,
        entry_zone_high: Any | None = None,
        order_type: str = "market",
        strategy: str | None = None,
        timeframe: str | None = None,
        conviction: Any | None = None,
        evidence_bundle: Mapping[str, Any] | None = None,
        supersedes_signal_id: str | None = None,
        telegram_request_id: str | None = None,
        quote_request_id: str | None = None,
        recommended_risk_percent: Any | None = None,
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
        normalized_state = str(analysis_state or "").strip().upper()
        expected_state = "LONG" if side == "buy" else "SHORT"
        if normalized_state != expected_state:
            raise FTMOMasterError("Monatise signal state is not executable or conflicts with direction")
        if str(confirmation_status or "").strip().casefold() != "confirmed":
            raise FTMOMasterError("Monatise signal is not fully confirmed")
        observed = _utc(now)
        if not str(signal_id).strip():
            raise FTMOMasterError("signal identity is required")
        instrument = self._verified_instrument_mapping(
            symbol,
            analysis_provider=analysis_provider,
            analysis_instrument=analysis_instrument,
        )
        execution_symbol = symbol.strip().upper()
        bridge = await self._healthy_bridge(observed)
        quote = (bridge.get("quotes") or {}).get(execution_symbol)
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
        ftmo_zone_low = None if entry_zone_low is None else ftmo_entry * (_decimal(entry_zone_low, "entry zone low", positive=True) / entry)
        ftmo_zone_high = None if entry_zone_high is None else ftmo_entry * (_decimal(entry_zone_high, "entry zone high", positive=True) / entry)
        if ftmo_zone_low is not None and ftmo_zone_high is not None and ftmo_zone_low > ftmo_zone_high:
            raise FTMOMasterError("analysis entry zone is inverted")
        proposal_id = hashlib.sha256(f"signal:{signal_id}".encode()).hexdigest()[:12]
        if supersedes_signal_id:
            for previous in await self.repository.proposals():
                if previous.get("signal_id") != supersedes_signal_id or previous.get("status") != ProposalStatus.PENDING.value:
                    continue
                stored_previous = await self.repository.proposal(previous["proposal_id"])
                if stored_previous is None:
                    continue
                previous_value, previous_version = stored_previous
                previous_value.update({
                    "status": ProposalStatus.INVALIDATED.value,
                    "lifecycle_state": "INVALIDATED",
                    "invalidated_at": observed.isoformat(),
                    "superseded_by_signal_id": signal_id,
                })
                await self.repository.update_proposal(previous["proposal_id"], previous_value, previous_version)
                await self.repository.audit("proposal_superseded", previous["proposal_id"], {"superseded_by_signal_id": signal_id})
        provider = str(analysis_provider or instrument.market_data_provider or source).strip().casefold()
        provider_instrument = str(analysis_instrument or instrument.provider_symbol or instrument.underlying_symbol)
        metadata = {
            "telegram_request_id": str(telegram_request_id or "") or None,
            "quote_request_id": str(quote_request_id or "") or None,
            "analysis_id": str(analysis_id or signal_id),
            "signal_id": str(signal_id),
            "analysis_source": source,
            "analysis_state": normalized_state,
            "confirmation_status": "confirmed",
            "analysis_provider": provider,
            "analysis_instrument": provider_instrument,
            "analysis_exchange": str(analysis_exchange or instrument.exchange),
            "analysis_price": str(entry),
            "analysis_entry": str(entry),
            "analysis_stop": str(stop),
            "analysis_target": str(target),
            "analysis_risk_fraction": str(risk_fraction),
            "analysis_reward_fraction": str(reward_fraction),
            "analysis_observed_at": _utc(analysis_observed_at or observed).isoformat(),
            "strategy": strategy or "Monatise confirmed setup",
            "timeframe": timeframe or "unknown",
            "conviction": conviction,
            "evidence_bundle": dict(evidence_bundle or {}),
            "mapping": {
                "canonical_instrument": instrument.underlying_symbol,
                "analysis_provider": provider,
                "analysis_instrument": provider_instrument,
                "ftmo_registry_symbol": instrument.ftmo_symbol,
                "ftmo_execution_symbol": execution_symbol,
                "asset_class": instrument.asset_class.value,
                "registry_version": instrument.registry_version,
                "registry_verified_at": instrument.last_verified_at.isoformat(),
                "execution_available": instrument.enabled,
            },
            "entry_zone_low": str(ftmo_zone_low) if ftmo_zone_low is not None else None,
            "entry_zone_high": str(ftmo_zone_high) if ftmo_zone_high is not None else None,
            "level_conversion": "external_relative_structure_to_ftmo_bid_ask",
            "approval_level_conversion": "analysis_relative_structure_to_current_ftmo_bid_ask",
        }
        proposal = await self.create_trade_proposal(
            actor="monatise-scanner", symbol=execution_symbol, side=side, order_type=order_type,
            entry=ftmo_entry if order_type != "market" else None,
            stop_loss=ftmo_stop, take_profit=ftmo_target, now=observed, _proposal_id=proposal_id,
            metadata=metadata,
            expires_at=signal_expires_at,
            risk_fraction_limit=(
                _decimal(recommended_risk_percent, "recommended risk percent", positive=True) / Decimal("100")
                if recommended_risk_percent is not None else None
            ),
        )
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
        await self.repository.audit("approval_received", proposal_id, {
            "actor": actor, "analysis_id": proposal.get("analysis_id"),
            "quote_request_id": proposal.get("quote_request_id"), "proposal_id": proposal_id,
        })
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
                ("quote clock skew", readiness.get("quote_clock_skew_detected", False)),
            ) if blocked]
            await self.repository.audit("approval_blocked", proposal_id, {"actor": actor, "blockers": blockers})
            raise FTMOMasterError("execution is blocked by: " + ", ".join(blockers))
        # Approval authorizes a fresh attempt, never the stale preview price.
        bridge = await self._healthy_bridge(observed)
        if proposal["kind"] == "open_trade":
            quote = (bridge.get("quotes") or {}).get(proposal["symbol"])
            if not quote or (observed - datetime.fromisoformat(quote["timestamp"])).total_seconds() > self.configuration.quote_max_age_seconds:
                raise FTMOMasterError("FTMO quote is stale at approval")
            instrument = self._verified_instrument_mapping(
                proposal["symbol"],
                analysis_provider=proposal.get("analysis_provider"),
                analysis_instrument=proposal.get("analysis_instrument"),
            )
            approval_session = classify_market_session(
                observed, instrument=instrument, trade_mode=quote.get("trade_mode"),
            )
            if not session_allows_execution(approval_session):
                raise FTMOMasterError("current market session does not permit execution")
            stop_loss, take_profit = proposal["stop_loss"], proposal["take_profit"]
            if proposal.get("analysis_risk_fraction") and proposal.get("analysis_reward_fraction") and proposal.get("order_type") == "market":
                live_entry = Decimal(str(quote["ask"] if proposal["side"] == "buy" else quote["bid"]))
                risk_fraction = Decimal(str(proposal["analysis_risk_fraction"]))
                reward_fraction = Decimal(str(proposal["analysis_reward_fraction"]))
                if proposal["side"] == "buy":
                    stop_loss = live_entry * (Decimal("1") - risk_fraction)
                    take_profit = live_entry * (Decimal("1") + reward_fraction)
                else:
                    stop_loss = live_entry * (Decimal("1") + risk_fraction)
                    take_profit = live_entry * (Decimal("1") - reward_fraction)
                tick = Decimal(str(quote["tick_size"]))
                stop_loss = (stop_loss / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
                take_profit = (take_profit / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
            await self.repository.audit("proposal_revalidating", proposal_id, {
                "actor": actor, "ftmo_bid": str(quote["bid"]), "ftmo_ask": str(quote["ask"]),
                "quote_timestamp": str(quote["timestamp"]),
            })
            try:
                refreshed = await self._validated_open_fields(
                    symbol=proposal["symbol"], side=proposal["side"], order_type=proposal["order_type"],
                    stop_loss=stop_loss, take_profit=take_profit,
                    entry=proposal.get("entry") if proposal["order_type"] != "market" else None,
                    now=observed,
                    reference_entry=proposal.get("entry") if proposal["order_type"] == "market" else None,
                    entry_zone_low=proposal.get("entry_zone_low"), entry_zone_high=proposal.get("entry_zone_high"),
                    risk_fraction_limit=proposal.get("recommended_risk_fraction"),
                )
            except FTMOMasterError as exc:
                reason = str(exc)
                if any(fragment in reason for fragment in ("price moved", "reward/risk", "levels require")):
                    proposal.update({
                        "status": ProposalStatus.INVALIDATED.value, "lifecycle_state": "INVALIDATED",
                        "invalidated_at": observed.isoformat(), "invalidation_reason": reason,
                    })
                    await self.repository.update_proposal(proposal_id, proposal, version)
                    await self.repository.audit("proposal_invalidated", proposal_id, {"actor": actor, "reason": reason})
                if "exposure limit" in reason:
                    raise FTMOMasterError(reason + " at approval") from exc
                raise
            proposal.update(refreshed)
            proposal["approval_execution_snapshot"] = refreshed["execution_snapshot"]
            proposal["approval_session_context"] = approval_session.to_dict()

        approval_id = hashlib.sha256(f"approval:{proposal_id}:{actor}:{observed.isoformat()}".encode()).hexdigest()
        command_id = hashlib.sha256(f"{proposal_id}:{proposal['kind']}:{proposal.get('operation', 'open')}".encode()).hexdigest()
        execution_id = hashlib.sha256(f"execution:{command_id}".encode()).hexdigest()
        command = {
            "command_id": command_id,
            "proposal_id": proposal_id,
            "analysis_id": proposal.get("analysis_id"),
            "quote_request_id": proposal.get("quote_request_id"),
            "signal_id": proposal.get("signal_id"),
            "telegram_request_id": proposal.get("telegram_request_id"),
            "approval_id": approval_id,
            "execution_id": execution_id,
            "operation": proposal.get("operation", "open"),
            "payload": {key: proposal.get(key) for key in (
                "symbol", "side", "order_type", "entry", "stop_loss", "take_profit", "volume", "target_id", "value",
                "analysis_id", "quote_request_id", "signal_id",
                "telegram_request_id",
            ) if proposal.get(key) is not None},
            "expected_account_id": self.configuration.account_id,
            "expected_server": self.configuration.server,
            "expected_currency": self.configuration.currency,
            "status": CommandStatus.READY.value,
            "lifecycle_state": "EXECUTION_QUEUED",
            "created_at": observed.isoformat(),
            "expires_at": min(datetime.fromisoformat(proposal["expires_at"]), observed + timedelta(seconds=30)).isoformat(),
            "automatic_resend": "same_command_id_only",
            "approval": {"approved_by": actor, "approved_at": observed.isoformat(), "approval_id": approval_id},
            "execution_session": {
                "execution_session_armed": readiness.get("execution_session_armed"),
                "execution_session_id": readiness.get("execution_session_id"),
                "execution_session_started_at": readiness.get("execution_session_started_at"),
                "execution_session_expiry": readiness.get("execution_session_expiry"),
                "kill_switch": readiness.get("kill_switch"),
                "manual_master_execution_enabled": self.configuration.activation_configured,
                "autonomous_execution_enabled": False,
            },
            "analysis_provenance": {key: proposal.get(key) for key in (
                "analysis_id", "quote_request_id", "signal_id", "analysis_source", "analysis_provider", "analysis_instrument",
                "telegram_request_id",
                "analysis_exchange", "analysis_price", "analysis_observed_at", "analysis_state",
                "confirmation_status", "strategy", "timeframe",
                "conviction", "evidence_bundle", "mapping",
            ) if proposal.get(key) is not None},
            "execution_snapshot": proposal.get("approval_execution_snapshot"),
            "market_session": proposal.get("approval_session_context"),
            "risk_policy": {
                "risk_fraction": str(self.configuration.risk_fraction),
                "maximum_risk_percent_per_trade": str(MAX_RISK_PERCENT_PER_TRADE),
                "authority": "percentage_only_current_equity",
                "maximum_open_exposures": self.configuration.maximum_open_exposures,
                "actual_risk_amount": proposal.get("risk_amount"),
                "actual_risk_fraction": proposal.get("risk_fraction"),
                "recommended_risk_fraction": proposal.get("recommended_risk_fraction"),
            },
        }
        command["payload"].update({
            "approval_id": approval_id,
            "execution_id": execution_id,
            "expires_epoch": str(int(min(datetime.fromisoformat(proposal["expires_at"]), observed + timedelta(seconds=30)).timestamp())),
        })
        if not await self.repository.save_command(command):
            raise FTMOMasterError("duplicate execution command")
        proposal.update({
            "status": ProposalStatus.COMMAND_CREATED.value, "lifecycle_state": "EXECUTION_QUEUED",
            "approved_by": actor, "approved_at": observed.isoformat(), "approval_id": approval_id,
            "command_id": command_id, "execution_id": execution_id,
        })
        await self.repository.update_proposal(proposal_id, proposal, version)
        await self.repository.audit("proposal_approved", proposal_id, {
            "actor": actor, "approval_id": approval_id, "command_id": command_id,
            "execution_id": execution_id, "analysis_id": proposal.get("analysis_id"),
            "quote_request_id": proposal.get("quote_request_id"), "proposal_id": proposal_id,
            "risk_amount": proposal.get("risk_amount"),
        })
        telegram_request_id = proposal.get("telegram_request_id")
        telegram_request = await self.repository.telegram_analysis_request(telegram_request_id) if telegram_request_id else None
        if telegram_request is not None:
            await self.repository.finish_telegram_analysis_request(telegram_request_id, {
                "approval_status": "approved",
                "approval_id": approval_id,
                "command_id": command_id,
                "execution_id": execution_id,
                "approved_at": observed.isoformat(),
            })
        return command

    async def reject(self, proposal_id: str, actor: str) -> dict[str, Any]:
        if actor not in self.configuration.authorized_user_ids:
            raise FTMOMasterError("Telegram user is not authorized")
        stored = await self.repository.proposal(proposal_id)
        if stored is None:
            raise FTMOMasterError("unknown proposal")
        proposal, version = stored
        if proposal.get("status") != ProposalStatus.PENDING.value:
            raise FTMOMasterError(f"proposal is already {proposal.get('status')}")
        proposal.update({
            "status": ProposalStatus.REJECTED.value, "lifecycle_state": "REJECTED",
            "rejected_by": actor, "rejected_at": _utc().isoformat(),
        })
        await self.repository.update_proposal(proposal_id, proposal, version)
        await self.repository.audit("proposal_rejected", proposal_id, {"actor": actor})
        telegram_request_id = proposal.get("telegram_request_id")
        telegram_request = await self.repository.telegram_analysis_request(telegram_request_id) if telegram_request_id else None
        if telegram_request is not None:
            await self.repository.finish_telegram_analysis_request(telegram_request_id, {
                "approval_status": "rejected",
                "rejected_at": proposal["rejected_at"],
            })
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
                "lifecycle_state": "EXECUTION_QUEUED",
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
            "requested_price": str(payload.get("requested_price") or "") or None,
            "fill_price": str(payload.get("fill_price") or "") or None,
            "slippage": str(payload.get("slippage") or "") or None,
            "executed_volume": str(payload.get("executed_volume") or "") or None,
            "executed_stop_loss": str(payload.get("executed_stop_loss") or "") or None,
            "executed_take_profit": str(payload.get("executed_take_profit") or "") or None,
        }
        if raw_status == CommandStatus.BROKER_UNCERTAIN.value:
            changes["automatic_resend"] = False
        lifecycle = {
            CommandStatus.ACCEPTED.value: "BROKER_ACCEPTED",
            CommandStatus.RECONCILED.value: "BROKER_ACCEPTED",
            CommandStatus.REJECTED.value: "EXECUTION_FAILED",
            CommandStatus.BROKER_UNCERTAIN.value: "EXECUTION_FAILED",
            CommandStatus.SUBMITTING.value: "MT5_RECEIVED",
        }.get(raw_status, "MT5_RECEIVED")
        changes["lifecycle_state"] = lifecycle
        previous_record = await self.repository.command(command_id)
        if previous_record is None:
            raise FTMOMasterError("unknown bridge command")
        previous = previous_record[0]
        evidence_keys = (
            "status", "lifecycle_state", "broker_ticket", "broker_retcode",
            "requested_price", "fill_price", "slippage", "executed_volume",
            "executed_stop_loss", "executed_take_profit",
        )
        notification_required = any(previous.get(key) != changes.get(key) for key in evidence_keys)
        command = await self.repository.update_command(command_id, changes)
        stored_proposal = await self.repository.proposal(str(command.get("proposal_id") or ""))
        if stored_proposal is not None:
            proposal, version = stored_proposal
            proposal_status = {
                CommandStatus.REJECTED.value: ProposalStatus.EXECUTION_FAILED.value,
                CommandStatus.BROKER_UNCERTAIN.value: ProposalStatus.RECONCILIATION_REQUIRED.value,
                CommandStatus.RECONCILED.value: ProposalStatus.RECONCILED.value,
            }.get(raw_status, proposal.get("status"))
            proposal.update({
                "status": proposal_status,
                "lifecycle_state": lifecycle,
                "broker_ticket": changes["broker_ticket"],
                "broker_retcode": changes["broker_retcode"],
                "broker_observed_at": changes["broker_observed_at"],
                "execution_result": {key: value for key, value in changes.items() if value is not None},
            })
            await self.repository.update_proposal(proposal["proposal_id"], proposal, version)
        await self.repository.audit("bridge_acknowledgement", command_id, {
            "status": raw_status, "lifecycle_state": lifecycle, "broker_ticket": changes["broker_ticket"],
            "broker_retcode": changes["broker_retcode"], "fill_price": changes["fill_price"],
            "analysis_id": command.get("analysis_id"), "quote_request_id": command.get("quote_request_id"),
            "proposal_id": command.get("proposal_id"), "execution_id": command.get("execution_id"),
        })
        command["notification_required"] = notification_required
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
            "MONATISE TRADE PROPOSAL",
            f"ID: {proposal['proposal_id']}",
            *((f"Signal: {proposal['signal_id']} | Analysis: {proposal.get('analysis_id') or 'unknown'}",) if proposal.get("signal_id") else ()),
            *((f"Telegram request: {proposal['telegram_request_id']}",) if proposal.get("telegram_request_id") else ()),
            f"Instrument: {proposal['symbol']}",
            f"Direction: {str(proposal['side']).upper()} | Type: {str(proposal['order_type']).upper()}",
            f"Strategy: {proposal.get('strategy') or 'Operator preview'}",
            f"Session: {proposal.get('market_session') or 'UNKNOWN'} | Checked: {proposal.get('session_checked_at') or 'UNKNOWN'}",
            f"Market: {'OPEN' if proposal.get('market_open') is True else 'CLOSED' if proposal.get('market_open') is False else 'UNKNOWN'} | Broker break: {proposal.get('broker_break_proximity') or 'UNKNOWN'}",
            f"Analysis reference price: {proposal.get('analysis_price') or proposal['entry']}",
            f"Proposed SL: {proposal['stop_loss']} | Proposed TP: {proposal['take_profit']}",
            f"Risk ceiling: {MAX_RISK_PERCENT_PER_TRADE:.2f}% | Recommended risk: {Decimal(str(proposal.get('recommended_risk_fraction') or proposal['risk_fraction'])) * 100:.2f}%",
            f"Preview calculated risk: {Decimal(str(proposal['risk_fraction'])) * 100:.2f}%",
            f"Estimated risk: ${proposal['risk_amount']} | Estimated volume: {proposal.get('volume') or 'RECALCULATE AT APPROVAL'} lots",
            f"FTMO preview Bid/Ask: {proposal['quote_bid']} / {proposal['quote_ask']}",
            f"FTMO quote observed UTC: {proposal.get('quote_observed_at_utc') or proposal.get('quote_timestamp') or 'UNKNOWN'} | Age: {proposal.get('quote_age_ms') or 'UNKNOWN'} ms",
            f"Signal expires: {proposal['expires_at']}",
            *((f"Conviction: {proposal['conviction']}",) if proposal.get("conviction") is not None else ()),
            "Status: AWAITING APPROVAL",
            f"Approve: /approve {proposal['proposal_id']} | Reject: /reject {proposal['proposal_id']}",
            "Approval authorizes revalidation at the current FTMO Bid/Ask; it does not authorize this preview price.",
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
        f"Execution session: {status.get('execution_session_id') or 'NONE'} | Expiry: {status.get('execution_session_expiry') or 'NONE'}",
        f"Master gates: {'READY' if status.get('activation_configured') else 'BLOCKED'}",
        f"Execution: {'READY' if status.get('execution_ready') else 'BLOCKED'}",
    ))
