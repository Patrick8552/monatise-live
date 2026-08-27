"""Fail-closed FTMO execution-price boundary and shadow intent models.

External providers may supply analytical context. Only a configured FTMO
platform adapter may supply prices and specifications used by this module.
Order submission is deliberately outside this first, shadow-only boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from enum import StrEnum
from typing import Any, Mapping, Protocol

from monatise.application.risk_policy import MAX_RISK_FRACTION_PER_TRADE, risk_ceiling


ZERO = Decimal("0")


class FTMOValidationError(RuntimeError):
    """An FTMO quote, specification, risk state, or intent is unsafe."""


class FTMOPlatform(StrEnum):
    CTRADER = "ctrader"
    MT4 = "mt4"
    MT5 = "mt5"


class FTMOAccountEnvironment(StrEnum):
    FREE_TRIAL = "free_trial"
    DEMO = "demo"
    LIVE_CAPABLE = "live_capable"


class FTMOExecutionMode(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    DEMO = "demo"
    LIVE = "live"


class FTMOIntentStatus(StrEnum):
    SHADOW_VALIDATED = "shadow_validated"
    CONFIRMATION_REQUIRED = "confirmation_required"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    RECONCILED = "reconciled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


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


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class FTMOExecutionConfiguration:
    platform: FTMOPlatform | None
    account_id: str | None
    account_environment: FTMOAccountEnvironment
    mode: FTMOExecutionMode
    execution_enabled: bool

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "FTMOExecutionConfiguration":
        raw_platform = str(environment.get("MONATISE_FTMO_PLATFORM", "")).strip().casefold()
        platform = FTMOPlatform(raw_platform) if raw_platform else None
        account_id = str(environment.get("MONATISE_FTMO_ACCOUNT_ID", "")).strip() or None
        account_environment = FTMOAccountEnvironment(
            str(environment.get("MONATISE_FTMO_ACCOUNT_ENVIRONMENT", "demo")).strip().casefold()
        )
        mode = FTMOExecutionMode(str(environment.get("MONATISE_FTMO_EXECUTION_MODE", "disabled")).strip().casefold())
        execution_enabled = str(environment.get("MONATISE_FTMO_EXECUTION_ENABLED", "false")).strip().casefold() in {
            "1", "true", "yes", "on",
        }
        if (platform is None) != (account_id is None):
            raise ValueError("FTMO platform and account ID must be configured together")
        if mode in {FTMOExecutionMode.DEMO, FTMOExecutionMode.LIVE} and not execution_enabled:
            raise ValueError("FTMO order-writing mode requires the explicit execution-enabled gate")
        if mode is FTMOExecutionMode.LIVE:
            if account_environment is not FTMOAccountEnvironment.LIVE_CAPABLE:
                raise ValueError("FTMO live mode requires a live-capable account environment")
            if str(environment.get("MONATISE_FTMO_LIVE_CONFIRMATION", "")).strip() != "I_APPROVE_FTMO_LIVE_EXECUTION":
                raise ValueError("FTMO live mode requires the exact live confirmation")
        return cls(platform, account_id, account_environment, mode, execution_enabled)

    @property
    def connected_identity_configured(self) -> bool:
        return self.platform is not None and self.account_id is not None

    @property
    def order_submission_allowed(self) -> bool:
        return self.execution_enabled and self.mode in {FTMOExecutionMode.DEMO, FTMOExecutionMode.LIVE}


@dataclass(frozen=True)
class FTMOAccount:
    account_id: str
    platform: FTMOPlatform
    environment: FTMOAccountEnvironment
    currency: str
    balance: Decimal
    equity: Decimal
    daily_start_equity: Decimal
    daily_loss_limit: Decimal
    total_loss_limit: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.account_id.strip() or not self.currency.strip():
            raise ValueError("FTMO account identity and currency are required")
        for name in ("balance", "equity", "daily_start_equity", "daily_loss_limit", "total_loss_limit"):
            object.__setattr__(self, name, _decimal(getattr(self, name), name, positive=True))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))


@dataclass(frozen=True)
class FTMOQuote:
    symbol: str
    bid: Decimal
    ask: Decimal
    timestamp: datetime
    platform: FTMOPlatform
    account_id: str
    quote_id: str
    market_open: bool = True
    source: str = "ftmo_platform"

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.account_id.strip() or not self.quote_id.strip():
            raise ValueError("FTMO quote identity is required")
        object.__setattr__(self, "bid", _decimal(self.bid, "bid", positive=True))
        object.__setattr__(self, "ask", _decimal(self.ask, "ask", positive=True))
        if self.ask < self.bid:
            raise ValueError("FTMO ask cannot be below bid")
        object.__setattr__(self, "timestamp", _aware(self.timestamp, "timestamp"))
        if self.source != "ftmo_platform":
            raise ValueError("execution quote source must be ftmo_platform")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def mid(self) -> Decimal:
        return (self.ask + self.bid) / Decimal("2")


@dataclass(frozen=True)
class FTMOSymbolSpecification:
    symbol: str
    digits: int
    tick_size: Decimal
    tick_value: Decimal
    contract_size: Decimal
    minimum_volume: Decimal
    maximum_volume: Decimal
    volume_step: Decimal
    minimum_stop_distance: Decimal
    base_currency: str
    quote_currency: str

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.base_currency.strip() or not self.quote_currency.strip():
            raise ValueError("FTMO symbol identity and currencies are required")
        if not 0 <= self.digits <= 12:
            raise ValueError("FTMO symbol digits are invalid")
        for name in (
            "tick_size", "tick_value", "contract_size", "minimum_volume",
            "maximum_volume", "volume_step",
        ):
            object.__setattr__(self, name, _decimal(getattr(self, name), name, positive=True))
        object.__setattr__(self, "minimum_stop_distance", _decimal(self.minimum_stop_distance, "minimum_stop_distance"))
        if self.minimum_stop_distance < ZERO or self.maximum_volume < self.minimum_volume:
            raise ValueError("FTMO symbol volume or stop specification is invalid")


@dataclass(frozen=True)
class FTMOPosition:
    position_id: str
    symbol: str
    side: str
    volume: Decimal
    entry_price: Decimal
    stop_loss: Decimal | None = None


@dataclass(frozen=True)
class FTMOOrder:
    order_id: str
    symbol: str
    side: str
    volume: Decimal
    status: str


class FTMOMarketAdapter(Protocol):
    async def get_account(self) -> FTMOAccount: ...
    async def get_symbol(self, symbol: str) -> FTMOSymbolSpecification: ...
    async def get_quote(self, symbol: str) -> FTMOQuote: ...
    async def get_candles(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> tuple[dict[str, Any], ...]: ...
    async def get_positions(self) -> tuple[FTMOPosition, ...]: ...
    async def get_orders(self) -> tuple[FTMOOrder, ...]: ...
    async def validate_order(self, order: Mapping[str, Any]) -> tuple[str, ...]: ...
    async def submit_order(self, order: Mapping[str, Any]) -> Any: ...
    async def modify_order(self, order_id: str, changes: Mapping[str, Any]) -> Any: ...
    async def cancel_order(self, order_id: str) -> Any: ...
    async def close_position(self, position_id: str, volume: Decimal | None = None) -> Any: ...


class UnavailableFTMOAdapter:
    """Explicit failure object used until an approved platform is connected."""

    def __init__(self, reason: str = "FTMO platform adapter is not configured") -> None:
        self.reason = reason

    def _unavailable(self) -> None:
        raise FTMOValidationError(self.reason)

    async def get_account(self) -> FTMOAccount: self._unavailable()
    async def get_symbol(self, symbol: str) -> FTMOSymbolSpecification: self._unavailable()
    async def get_quote(self, symbol: str) -> FTMOQuote: self._unavailable()
    async def get_candles(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> tuple[dict[str, Any], ...]: self._unavailable()
    async def get_positions(self) -> tuple[FTMOPosition, ...]: self._unavailable()
    async def get_orders(self) -> tuple[FTMOOrder, ...]: self._unavailable()
    async def validate_order(self, order: Mapping[str, Any]) -> tuple[str, ...]: self._unavailable()
    async def submit_order(self, order: Mapping[str, Any]) -> Any: self._unavailable()
    async def modify_order(self, order_id: str, changes: Mapping[str, Any]) -> Any: self._unavailable()
    async def cancel_order(self, order_id: str) -> Any: self._unavailable()
    async def close_position(self, position_id: str, volume: Decimal | None = None) -> Any: self._unavailable()


@dataclass(frozen=True)
class FTMORiskPolicy:
    risk_fraction: Decimal = MAX_RISK_FRACTION_PER_TRADE
    maximum_total_open_risk_fraction: Decimal = MAX_RISK_FRACTION_PER_TRADE
    daily_loss_safety_buffer_fraction: Decimal = Decimal("0.10")
    maximum_quote_age_seconds: Decimal = Decimal("5")
    maximum_spread_ticks: Decimal = Decimal("80")
    maximum_reference_deviation_fraction: Decimal = Decimal("0.0025")

    def __post_init__(self) -> None:
        for name in (
            "risk_fraction", "maximum_total_open_risk_fraction",
            "maximum_quote_age_seconds", "maximum_spread_ticks",
            "maximum_reference_deviation_fraction",
        ):
            object.__setattr__(self, name, _decimal(getattr(self, name), name, positive=True))
        object.__setattr__(
            self,
            "daily_loss_safety_buffer_fraction",
            _decimal(self.daily_loss_safety_buffer_fraction, "daily_loss_safety_buffer_fraction"),
        )
        if self.risk_fraction > MAX_RISK_FRACTION_PER_TRADE:
            raise ValueError("FTMO risk per trade idea cannot exceed 3%")
        if not ZERO <= self.daily_loss_safety_buffer_fraction < Decimal("1"):
            raise ValueError("daily loss safety buffer must be between 0 and 1")


@dataclass(frozen=True)
class FTMOAnalyticalSetup:
    signal_id: str
    symbol: str
    side: str
    analysis_price: Decimal
    analysis_stop: Decimal
    analysis_target: Decimal
    analysis_source: str
    observed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.signal_id.strip() or not self.symbol.strip() or not self.analysis_source.strip():
            raise ValueError("analytical setup identity is required")
        normalized_side = self.side.strip().casefold()
        if normalized_side not in {"long", "short"}:
            raise ValueError("analytical setup side must be long or short")
        object.__setattr__(self, "side", normalized_side)
        for name in ("analysis_price", "analysis_stop", "analysis_target"):
            object.__setattr__(self, name, _decimal(getattr(self, name), name, positive=True))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))
        if self.expires_at <= self.observed_at:
            raise ValueError("analytical setup must expire after observation")
        if self.side == "long" and not self.analysis_stop < self.analysis_price < self.analysis_target:
            raise ValueError("long analytical levels are invalid")
        if self.side == "short" and not self.analysis_target < self.analysis_price < self.analysis_stop:
            raise ValueError("short analytical levels are invalid")


@dataclass(frozen=True)
class FTMOPriceDiagnostic:
    symbol: str
    analysis_price: Decimal
    analysis_source: str
    ftmo_bid: Decimal
    ftmo_ask: Decimal
    ftmo_spread: Decimal
    quote_timestamp: datetime
    difference: Decimal
    difference_ticks: Decimal
    aligned: bool
    status: str


@dataclass(frozen=True)
class FTMOExecutionIntent:
    execution_intent_id: str
    signal_id: str
    account_id: str
    platform: FTMOPlatform
    symbol: str
    side: str
    quote_id: str
    quote_timestamp: datetime
    entry: Decimal
    stop_loss: Decimal
    targets: tuple[Decimal, ...]
    volume: Decimal
    risk_amount: Decimal
    risk_fraction: Decimal
    status: FTMOIntentStatus
    created_at: datetime
    execution_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return {key: _json_value(item) for key, item in value.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


class FTMONativePriceAuthority:
    def __init__(self, policy: FTMORiskPolicy | None = None) -> None:
        self.policy = policy or FTMORiskPolicy()

    def diagnose(self, setup: FTMOAnalyticalSetup, quote: FTMOQuote, specification: FTMOSymbolSpecification) -> FTMOPriceDiagnostic:
        self._identities(setup, quote, specification)
        difference = setup.analysis_price - quote.mid
        difference_ticks = abs(difference) / specification.tick_size
        deviation = abs(difference) / quote.mid
        aligned = deviation <= self.policy.maximum_reference_deviation_fraction
        return FTMOPriceDiagnostic(
            setup.symbol, setup.analysis_price, setup.analysis_source,
            quote.bid, quote.ask, quote.spread, quote.timestamp,
            difference, difference_ticks, aligned,
            "aligned" if aligned else "mismatch_external_reference_only",
        )

    def build_shadow_intent(
        self,
        setup: FTMOAnalyticalSetup,
        quote: FTMOQuote,
        specification: FTMOSymbolSpecification,
        account: FTMOAccount,
        *,
        existing_open_risk: Decimal = ZERO,
        now: datetime | None = None,
    ) -> FTMOExecutionIntent:
        now = _aware(now or datetime.now(timezone.utc), "now")
        diagnostic = self.diagnose(setup, quote, specification)
        if not diagnostic.aligned:
            raise FTMOValidationError("external analysis price is materially misaligned with FTMO")
        if setup.expires_at <= now:
            raise FTMOValidationError("analytical setup is expired")
        age = Decimal(str((now - quote.timestamp).total_seconds()))
        if age < ZERO or age > self.policy.maximum_quote_age_seconds:
            raise FTMOValidationError("FTMO quote is stale")
        if not quote.market_open:
            raise FTMOValidationError("FTMO market is closed")
        spread_ticks = quote.spread / specification.tick_size
        if spread_ticks > self.policy.maximum_spread_ticks:
            raise FTMOValidationError("FTMO spread exceeds policy")
        if account.account_id != quote.account_id or account.platform is not quote.platform:
            raise FTMOValidationError("FTMO account and quote identity do not match")

        external_risk_fraction = abs(setup.analysis_price - setup.analysis_stop) / setup.analysis_price
        external_reward_fraction = abs(setup.analysis_target - setup.analysis_price) / setup.analysis_price
        entry = quote.ask if setup.side == "long" else quote.bid
        if setup.side == "long":
            stop = self._ticks(entry * (Decimal("1") - external_risk_fraction), specification.tick_size, ROUND_FLOOR)
            target = self._ticks(entry * (Decimal("1") + external_reward_fraction), specification.tick_size, ROUND_FLOOR)
        else:
            stop = self._ticks(entry * (Decimal("1") + external_risk_fraction), specification.tick_size, ROUND_CEILING)
            target = self._ticks(entry * (Decimal("1") - external_reward_fraction), specification.tick_size, ROUND_CEILING)
        entry = self._ticks(entry, specification.tick_size, ROUND_HALF_UP)
        stop_distance = abs(entry - stop)
        if stop_distance < specification.minimum_stop_distance:
            raise FTMOValidationError("FTMO stop distance is below the symbol minimum")

        risk_budget = min(account.equity * self.policy.risk_fraction, risk_ceiling(account.equity))
        loss_today = max(ZERO, account.daily_start_equity - account.equity)
        daily_buffer = account.daily_loss_limit * self.policy.daily_loss_safety_buffer_fraction
        remaining_daily_capacity = account.daily_loss_limit - loss_today - daily_buffer
        if remaining_daily_capacity <= ZERO or risk_budget > remaining_daily_capacity:
            raise FTMOValidationError("FTMO daily loss capacity is insufficient")
        existing_open_risk = _decimal(existing_open_risk, "existing_open_risk")
        if existing_open_risk < ZERO:
            raise FTMOValidationError("existing open risk cannot be negative")
        if existing_open_risk + risk_budget > account.equity * self.policy.maximum_total_open_risk_fraction:
            raise FTMOValidationError("FTMO total open risk limit would be exceeded")

        stop_ticks = stop_distance / specification.tick_size
        loss_per_volume = stop_ticks * specification.tick_value
        raw_volume = risk_budget / loss_per_volume
        volume = (raw_volume / specification.volume_step).to_integral_value(rounding=ROUND_FLOOR) * specification.volume_step
        volume = min(volume, specification.maximum_volume)
        if volume < specification.minimum_volume:
            raise FTMOValidationError("calculated FTMO volume is below the symbol minimum")
        actual_risk = loss_per_volume * volume
        identity = {
            "signal_id": setup.signal_id,
            "account_id": account.account_id,
            "symbol": setup.symbol,
            "side": setup.side,
            "quote_id": quote.quote_id,
            "entry": str(entry),
            "stop": str(stop),
            "target": str(target),
            "volume": str(volume),
        }
        intent_id = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return FTMOExecutionIntent(
            intent_id, setup.signal_id, account.account_id, account.platform,
            setup.symbol, setup.side, quote.quote_id, quote.timestamp,
            entry, stop, (target,), volume, actual_risk,
            actual_risk / account.equity, FTMOIntentStatus.SHADOW_VALIDATED,
            now, False,
        )

    @staticmethod
    def _identities(setup: FTMOAnalyticalSetup, quote: FTMOQuote, specification: FTMOSymbolSpecification) -> None:
        symbols = {setup.symbol.strip().casefold(), quote.symbol.strip().casefold(), specification.symbol.strip().casefold()}
        if len(symbols) != 1:
            raise FTMOValidationError("FTMO symbol identity mismatch")

    @staticmethod
    def _ticks(value: Decimal, tick_size: Decimal, rounding: str) -> Decimal:
        return (value / tick_size).to_integral_value(rounding=rounding) * tick_size


class DurableFTMOIntentRepository:
    """Durable idempotency and reconciliation state for execution intents."""

    NAMESPACE = "ftmo_execution_intents"

    def __init__(self, store: Any) -> None:
        self.store = store
        self._lock = asyncio.Lock()

    async def claim(self, intent: FTMOExecutionIntent) -> bool:
        async with self._lock:
            if await self.store.get(self.NAMESPACE, intent.execution_intent_id) is not None:
                return False
            try:
                await self.store.put(self.NAMESPACE, intent.execution_intent_id, intent.to_dict(), expected_version=0)
            except RuntimeError:
                return False
            return True

    async def get(self, execution_intent_id: str) -> dict[str, Any] | None:
        record = await self.store.get(self.NAMESPACE, execution_intent_id)
        return dict(record.value) if record is not None else None

    async def mark_reconciliation_required(self, execution_intent_id: str, *, reason: str) -> None:
        async with self._lock:
            record = await self.store.get(self.NAMESPACE, execution_intent_id)
            if record is None:
                raise KeyError(f"unknown FTMO execution intent: {execution_intent_id}")
            value = dict(record.value)
            value.update({
                "status": FTMOIntentStatus.RECONCILIATION_REQUIRED.value,
                "reconciliation_reason": reason,
                "automatic_resend": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            await self.store.put(self.NAMESPACE, execution_intent_id, value, expected_version=record.version)


@dataclass
class FTMOExecutionTelemetry:
    connectivity: str = "unconfigured"
    last_successful_quote_at: datetime | None = None
    last_quote_age_seconds: float | None = None
    last_spread: str | None = None
    signal_count: int = 0
    rejection_count: int = 0
    last_rejection_reason: str | None = None
    shadow_intent_count: int = 0
    duplicate_intent_count: int = 0
    submitted_order_count: int = 0
    reconciliation_state: str = "not_started"
    execution_kill_switch: bool = True

    def snapshot(self) -> dict[str, Any]:
        return {
            "connectivity": self.connectivity,
            "last_successful_quote_at": self.last_successful_quote_at.isoformat() if self.last_successful_quote_at else None,
            "last_quote_age_seconds": self.last_quote_age_seconds,
            "last_spread": self.last_spread,
            "signal_count": self.signal_count,
            "rejection_count": self.rejection_count,
            "last_rejection_reason": self.last_rejection_reason,
            "shadow_intent_count": self.shadow_intent_count,
            "duplicate_intent_count": self.duplicate_intent_count,
            "submitted_order_count": self.submitted_order_count,
            "reconciliation_state": self.reconciliation_state,
            "execution_kill_switch": self.execution_kill_switch,
            "execution_enabled": False,
        }


@dataclass(frozen=True)
class FTMOShadowResult:
    diagnostic: FTMOPriceDiagnostic | None
    intent: FTMOExecutionIntent | None
    telegram_message: str
    rejection_reason: str | None
    duplicate: bool = False
    execution_enabled: bool = False


class FTMOShadowExecutionService:
    """Read-only FTMO quote conversion plus durable shadow intent creation."""

    def __init__(
        self,
        adapter: FTMOMarketAdapter,
        intents: DurableFTMOIntentRepository,
        *,
        authority: FTMONativePriceAuthority | None = None,
        telemetry: FTMOExecutionTelemetry | None = None,
    ) -> None:
        self.adapter = adapter
        self.intents = intents
        self.authority = authority or FTMONativePriceAuthority()
        self.telemetry = telemetry or FTMOExecutionTelemetry()

    async def evaluate(
        self,
        setup: FTMOAnalyticalSetup,
        *,
        existing_open_risk: Decimal = ZERO,
        now: datetime | None = None,
    ) -> FTMOShadowResult:
        observed_now = _aware(now or datetime.now(timezone.utc), "now")
        self.telemetry.signal_count += 1
        diagnostic: FTMOPriceDiagnostic | None = None
        try:
            account, specification, quote = await asyncio.gather(
                self.adapter.get_account(),
                self.adapter.get_symbol(setup.symbol),
                self.adapter.get_quote(setup.symbol),
            )
            self.telemetry.connectivity = "connected"
            self.telemetry.last_successful_quote_at = quote.timestamp
            self.telemetry.last_quote_age_seconds = max(0.0, (observed_now - quote.timestamp).total_seconds())
            self.telemetry.last_spread = str(quote.spread)
            diagnostic = self.authority.diagnose(setup, quote, specification)
            intent = self.authority.build_shadow_intent(
                setup, quote, specification, account,
                existing_open_risk=existing_open_risk,
                now=observed_now,
            )
            claimed = await self.intents.claim(intent)
            if not claimed:
                self.telemetry.duplicate_intent_count += 1
                reason = "duplicate execution intent"
                return FTMOShadowResult(
                    diagnostic, None,
                    format_ftmo_price_diagnostic(diagnostic, rejection_reason=reason),
                    reason, duplicate=True,
                )
            self.telemetry.shadow_intent_count += 1
            return FTMOShadowResult(
                diagnostic, intent,
                format_ftmo_price_diagnostic(diagnostic, proposed=intent),
                None,
            )
        except Exception as exc:
            reason = str(exc) if isinstance(exc, FTMOValidationError) else type(exc).__name__
            self.telemetry.rejection_count += 1
            self.telemetry.last_rejection_reason = reason
            if diagnostic is None:
                message = "\n".join((
                    "MONATISE / FTMO PRICE CHECK",
                    f"Instrument: {setup.symbol}",
                    f"Rejected: {reason}",
                    "Mode: SHADOW — NO ORDER SENT",
                ))
            else:
                message = format_ftmo_price_diagnostic(diagnostic, rejection_reason=reason)
            return FTMOShadowResult(diagnostic, None, message, reason)


def format_ftmo_price_diagnostic(
    diagnostic: FTMOPriceDiagnostic,
    *,
    proposed: FTMOExecutionIntent | None = None,
    rejection_reason: str | None = None,
) -> str:
    lines = [
        "MONATISE / FTMO PRICE CHECK",
        f"Instrument: {diagnostic.symbol}",
        f"Analysis price: {diagnostic.analysis_price}",
        f"Analysis price source: {diagnostic.analysis_source}",
        f"FTMO Bid: {diagnostic.ftmo_bid}",
        f"FTMO Ask: {diagnostic.ftmo_ask}",
        f"FTMO spread: {diagnostic.ftmo_spread}",
        f"FTMO quote timestamp: {diagnostic.quote_timestamp.isoformat()}",
        f"Difference from analysis price: {diagnostic.difference}",
        f"Difference in ticks/points: {diagnostic.difference_ticks}",
        f"Price-alignment status: {diagnostic.status}",
    ]
    if proposed is not None:
        lines.extend((
            f"Proposed FTMO-native entry: {proposed.entry}",
            f"Proposed stop: {proposed.stop_loss}",
            f"Proposed targets: {', '.join(map(str, proposed.targets))}",
            f"Calculated risk: {proposed.risk_amount} ({proposed.risk_fraction * 100:.4f}%)",
            f"Calculated volume: {proposed.volume}",
        ))
    if rejection_reason:
        lines.append(f"Rejected: {rejection_reason}")
    lines.append("Mode: SHADOW — NO ORDER SENT")
    return "\n".join(lines)
