"""Capability-aware market intelligence for FTMO stocks and futures-linked CFDs.

Analytical providers are deliberately kept separate from the native MT5 quote
transport.  Nothing in this module can create an order or manufacture an FTMO
Bid/Ask from an analytical price.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from monatise.adapters.alpaca import AlpacaMarketDataAdapter
from monatise.adapters.finnhub import FinnhubAdapter
from monatise.adapters.flashalpha import FlashAlphaAdapter
from monatise.adapters.quiver import QuiverAdapter, normalize_quiver_symbol
from monatise.application.flashalpha_analysis import build_flashalpha_futures_analysis
from monatise.application.ftmo_registry import FTMOAssetClass, FTMOInstrument
from monatise.application.stock_analysis import build_stock_analysis


FAILURE_CODES = {
    "provider_unsupported", "provider_unavailable", "provider_rate_limited",
    "provider_timeout", "provider_stale", "provider_incomplete",
    "provider_conflict", "all_market_data_providers_failed",
}


def _failure_code(error: BaseException) -> str:
    detail = str(error).casefold()
    if "429" in detail or "rate" in detail and "limit" in detail:
        return "provider_rate_limited"
    if "timeout" in detail or isinstance(error, TimeoutError):
        return "provider_timeout"
    if "unsupported" in detail or "404" in detail or "403" in detail:
        return "provider_unsupported"
    return "provider_unavailable"


def _source(
    provider: str,
    role: str,
    status: str,
    symbol: str | None,
    *,
    requested: bool = True,
    evidence: list[str] | None = None,
    affected_score: bool = False,
    failure_reason: str | None = None,
    timeframes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "role": role,
        "requested": requested,
        "status": status,
        "provider_symbol": symbol,
        "timeframes": dict(timeframes or {}),
        "failure_reason": failure_reason,
        "evidence_contributed": list(evidence or []),
        "affected_score": affected_score,
    }


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def validate_candles(
    rows: Any,
    *,
    provider: str,
    symbol: str,
    timeframe: str,
    now: datetime,
    minimum_count: int = 22,
    maximum_age: timedelta = timedelta(days=4),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate and normalize one analytical candle series or fail closed."""
    if not isinstance(rows, list) or len(rows) < minimum_count:
        raise ValueError("provider_incomplete: insufficient candle count")
    clean: list[dict[str, Any]] = []
    timestamps: list[datetime] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("provider_incomplete: malformed candle")
        timestamp = _parse_time(row.get("t"))
        try:
            values = {key: float(row[key]) for key in ("o", "h", "l", "c")}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("provider_incomplete: malformed OHLC") from exc
        if timestamp is None or not all(math.isfinite(value) and value > 0 for value in values.values()):
            raise ValueError("provider_incomplete: malformed candle values")
        if values["l"] > min(values["o"], values["c"]) or values["h"] < max(values["o"], values["c"]) or values["l"] > values["h"]:
            raise ValueError("provider_incomplete: impossible OHLC relationship")
        timestamps.append(timestamp)
        clean.append({"t": timestamp.isoformat(), **values})
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("provider_incomplete: unordered or duplicate candles")
    latest = timestamps[-1]
    if latest > now:
        raise ValueError("provider_incomplete: future candle timestamp")
    age = now - latest
    if age > maximum_age:
        raise ValueError("provider_stale: latest candle is stale")
    expected_seconds = {"15m": 900, "1h": 3_600, "1d": 86_400}.get(timeframe.casefold())
    gaps = sum(
        1 for left, right in zip(timestamps, timestamps[1:])
        if expected_seconds is not None and (right - left).total_seconds() > expected_seconds * 3
    )
    return clean, {
        "provider": provider,
        "provider_symbol": symbol,
        "timeframe": timeframe,
        "candle_count": len(clean),
        "latest_candle_timestamp": latest.isoformat(),
        "freshness_seconds": int(age.total_seconds()),
        "duplicate_count": 0,
        "large_gap_count": gaps,
        "quality": "valid",
    }


