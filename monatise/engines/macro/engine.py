from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite

from monatise.engines.macro.models import (
    MacroAssessment,
    MacroBias,
    MacroEvent,
    MacroEventImpact,
    MacroRequest,
    MacroRiskState,
)
from monatise.engines.macro.provider import MacroDataPort
from monatise.engines.macro.rules import CRYPTO_MACRO_RULES, MacroRule


class MacroEngine:
    """Crypto-only macro qualification engine.

    The engine may qualify or block analysis. It must not create entries,
    grids, stops, targets, orders, or trade-execution instructions.
    """

    def __init__(
        self,
        provider: MacroDataPort,
        *,
        rules: tuple[MacroRule, ...] = CRYPTO_MACRO_RULES,
    ) -> None:
        if not rules:
            raise ValueError("at least one macro rule is required")
        self._provider = provider
        self._rules = tuple(rules)

    def assess(self, request: MacroRequest) -> MacroAssessment:
        request.validate()
        observed_at = self._as_utc(request.observed_at)
        reasons: list[str] = []

        if not self._is_crypto_symbol(request.symbol):
            return MacroAssessment(
                symbol=request.symbol.upper(),
                bias=MacroBias.UNKNOWN,
                risk_state=MacroRiskState.DATA_UNAVAILABLE,
                conviction=0.0,
                score=0.0,
                reasons=("unsupported symbol: crypto assets only",),
                metadata={"engine_scope": "crypto_only"},
            )

        try:
            raw_factors = self._provider.context_snapshot(request.symbol)
        except Exception as exc:
            return MacroAssessment(
                symbol=request.symbol.upper(),
                bias=MacroBias.UNKNOWN,
                risk_state=MacroRiskState.DATA_UNAVAILABLE,
                conviction=0.0,
                score=0.0,
                reasons=(f"macro provider error: {type(exc).__name__}: {exc}",),
                metadata={"engine_scope": "crypto_only"},
            )

        factors = self._normalize_factors(raw_factors, reasons)

        try:
            events = self._provider.economic_events()
            calendar_available = True
        except Exception as exc:
            calendar_available = False
            if not request.allow_partial_context:
                return MacroAssessment(
                    symbol=request.symbol.upper(),
                    bias=MacroBias.UNKNOWN,
                    risk_state=MacroRiskState.DATA_UNAVAILABLE,
                    conviction=0.0,
                    score=0.0,
                    reasons=(f"economic calendar unavailable: {type(exc).__name__}: {exc}",),
                    factors=factors,
                    metadata={"engine_scope": "crypto_only"},
                )
            events = []
            reasons.append(
                f"economic calendar unavailable: {type(exc).__name__}: {exc}"
            )

        relevant_events = self._relevant_events(
            events,
            request.include_currencies,
        )
        active_events, upcoming_events = self._classify_events(
            relevant_events,
            observed_at,
            request.event_lock_before_minutes,
            request.event_lock_after_minutes,
        )

        if active_events:
            reasons.append("new crypto analysis locked around high-impact macro event")

        score, used_count = self._score(factors, self._rules)
        bias = self._bias_from_score(score, used_count)
        conviction = self._conviction(score, used_count, len(self._rules))

        if used_count == 0:
            reasons.append("no usable crypto macro factors")
        else:
            reasons.append(
                f"{used_count} crypto macro factor(s) contributed to the assessment"
            )

        if factors.get("btc_dominance_change_pct") is not None:
            reasons.append(
                self._btc_dominance_reason(
                    request.symbol,
                    factors["btc_dominance_change_pct"],
                )
            )

        risk_state = self._risk_state(
            active_events=active_events,
            used_count=used_count,
            calendar_available=calendar_available,
        )

        return MacroAssessment(
            symbol=request.symbol.upper(),
            bias=bias,
            risk_state=risk_state,
            conviction=conviction,
            score=score,
            reasons=tuple(reasons),
            active_events=tuple(active_events),
            upcoming_events=tuple(upcoming_events),
            factors=factors,
            metadata={
                "engine_scope": "crypto_only",
                "rules_considered": len(self._rules),
                "factors_used": used_count,
                "event_lock_before_minutes": request.event_lock_before_minutes,
                "event_lock_after_minutes": request.event_lock_after_minutes,
            },
        )

    @staticmethod
    def _normalize_factors(
        raw: dict[str, float | None],
        reasons: list[str],
    ) -> dict[str, float | None]:
        normalized: dict[str, float | None] = {}
        for key, value in raw.items():
            if value is None:
                normalized[key] = None
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                normalized[key] = None
                reasons.append(f"{key} is not numeric")
                continue
            if not isfinite(number):
                normalized[key] = None
                reasons.append(f"{key} is not finite")
            else:
                normalized[key] = number
        return normalized

    @staticmethod
    def _score(
        factors: dict[str, float | None],
        rules: tuple[MacroRule, ...],
    ) -> tuple[float, int]:
        total = 0.0
        used = 0
        used_weight = 0.0

        for rule in rules:
            contribution = rule.contribution(factors.get(rule.factor))
            if contribution is None:
                continue
            total += contribution
            used += 1
            used_weight += abs(rule.weight)

        if used_weight == 0:
            return 0.0, 0

        normalized = max(-1.0, min(1.0, total / used_weight))
        return normalized, used

    @staticmethod
    def _bias_from_score(score: float, used_count: int) -> MacroBias:
        if used_count == 0:
            return MacroBias.UNKNOWN
        if score >= 0.25:
            return MacroBias.BULLISH
        if score <= -0.25:
            return MacroBias.BEARISH
        if abs(score) <= 0.10:
            return MacroBias.NEUTRAL
        return MacroBias.CONFLICTED

    @staticmethod
    def _conviction(score: float, used: int, total_rules: int) -> float:
        if used == 0 or total_rules == 0:
            return 0.0
        coverage = min(1.0, used / total_rules)
        return round(min(1.0, abs(score) * 0.75 + coverage * 0.25), 4)

    @staticmethod
    def _is_crypto_symbol(symbol: str) -> bool:
        normalized = symbol.upper().replace("/", "").replace("-", "").replace("_", "")
        base_assets = {
            "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX",
            "LINK", "DOT", "LTC", "BCH", "SUI", "APT", "ARB", "OP",
            "PEPE", "WIF", "BONK", "TRX", "TON", "NEAR", "ATOM",
        }
        if normalized in base_assets:
            return True
        for quote in ("USDT", "USDC", "BTC", "ETH"):
            if normalized.endswith(quote) and len(normalized) > len(quote):
                return True
        if normalized.endswith("USD"):
            return normalized[:-3] in base_assets
        return False

    @staticmethod
    def _relevant_events(
        events: list[MacroEvent],
        currencies: tuple[str, ...],
    ) -> list[MacroEvent]:
        selected = [
            event
            for event in events
            if event.impact in {
                MacroEventImpact.HIGH,
                MacroEventImpact.CRITICAL,
            }
        ]
        if not currencies:
            return selected
        allowed = {currency.upper() for currency in currencies}
        return [
            event
            for event in selected
            if event.currency is None or event.currency.upper() in allowed
        ]

    @staticmethod
    def _classify_events(
        events: list[MacroEvent],
        observed_at: datetime,
        before_minutes: int,
        after_minutes: int,
    ) -> tuple[list[MacroEvent], list[MacroEvent]]:
        active: list[MacroEvent] = []
        upcoming: list[MacroEvent] = []
        before = timedelta(minutes=before_minutes)
        after = timedelta(minutes=after_minutes)

        for event in events:
            scheduled_at = MacroEngine._as_utc(event.scheduled_at)
            if scheduled_at - before <= observed_at <= scheduled_at + after:
                active.append(event)
            elif observed_at < scheduled_at:
                upcoming.append(event)

        active.sort(key=lambda event: event.scheduled_at)
        upcoming.sort(key=lambda event: event.scheduled_at)
        return active, upcoming

    @staticmethod
    def _risk_state(
        *,
        active_events: list[MacroEvent],
        used_count: int,
        calendar_available: bool,
    ) -> MacroRiskState:
        if active_events:
            return MacroRiskState.EVENT_LOCK
        if used_count == 0 and not calendar_available:
            return MacroRiskState.DATA_UNAVAILABLE
        if used_count == 0 or not calendar_available:
            return MacroRiskState.ELEVATED
        return MacroRiskState.NORMAL

    @staticmethod
    def _btc_dominance_reason(symbol: str, change: float) -> str:
        normalized = symbol.upper().replace("/", "").replace("-", "").replace("_", "")
        is_bitcoin = normalized.startswith("BTC")
        if abs(change) <= 0.10:
            return "BTC dominance is broadly stable"
        if change > 0:
            return (
                "rising BTC dominance supports Bitcoin relative strength"
                if is_bitcoin
                else "rising BTC dominance may pressure altcoin relative performance"
            )
        return (
            "falling BTC dominance may reduce Bitcoin relative strength"
            if is_bitcoin
            else "falling BTC dominance may support altcoin relative performance"
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
