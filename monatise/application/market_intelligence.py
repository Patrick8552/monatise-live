"""Capability-aware market intelligence for FTMO stocks and futures-linked CFDs.

Analytical providers are deliberately kept separate from the native MT5 quote
transport.  Nothing in this module can create an order or manufacture an FTMO
Bid/Ask from an analytical price.
"""

from __future__ import annotations

from monatise.application.take_profit import MultiTPConfiguration, route_for
from monatise.application.target_evidence import apply_flashalpha_plan

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from monatise.adapters.flashalpha import FlashAlphaAdapter
from monatise.adapters.quiver import normalize_quiver_symbol
from monatise.application.flashalpha_analysis import build_flashalpha_futures_analysis
from monatise.application.ftmo_registry import FTMOAssetClass, FTMOInstrument, FTMO_REGISTRY
from monatise.application.hierarchy.assets import AssetHierarchyAnalysis
from monatise.application.hierarchy.broker_candles import is_index
from monatise.application.hierarchy.policy import SHARED_TIMEFRAME_POLICY as POLICY
from monatise.application.provider_evidence import EvidenceValidationError, FEEDS, flashalpha_diagnostics, gamma_status


FAILURE_CODES = {
    "provider_unsupported", "provider_unavailable", "provider_rate_limited",
    "provider_timeout", "provider_stale", "provider_incomplete",
    "provider_conflict", "all_market_data_providers_failed",
}


def _failure_code(error: BaseException) -> str:
    if getattr(error, "status_code", None) == 429 or getattr(error, "code", None) == "rate_limited":
        return "provider_rate_limited"
    if getattr(error, "status_code", None) in {403, 404}:
        return "provider_unsupported"
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
    def reject(message, field, issue, endpoint="context"):
        raise EvidenceValidationError(message, field=field, issue=issue, endpoint=endpoint)

    if not isinstance(context, dict) or str(context.get("symbol") or "").upper() != provider_symbol.upper():
        reject("provider_incomplete: futures symbol identity mismatch", "symbol", "identity_mismatch")
    as_of = _parse_time(context.get("as_of"))
    if as_of is None:
        reject("provider_incomplete: missing provider timestamp", "as_of", "missing_or_malformed")
    if as_of > now:
        reject("provider_incomplete: future provider timestamp", "as_of", "future")
    if now - as_of > maximum_age:
        reject("provider_stale: futures intelligence is stale", "as_of", "stale")
    # A newly generated response must not disguise an old source feed or a
    # stale/mismatched second endpoint. Legacy normalized replay data retains
    # its existing snapshot validation when endpoint metadata is absent.
    for endpoint, raw in (context.get("provider_evidence") or {}).items():
        if endpoint not in {"gex", "levels"}:
            continue
        if not isinstance(raw, dict):
            reject(f"provider_incomplete: flashalpha {endpoint} malformed evidence", "response", "malformed", endpoint)
        if str(raw.get("symbol") or "").upper() != provider_symbol.upper():
            reject(f"provider_incomplete: flashalpha {endpoint} symbol identity mismatch", "symbol", "identity_mismatch", endpoint)
        clocks = {"as_of": raw.get("as_of")}
        feeds = raw.get("data_as_of")
        if "data_as_of" in raw and not isinstance(feeds, dict):
            reject(f"provider_incomplete: flashalpha {endpoint} invalid data_as_of", "data_as_of", "malformed", endpoint)
        relevant_feeds = FEEDS[4:] if provider_symbol.endswith("=F") else FEEDS[:2]
        clocks.update({f"data_as_of.{key}": feeds.get(key) for key in relevant_feeds if isinstance(feeds, dict)})
        for field, value in clocks.items():
            parsed = _parse_time(value)
            if parsed is None or parsed > now:
                reject(f"provider_incomplete: flashalpha {endpoint} invalid {field}", field, "future" if parsed else "missing_or_malformed", endpoint)
            if now - parsed > maximum_age:
                reject(f"provider_stale: flashalpha {endpoint} stale {field}", field, "stale", endpoint)
        # GEX and levels can be served by different snapshots. A certified
        # levels response cannot hide a failed certificate in the GEX response.
        if "gamma_flip_status" in raw and raw["gamma_flip_status"] != "available":
            status = gamma_status(raw["gamma_flip_status"])
            reject(f"provider_incomplete: flashalpha {endpoint} gamma_flip unavailable ({status})", "gamma_flip", status, endpoint)
    if "gamma_flip_status" in context and context["gamma_flip_status"] != "available":
        status = gamma_status(context["gamma_flip_status"])
        reject(f"provider_incomplete: flashalpha gamma_flip unavailable ({status})", "gamma_flip", status, "levels")
    for key in ("underlying_price", "gamma_flip", "call_wall", "put_wall"):
        value = context.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
            reject(f"provider_incomplete: invalid {key}", key, "invalid_number")
    net_gex = context.get("net_gex")
    if not isinstance(net_gex, (int, float)) or isinstance(net_gex, bool) or not math.isfinite(float(net_gex)):
        reject("provider_incomplete: invalid net_gex", "net_gex", "invalid_number")
    if not context["put_wall"] <= context["underlying_price"] <= context["call_wall"]:
        reject("provider_conflict: flashalpha walls do not bracket underlying price", "walls", "price_relationship")
    return as_of