def validate_flashalpha_context(
    context: Any,
    *,
    provider_symbol: str,
    now: datetime,
    maximum_age: timedelta,
) -> datetime:
    if not isinstance(context, dict) or str(context.get("symbol") or "").upper() != provider_symbol.upper():
        raise ValueError("provider_incomplete: futures symbol identity mismatch")
    as_of = _parse_time(context.get("as_of"))
    if as_of is None:
        raise ValueError("provider_incomplete: missing provider timestamp")
    if as_of > now:
        raise ValueError("provider_incomplete: future provider timestamp")
    if now - as_of > maximum_age:
        raise ValueError("provider_stale: futures intelligence is stale")
    for key in ("underlying_price", "gamma_flip"):
        value = context.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError(f"provider_incomplete: invalid {key}")
    return as_of


async def _optional_call(call: Any) -> tuple[Any | None, str | None]:
    try:
        return await asyncio.to_thread(call), None
    except Exception as error:  # provider adapters expose sanitized error types
        return None, _failure_code(error)


def _insufficient(
    symbol: str,
    asset_class: str,
    sources: list[dict[str, Any]],
    reason: str,
    *,
    now: datetime,
) -> dict[str, Any]:
    return {
        "asset": symbol,
        "asset_class": asset_class,
        "decision": "INSUFFICIENT_MARKET_DATA",
        "direction": "NONE",
        "score": 0,
        "score_threshold": 7,
        "setup_status": "insufficient_market_data",
        "reason_code": reason,
        "reasons": [reason],
        "analysis_sources": sources,
        "provider_consensus": "INSUFFICIENT",
        "fallback_status": "no_verified_fallback",
        "ftmo_execution_quote": {"provider": "ftmo_mt5", "status": "not_requested", "reason": "analysis_not_qualified"},
        "generated_at": now.isoformat(),
        "execution": {"enabled": False, "orders_placed": 0},
    }


