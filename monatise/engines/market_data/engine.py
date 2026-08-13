from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from monatise.core.models import Candle
from monatise.core.ports import MarketDataPort
from monatise.engines.market_data.models import (
    DataQuality,
    DataStatus,
    MarketDataRequest,
    MarketSnapshot,
    utc_now,
)
from monatise.engines.market_data.provider import DerivativesDataPort


class MarketDataEngine:
    """Normalizes and validates market data before downstream analysis.

    The engine is analysis-only. It does not place, modify, or cancel orders.
    """

    def __init__(
        self,
        providers: dict[str, MarketDataPort],
        *,
        derivatives_provider: DerivativesDataPort | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not providers:
            raise ValueError("at least one market-data provider is required")
        self._providers = dict(providers)
        self._derivatives_provider = derivatives_provider
        self._clock = clock

    def collect(self, request: MarketDataRequest) -> MarketSnapshot:
        request.validate()
        observed_at = self._as_utc(self._clock())
        issues: list[str] = []
        degraded_candidate: MarketSnapshot | None = None

        ordered_sources = self._ordered_sources(request.preferred_source)
        current_price, current_source = self._collect_current_price(request.symbol, ordered_sources, issues)
        for source_name in ordered_sources:
            provider = self._providers[source_name]
            try:
                raw_candles = provider.candles(
                    request.symbol,
                    request.candle_limit,
                    request.interval,
                )
                candles = self._normalize_candles(raw_candles)
                try:
                    raw_price = provider.latest_price(request.symbol)
                except Exception as exc:
                    raw_price = candles[-1].close if candles else None
                    issues.append(
                        f"{source_name}: provider error on latest price; used latest candle close "
                        f"({type(exc).__name__})"
                    )
                reference_price = self._normalize_price(raw_price)
                price = current_price if current_price is not None else reference_price

                provider_issues = self._validate_series(candles)
                issues.extend(f"{source_name}: {item}" for item in provider_issues)

                if price is None or not candles:
                    issues.append(f"{source_name}: missing usable price or candles")
                    continue

                latest_at = self._parse_timestamp(candles[-1].timestamp)
                age_seconds = (
                    max(0.0, (observed_at - latest_at).total_seconds())
                    if latest_at is not None
                    else None
                )

                if latest_at is None:
                    issues.append(f"{source_name}: latest candle timestamp is invalid")
                elif age_seconds is not None and age_seconds > request.max_age_seconds:
                    issues.append(
                        f"{source_name}: stale data ({age_seconds:.1f}s old; "
                        f"limit {request.max_age_seconds}s)"
                    )

                derivatives, derivative_issues = self._collect_derivatives(request.symbol, request.interval)
                issues.extend(derivative_issues)

                status = self._derive_status(
                    price=price,
                    candles=candles,
                    latest_at=latest_at,
                    age_seconds=age_seconds,
                    max_age_seconds=request.max_age_seconds,
                    validation_issues=provider_issues,
                )

                snapshot = MarketSnapshot(
                    symbol=request.symbol.upper(),
                    interval=request.interval,
                    price=price,
                    candles=tuple(candles),
                    derivatives=derivatives,
                    quality=DataQuality(
                        status=status,
                        source=source_name,
                        observed_at=observed_at,
                        latest_candle_at=latest_at,
                        age_seconds=age_seconds,
                        issues=tuple(issues),
                    ),
                    metadata={
                        "requested_candle_limit": request.candle_limit,
                        "returned_candle_count": len(candles),
                        "fallback_used": source_name != ordered_sources[0],
                        "providers_attempted": ordered_sources[: ordered_sources.index(source_name) + 1],
                        "price_type": "current" if current_price is not None else "reference",
                        "price_source": current_source or source_name,
                        "price_observed_at": observed_at.isoformat(),
                    },
                )
                if status is DataStatus.READY:
                    return snapshot
                if status is DataStatus.DEGRADED and degraded_candidate is None:
                    degraded_candidate = snapshot
            except Exception as exc:  # Adapter failures must not crash the pipeline.
                issues.append(f"{source_name}: provider error: {type(exc).__name__}: {exc}")

        if degraded_candidate is not None:
            return degraded_candidate

        return MarketSnapshot(
            symbol=request.symbol.upper(),
            interval=request.interval,
            price=None,
            candles=(),
            derivatives={},
            quality=DataQuality(
                status=DataStatus.NO_DATA,
                source=None,
                observed_at=observed_at,
                latest_candle_at=None,
                age_seconds=None,
                issues=tuple(issues or ["no provider returned usable data"]),
            ),
            metadata={
                "requested_candle_limit": request.candle_limit,
                "providers_attempted": ordered_sources,
            },
        )

    def _collect_current_price(self, symbol: str, ordered_sources: list[str], issues: list[str]) -> tuple[float | None, str | None]:
        for source_name in ordered_sources:
            current_reader = getattr(self._providers[source_name], "latest_current_price", None)
            if not callable(current_reader):
                continue
            try:
                current_price = self._normalize_price(current_reader(symbol))
            except Exception as exc:
                issues.append(f"{source_name}: current price unavailable ({type(exc).__name__})")
                continue
            if current_price is not None:
                return current_price, source_name
            issues.append(f"{source_name}: current price is invalid")
        return None, None

    def _ordered_sources(self, preferred: str | None) -> list[str]:
        names = list(self._providers)
        if preferred is None:
            return names
        if preferred not in self._providers:
            raise ValueError(f"unknown preferred_source: {preferred}")
        return [preferred, *(name for name in names if name != preferred)]

    def _collect_derivatives(
        self, symbol: str, interval: str
    ) -> tuple[dict[str, float | None], list[str]]:
        if self._derivatives_provider is None:
            return {}, []
        try:
            payload = self._derivatives_provider.derivatives_snapshot(symbol, interval)
        except Exception as exc:
            return {}, [f"derivatives: provider error: {type(exc).__name__}: {exc}"]

        normalized: dict[str, float | None] = {}
        issues: list[str] = []
        for key, value in payload.items():
            if value is None:
                normalized[key] = None
                issues.append(f"derivatives: {key} unavailable")
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                normalized[key] = None
                issues.append(f"derivatives: {key} is not numeric")
                continue
            if not isfinite(number):
                normalized[key] = None
                issues.append(f"derivatives: {key} is not finite")
            else:
                normalized[key] = number
        return normalized, issues

    @staticmethod
    def _normalize_price(value: Any) -> float | None:
        try:
            price = float(value)
        except (TypeError, ValueError):
            return None
        if not isfinite(price) or price <= 0:
            return None
        return price

    @staticmethod
    def _normalize_candles(values: Iterable[Candle]) -> list[Candle]:
        candles = list(values)
        normalized: list[Candle] = []
        seen: set[str] = set()

        for candle in candles:
            candle.validate()
            numeric_values = (
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
            )
            if not all(isfinite(float(value)) for value in numeric_values):
                raise ValueError("candle contains a non-finite numeric value")
            if candle.timestamp in seen:
                continue
            seen.add(candle.timestamp)
            normalized.append(candle)

        normalized.sort(
            key=lambda item: MarketDataEngine._parse_timestamp(item.timestamp)
            or datetime.min.replace(tzinfo=timezone.utc)
        )
        return normalized

    @staticmethod
    def _validate_series(candles: list[Candle]) -> list[str]:
        issues: list[str] = []
        if len(candles) < 2:
            issues.append("fewer than two valid candles")
        if candles and candles[-1].volume < 0:
            issues.append("latest candle volume is negative")
        return issues

    @staticmethod
    def _derive_status(
        *,
        price: float | None,
        candles: list[Candle],
        latest_at: datetime | None,
        age_seconds: float | None,
        max_age_seconds: int,
        validation_issues: list[str],
    ) -> DataStatus:
        if price is None or not candles:
            return DataStatus.NO_DATA
        if latest_at is None:
            return DataStatus.DEGRADED
        if age_seconds is None or age_seconds > max_age_seconds:
            return DataStatus.DEGRADED
        if validation_issues:
            return DataStatus.DEGRADED
        return DataStatus.READY

    @staticmethod
    def _parse_timestamp(value: str) -> datetime | None:
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