async def _optional_call(call: Any) -> tuple[Any | None, str | None]:
    try:
        return await asyncio.to_thread(call), None
    except Exception as error:  # provider adapters expose sanitized error types
        return None, _failure_code(error)


async def _flashalpha_call(adapter, symbol):
    try:
        return await asyncio.to_thread(adapter.context, symbol), None, None
    except Exception as error:
        return None, _failure_code(error), flashalpha_diagnostics(error=error)


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
    """Use crypto's candle hierarchy; retain verified provider context gates."""

    def __init__(self, alpaca, quiver, finnhub, flashalpha, *, environment, hierarchy=None):
        self.alpaca, self.quiver, self.finnhub, self.flashalpha = alpaca, quiver, finnhub, flashalpha
        self.environment = environment
        self.hierarchy = hierarchy or AssetHierarchyAnalysis(alpaca=alpaca, environment=environment)

    async def analyse(self, symbol, *, instrument=None, now=None, enrichment_index=None):
        observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if instrument is None:
            matches = [item for item in FTMO_REGISTRY.for_asset_class(FTMOAssetClass.STOCK)
                       if str(symbol).upper() in {item.ftmo_symbol.upper(), item.underlying_symbol.upper(), str(item.provider_symbol).upper()}]
            instrument = matches[0] if len(matches) == 1 else None
        ticker = str(symbol).upper().strip()
        if instrument is None or instrument.asset_class is not FTMOAssetClass.STOCK or instrument.market_data_provider != "flashalpha":
            return {**_insufficient(ticker, "stock", [], "provider_unsupported", now=observed), **POLICY.metadata()}
        flash, quiver, finnhub = await asyncio.gather(
            _flashalpha_call(self.flashalpha, ticker),
            _optional_call(lambda: self.quiver.context(normalize_quiver_symbol(ticker)))
            if enrichment_index is None or enrichment_index < max(0, int(self.environment.get("MONATISE_STOCK_QUIVER_CAP_PER_CYCLE", "6")))
            else asyncio.sleep(0, result=(None, "cycle_quota_reserved")),
            _optional_call(lambda: self.finnhub.context(ticker))
            if enrichment_index is None or enrichment_index < max(0, int(self.environment.get("MONATISE_STOCK_FINNHUB_CAP_PER_CYCLE", "6")))
            else asyncio.sleep(0, result=(None, "cycle_quota_reserved")),
        )
        context, error, diagnostics = flash
        error_detail = None
        # Providers can stamp a response while the request is in flight. Compare
        # against receipt time, never the earlier request-start time. An explicit
        # clock remains fixed for deterministic replay and future-data rejection.
        observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if error is None:
            try:
                validate_flashalpha_context(context, provider_symbol=ticker, now=observed,
                    maximum_age=timedelta(minutes=max(5, int(self.environment.get("MONATISE_FLASHALPHA_MAX_AGE_MINUTES", "60")))))
            except ValueError as exc:
                error = str(exc).split(":", 1)[0]
                error_detail = str(exc)  # Fixed validation messages, never a provider exception.
                diagnostics = flashalpha_diagnostics(context, exc)
        diagnostics = diagnostics or flashalpha_diagnostics(context)
        sources = [
            _source("flashalpha", "positioning_context", "failed" if error else "used", ticker,
                    evidence=[] if error else ["verified positioning context at shared analysis layer"], failure_reason=error_detail or error),
            _source("quiver", "supplemental_intelligence", "used" if quiver[0] and quiver[0].get("available") else "degraded", ticker, failure_reason=quiver[1]),
            _source("finnhub", "supplemental_intelligence", "used" if finnhub[0] and not finnhub[0].get("unavailable") else "degraded", ticker, failure_reason=finnhub[1]),
            _source("ftmo_mt5", "execution_pricing", "not_requested", instrument.ftmo_symbol, requested=False),
        ]
        if error:
            await self.hierarchy.invalidate(instrument)
            return {**_insufficient(ticker, "stock", sources, error, now=observed), "reason_detail": error_detail, "provider_diagnostics": diagnostics, **POLICY.metadata(), "analysis_provider": "alpaca", "analysis_instrument": ticker}
        quiver_score = int((((quiver[0] or {}).get("summary") or {}).get("score") or 0))
        result = await self.hierarchy.analyse(instrument, context={**context, "quiver_score": quiver_score}, now=now)
        result["analysis_sources"] += sources
        result["provider_diagnostics"] = diagnostics
        result["supplemental_intelligence"] = result["additional_context"] = {
            "flashalpha": context, "quiver": quiver[0] or {}, "finnhub": finnhub[0] or {},
        }
        result["direction_authority"] = "Monatise shared H1 market structure"
        result["provider_consensus"] = "PARTIAL"
        result["fallback_status"] = "no_snapshot_only_fallback"
        if result.get("setup_status") == "confirmed":
            from monatise.application.flashalpha_analysis import flashalpha_directional_bias
            bias = flashalpha_directional_bias(context)
            direction = result["direction"]
            score = int((((quiver[0] or {}).get("summary") or {}).get("score") or 0))
            conflict = ((direction == "LONG" and (bias == "bearish" or score <= -2))
                        or (direction == "SHORT" and (bias == "bullish" or score >= 2)))
            result["provider_consensus"] = "CONFLICT" if conflict else "CONFIRMED"
            if conflict:
                result.update(decision="NO_TRADE", setup_status="provider_conflict", publication_valid=False)
                result["reasons"].append("positioning_context_conflicts_with_shared_hierarchy")
                await self.hierarchy.invalidate(instrument)
        return result