class StockMarketIntelligenceCoordinator:
    """Coordinate verified stock providers without inventing a candle fallback."""

    def __init__(
        self,
        alpaca: AlpacaMarketDataAdapter,
        quiver: QuiverAdapter,
        finnhub: FinnhubAdapter,
        flashalpha: FlashAlphaAdapter,
        *,
        environment: Mapping[str, str],
    ) -> None:
        self.alpaca = alpaca
        self.quiver = quiver
        self.finnhub = finnhub
        self.flashalpha = flashalpha
        self.environment = environment

    async def analyse(
        self,
        symbol: str,
        *,
        instrument: FTMOInstrument | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        ticker = str(symbol).upper().strip()
        sources: list[dict[str, Any]] = []
        if instrument is not None and (
            instrument.asset_class is not FTMOAssetClass.STOCK
            or instrument.market_data_provider != "alpaca"
        ):
            sources.extend([
                _source("alpaca", "required_market_data", "not_applicable", ticker, requested=False, failure_reason="provider_unsupported"),
                _source("quiver", "directional_intelligence", "not_requested", ticker, requested=False),
                _source("finnhub", "supplemental_intelligence", "not_requested", ticker, requested=False),
                _source("flashalpha", "confirmation", "not_requested", ticker, requested=False),
                _source("ftmo_mt5", "execution_pricing", "not_requested", instrument.ftmo_symbol, requested=False, failure_reason="analysis_not_qualified"),
            ])
            result = _insufficient(ticker, "stock", sources, "provider_unsupported", now=observed)
            result.update({"analysis_provider": "none", "analysis_instrument": ticker})
            return result

        hourly_result, trigger_result, snapshot_result, quiver_result, finnhub_result, flashalpha_result = await asyncio.gather(
            _optional_call(lambda: self.alpaca.stock_bars(ticker, "1Hour", 240)),
            _optional_call(lambda: self.alpaca.stock_bars(ticker, "15Min", 240)),
            _optional_call(lambda: self.alpaca.stock_snapshot(ticker)),
            _optional_call(lambda: self.quiver.context(normalize_quiver_symbol(ticker))),
            _optional_call(lambda: self.finnhub.context(ticker)),
            _optional_call(lambda: self.flashalpha.context(normalize_quiver_symbol(ticker))),
        )
        hourly, hourly_error = hourly_result
        trigger, trigger_error = trigger_result
        snapshot, snapshot_error = snapshot_result

        quality: dict[str, Any] = {}
        market_failure = hourly_error or trigger_error or snapshot_error
        if market_failure is None:
            try:
                hourly, quality["1h"] = validate_candles(
                    hourly, provider="alpaca", symbol=ticker, timeframe="1h", now=observed,
                    maximum_age=timedelta(days=4),
                )
                trigger, quality["15m"] = validate_candles(
                    trigger, provider="alpaca", symbol=ticker, timeframe="15m", now=observed,
                    maximum_age=timedelta(days=4),
                )
                if not isinstance(snapshot, dict):
                    raise ValueError("provider_incomplete: malformed snapshot")
            except ValueError as error:
                detail = str(error)
                market_failure = "provider_stale" if detail.startswith("provider_stale") else "provider_incomplete"
        sources.append(_source(
            "alpaca", "required_market_data", "used" if market_failure is None else "failed", ticker,
            evidence=["1h OHLC", "15m OHLC", "stock snapshot"] if market_failure is None else [],
            failure_reason=market_failure, timeframes=quality,
        ))

        quiver, quiver_error = quiver_result
        quiver_available = isinstance(quiver, dict) and bool(quiver.get("available"))
        sources.append(_source(
            "quiver", "directional_intelligence", "used" if quiver_available else "degraded", ticker,
            evidence=["Congress activity", "insider activity", "alternative-data context"] if quiver_available else [],
            affected_score=quiver_available,
            failure_reason=quiver_error or ("provider_incomplete" if not quiver_available else None),
        ))

        finnhub, finnhub_error = finnhub_result
        finnhub_available = isinstance(finnhub, dict) and not finnhub.get("unavailable")
        sources.append(_source(
            "finnhub", "supplemental_intelligence", "used" if finnhub_available else "degraded", ticker,
            evidence=["company quote", "news", "recommendations", "earnings calendar"] if finnhub_available else [],
            affected_score=False, failure_reason=finnhub_error,
        ))

        flashalpha, flashalpha_error = flashalpha_result
        flashalpha_available = isinstance(flashalpha, dict) and flashalpha.get("net_gex") is not None
        sources.append(_source(
            "flashalpha", "confirmation", "used" if flashalpha_available else "degraded", ticker,
            evidence=["options gamma exposure", "gamma flip", "call/put walls"] if flashalpha_available else [],
            affected_score=flashalpha_available, failure_reason=flashalpha_error,
        ))
        ftmo_source = _source("ftmo_mt5", "execution_pricing", "not_requested", instrument.ftmo_symbol if instrument else ticker, requested=False, failure_reason="analysis_not_qualified")
        sources.append(ftmo_source)

        if market_failure is not None:
            result = _insufficient(ticker, "stock", sources, market_failure, now=observed)
            result.update({
                "analysis_provider": "alpaca", "analysis_instrument": ticker,
                "data_quality": quality,
                "supplemental_intelligence": {"quiver": quiver or {}, "finnhub": finnhub or {}, "flashalpha": flashalpha or {}},
            })
            return result

        validity_minutes = max(15, int(self.environment.get("MONATISE_STOCK_15M_VALIDITY_MINUTES", "60")))
        analysis = build_stock_analysis(
            quiver or {"symbol": ticker, "available": False, "summary": {}},
            bars=hourly, trigger_bars=trigger, snapshot=snapshot or {},
            finnhub=finnhub or {"source": "Finnhub", "unavailable": True},
            flashalpha=flashalpha or {"source": "FlashAlpha", "unavailable": True},
            now=observed, validity_minutes=validity_minutes,
        )
        if analysis.get("reason_code") == "FLASHALPHA_POSITIONING_CONFLICT":
            consensus = "CONFLICT"
        elif not quiver_available:
            consensus = "INSUFFICIENT"
        elif flashalpha_available:
            consensus = "CONFIRMED"
        else:
            consensus = "PARTIAL"
        analysis.update({
            "analysis_provider": "alpaca+quiver",
            "analysis_instrument": ticker,
            "analysis_sources": sources,
            "provider_consensus": consensus,
            "fallback_status": "not_available_no_verified_fallback",
            "data_quality": quality,
            "supplemental_intelligence": {"quiver": quiver or {}, "finnhub": finnhub or {}, "flashalpha": flashalpha or {}},
            "ftmo_execution_quote": {"provider": "ftmo_mt5", "status": "not_requested", "reason": "awaiting_qualification" if analysis.get("setup_status") == "confirmed" else "analysis_not_qualified"},
        })
        return analysis


class FuturesMarketIntelligenceCoordinator:
    """Coordinate FlashAlpha's verified options-on-futures intelligence."""

    def __init__(self, flashalpha: FlashAlphaAdapter, *, environment: Mapping[str, str]) -> None:
        self.flashalpha = flashalpha
        self.environment = environment

    async def analyse(
        self,
        instrument: FTMOInstrument,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if instrument.asset_class is not FTMOAssetClass.FUTURES_LINKED or not instrument.futures_symbol:
            raise ValueError("instrument is not a verified futures-linked FTMO CFD")
        provider_symbol = f"{instrument.futures_symbol}=F"
        context, error = await _optional_call(lambda: self.flashalpha.context(provider_symbol))
        reason = error
        as_of = None
        if reason is None:
            try:
                as_of = validate_flashalpha_context(
                    context, provider_symbol=provider_symbol, now=observed,
                    maximum_age=timedelta(minutes=max(5, int(self.environment.get("MONATISE_FLASHALPHA_MAX_AGE_MINUTES", "60")))),
                )
            except ValueError as validation_error:
                reason = "provider_stale" if str(validation_error).startswith("provider_stale") else "provider_incomplete"

        sources = [
            _source("alpaca", "market_data", "not_applicable", None, requested=False, failure_reason="provider_unsupported"),
            _source("quiver", "supplemental_intelligence", "not_applicable", None, requested=False, failure_reason="provider_unsupported"),
            _source("finnhub", "supplemental_intelligence", "not_applicable", None, requested=False, failure_reason="provider_unsupported"),
            _source(
                "flashalpha", "specialist_futures_intelligence", "used" if reason is None else "failed", provider_symbol,
                evidence=["options-on-futures gamma exposure", "gamma flip", "call/put walls"] if reason is None else [],
                affected_score=reason is None, failure_reason=reason,
                timeframes={"snapshot": {"latest_timestamp": as_of.isoformat() if as_of else None, "quality": "valid" if reason is None else "rejected"}},
            ),
            _source("ftmo_mt5", "execution_pricing", "not_requested", instrument.ftmo_symbol, requested=False, failure_reason="analysis_not_qualified"),
        ]
        if reason is not None:
            result = _insufficient(instrument.ftmo_symbol, FTMOAssetClass.FUTURES_LINKED.value, sources, reason, now=observed)
            result.update({
                "ftmo_symbol": instrument.ftmo_symbol,
                "underlying_market": instrument.underlying_market,
                "futures_symbol": instrument.futures_symbol,
                "micro_futures_symbol": instrument.micro_futures_symbol,
                "analysis_provider": "flashalpha",
                "analysis_instrument": provider_symbol,
            })
            return result

        analysis = build_flashalpha_futures_analysis(context)
        validity_minutes = max(5, int(self.environment.get("MONATISE_FUTURES_ON_DEMAND_VALIDITY_MINUTES", "15")))
        analysis.update({
            "ftmo_symbol": instrument.ftmo_symbol,
            "underlying_market": instrument.underlying_market,
            "futures_symbol": instrument.futures_symbol,
            "micro_futures_symbol": instrument.micro_futures_symbol,
            "asset_class": FTMOAssetClass.FUTURES_LINKED.value,
            "analysis_provider": "flashalpha",
            "analysis_instrument": provider_symbol,
            "analysis_exchange": instrument.exchange,
            "timeframe": "intraday options-positioning snapshot",
            "generated_at": observed.isoformat(),
            "expires_at": (observed + timedelta(minutes=validity_minutes)).isoformat(),
            "freshness": "fresh",
            "publication_valid": True,
            "analysis_sources": sources,
            "provider_consensus": "PARTIAL",
            "fallback_status": "not_available_no_verified_fallback",
            "data_quality": {"flashalpha_snapshot": {"latest_timestamp": as_of.isoformat(), "quality": "valid"}},
            "ftmo_execution_quote": {"provider": "ftmo_mt5", "status": "not_requested", "reason": "awaiting_qualification" if analysis.get("setup_status") == "confirmed" else "analysis_not_qualified"},
        })
        return analysis