class FuturesMarketIntelligenceCoordinator:
    """Coordinate shared index candles and other futures positioning analysis."""

    def __init__(self, flashalpha: FlashAlphaAdapter, *, environment: Mapping[str, str], hierarchy: AssetHierarchyAnalysis | None = None) -> None:
        self.flashalpha = flashalpha
        self.environment = environment
        self.hierarchy = hierarchy or AssetHierarchyAnalysis(environment=environment)

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
        context, error, diagnostics = await _flashalpha_call(self.flashalpha, provider_symbol)
        observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        reason = error
        reason_detail = None
        as_of = None
        if reason is None:
            try:
                as_of = validate_flashalpha_context(
                    context, provider_symbol=provider_symbol, now=observed,
                    maximum_age=timedelta(minutes=max(5, int(self.environment.get("MONATISE_FLASHALPHA_MAX_AGE_MINUTES", "60")))),
                )
            except ValueError as validation_error:
                reason = "provider_stale" if str(validation_error).startswith("provider_stale") else "provider_incomplete"
                reason_detail = str(validation_error)
                diagnostics = flashalpha_diagnostics(context, validation_error)
        diagnostics = diagnostics or flashalpha_diagnostics(context)

        sources = [
            _source("alpaca", "market_data", "not_applicable", None, requested=False, failure_reason="provider_unsupported"),
            _source("quiver", "supplemental_intelligence", "not_applicable", None, requested=False, failure_reason="provider_unsupported"),
            _source("finnhub", "supplemental_intelligence", "not_applicable", None, requested=False, failure_reason="provider_unsupported"),
            _source(
                "flashalpha", "specialist_futures_intelligence", "used" if reason is None else "failed", provider_symbol,
                evidence=["options-on-futures gamma exposure", "gamma flip", "call/put walls"] if reason is None else [],
                affected_score=reason is None, failure_reason=reason_detail or reason,
                timeframes={"snapshot": {"latest_timestamp": as_of.isoformat() if as_of else None, "quality": "valid" if reason is None else "rejected"}},
            ),
            _source("ftmo_mt5", "execution_pricing", "not_requested", instrument.ftmo_symbol, requested=False, failure_reason="analysis_not_qualified"),
        ]
        if reason is not None:
            if is_index(instrument):
                await self.hierarchy.invalidate(instrument)
            result = _insufficient(instrument.ftmo_symbol, FTMOAssetClass.FUTURES_LINKED.value, sources, reason, now=observed)
            result["reason_detail"] = reason_detail
            result["provider_diagnostics"] = diagnostics
            result.update({
                "ftmo_symbol": instrument.ftmo_symbol,
                "underlying_market": instrument.underlying_market,
                "futures_symbol": instrument.futures_symbol,
                "micro_futures_symbol": instrument.micro_futures_symbol,
                "analysis_provider": "flashalpha",
                "analysis_instrument": provider_symbol,
            })
            if is_index(instrument):
                result.update(POLICY.metadata())
            return result

        if is_index(instrument):
            analysis = await self.hierarchy.analyse(instrument, context=context, now=now)
            analysis["analysis_sources"] += sources
            analysis["provider_diagnostics"] = diagnostics
            analysis.update({"futures_symbol": instrument.futures_symbol, "micro_futures_symbol": instrument.micro_futures_symbol,
                             "underlying_market": instrument.underlying_market, "provider_consensus": "PARTIAL",
                             "fallback_status": "no_snapshot_only_fallback"})
            return analysis
        analysis = build_flashalpha_futures_analysis(context)
        validity_minutes = max(5, int(self.environment.get("MONATISE_FUTURES_ON_DEMAND_VALIDITY_MINUTES", "30")))
        analysis.update({
            "provider_diagnostics": diagnostics,
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
        return apply_flashalpha_plan(analysis, context, config=MultiTPConfiguration.from_environment(self.environment), route=route_for(instrument), now=observed)
