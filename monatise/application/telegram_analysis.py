"""Canonical Telegram on-demand analysis normalization and formatting.

This module contains no broker transport.  It resolves an allowlisted request
to the FTMO registry, normalizes the existing Monatise analysis result, and
formats the immutable analysis/proposal lineage consumed by Telegram.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from monatise.application.ftmo_registry import FTMOAssetClass, FTMOInstrument, FTMOInstrumentRegistry


RISK_CEILING_PERCENT = Decimal("3.00")


class TelegramAnalysisError(RuntimeError):
    """A Telegram analysis request cannot be resolved safely."""


@dataclass(frozen=True)
class ResolvedTelegramInstrument:
    requested: str
    canonical: str
    analysis_symbol: str
    analysis_provider: str
    analysis_instrument: str
    execution_registry_symbol: str
    asset_class: FTMOAssetClass
    instrument: FTMOInstrument


_EXPLICIT_ALIASES = {
    "GOLD": "XAU/USD",
    "XAU": "XAU/USD",
    "XAUUSD": "XAU/USD",
    "BITCOIN": "BTCUSD",
    "BTC": "BTCUSD",
    "BTCUSD": "BTCUSD",
    "BTCUSDT": "BTCUSD",
    "ETHEREUM": "ETHUSD",
    "ETH": "ETHUSD",
    "ETHUSD": "ETHUSD",
    "ETHUSDT": "ETHUSD",
    "NASDAQ": "US100.cash",
    "NASDAQ100": "US100.cash",
    "NQ": "US100.cash",
    "US100": "US100.cash",
    "US100CASH": "US100.cash",
}


def symbol_key(value: str) -> str:
    return "".join(character for character in value.strip().upper() if character.isalnum())


def resolve_telegram_instrument(raw: str, registry: FTMOInstrumentRegistry) -> ResolvedTelegramInstrument:
    requested = raw.strip().lstrip("$")
    if not requested:
        raise TelegramAnalysisError("Instrument mapping could not be verified.")
    key = symbol_key(requested)
    explicit = _EXPLICIT_ALIASES.get(key)
    if explicit is not None:
        candidates = [registry.resolve(explicit)]
    else:
        candidates = []
        for instrument in registry.all(enabled_only=True):
            accepted = {
                symbol_key(instrument.ftmo_symbol),
                symbol_key(instrument.underlying_symbol),
            }
            if instrument.provider_symbol:
                accepted.add(symbol_key(instrument.provider_symbol))
            if instrument.asset_class is FTMOAssetClass.CRYPTO:
                base = symbol_key(instrument.provider_symbol or instrument.underlying_symbol)
                accepted.update({f"{base}USD", f"{base}USDT"})
            if key in accepted:
                candidates.append(instrument)
    unique = {item.ftmo_symbol: item for item in candidates}
    if len(unique) != 1:
        raise TelegramAnalysisError("Instrument mapping could not be verified.")
    instrument = next(iter(unique.values()))
    if instrument.asset_class is FTMOAssetClass.CRYPTO:
        provider, analysis_symbol = "coinglass", instrument.underlying_symbol
        analysis_instrument = f"{instrument.provider_symbol or instrument.underlying_symbol}USDT"
    elif instrument.asset_class is FTMOAssetClass.FOREX:
        provider = instrument.market_data_provider
        analysis_symbol = instrument.provider_symbol or instrument.underlying_symbol
        analysis_instrument = analysis_symbol
    elif instrument.asset_class is FTMOAssetClass.STOCK:
        provider, analysis_symbol = instrument.market_data_provider, instrument.provider_symbol or instrument.underlying_symbol
        analysis_instrument = analysis_symbol
    else:
        provider, analysis_symbol = instrument.market_data_provider, instrument.futures_symbol or instrument.underlying_symbol
        analysis_instrument = analysis_symbol
    return ResolvedTelegramInstrument(
        requested=requested,
        canonical=instrument.ftmo_symbol,
        analysis_symbol=analysis_symbol,
        analysis_provider=provider,
        analysis_instrument=analysis_instrument,
        execution_registry_symbol=instrument.ftmo_symbol,
        asset_class=instrument.asset_class,
        instrument=instrument,
    )


def recommended_risk_percent(score: Any) -> Decimal:
    """Return a conviction-scaled recommendation that never defaults to 3%."""
    try:
        conviction = min(10, max(0, abs(int(score or 0))))
    except (TypeError, ValueError):
        conviction = 0
    if conviction >= 10:
        return Decimal("2.00")
    if conviction >= 9:
        return Decimal("1.50")
    if conviction >= 8:
        return Decimal("1.25")
    if conviction >= 7:
        return Decimal("1.00")
    return Decimal("0.50")


def request_identity(chat_id: str, update_id: Any) -> tuple[str, str]:
    digest = hashlib.sha256(f"telegram:{chat_id}:{update_id}".encode()).hexdigest()
    return f"tgr_{digest[:20]}", f"ana_{digest[20:40]}"


def signal_identity(request_id: str, analysis_id: str, setup: Mapping[str, Any]) -> str:
    immutable = json.dumps({
        "request_id": request_id,
        "analysis_id": analysis_id,
        "instrument": setup.get("canonical_instrument"),
        "direction": setup.get("direction"),
        "entry": setup.get("entry"),
        "entry_zone": setup.get("entry_zone"),
        "stop": setup.get("stop_loss"),
        "targets": setup.get("targets"),
        "expires_at": setup.get("expires_at"),
    }, sort_keys=True, separators=(",", ":"), default=str)
    return "sig_" + hashlib.sha256(immutable.encode()).hexdigest()[:24]


def normalize_analysis(
    raw: Mapping[str, Any],
    resolved: ResolvedTelegramInstrument,
    *,
    request_id: str,
    analysis_id: str,
    requested_at: datetime,
    started_at: datetime,
    completed_at: datetime,
    session: Mapping[str, Any],
) -> dict[str, Any]:
    asset_class = resolved.asset_class
    if asset_class is FTMOAssetClass.CRYPTO:
        classification = str(raw.get("classification") or "no_trade").casefold()
        direction = str(raw.get("direction") or "none").casefold()
        confirmed = str(raw.get("entry_confirmation_status") or "").casefold() == "confirmed"
        entry_zone = raw.get("entry_zone") if isinstance(raw.get("entry_zone"), Mapping) else None
        entry = raw.get("entry")
        if entry is None and entry_zone:
            entry = (float(entry_zone["low"]) + float(entry_zone["high"])) / 2
        stop = raw.get("invalidation")
        targets = list(raw.get("targets") or ([raw.get("target")] if raw.get("target") is not None else []))
        qualified = classification not in {"no_trade", "grid", "two_sided", "none"} and direction in {"long", "short"} and confirmed
        decision = f"QUALIFIED {direction.upper()}" if qualified else "NO_TRADE"
        current_price = raw.get("current_reference_price") or (raw.get("evidence") or {}).get("current_price") or raw.get("entry")
        provider_evidence = raw.get("derivatives") or (raw.get("evidence") or {}).get("derivatives") or {}
        reasons = list(raw.get("blockers") or raw.get("reasons") or raw.get("price_action_reasons") or [])
    elif asset_class in {FTMOAssetClass.STOCK, FTMOAssetClass.FOREX}:
        stock_decision = str(raw.get("decision") or "NO_TRADE").upper()
        direction = "long" if stock_decision == "BUY_WATCH" else "short" if stock_decision == "SELL_WATCH" else "none"
        qualified = raw.get("setup_status") == "confirmed" and direction in {"long", "short"}
        entry, stop = raw.get("entry"), raw.get("stop_loss")
        targets = list(raw.get("targets") or ([raw.get("target")] if raw.get("target") is not None else []))
        entry_zone = raw.get("entry_zone") if isinstance(raw.get("entry_zone"), Mapping) else None
        decision = f"QUALIFIED {direction.upper()}" if qualified else "NO_TRADE"
        current_price = raw.get("current_price") or (raw.get("snapshot") or {}).get("latest_trade") or entry
        provider_evidence = raw.get("additional_context") or {}
        reasons = list(raw.get("cautions") or raw.get("reasons") or [])
        classification, confirmed = "trend" if qualified else "no_trade", qualified
    else:
        futures_decision = str(raw.get("decision") or "NO_TRADE").upper()
        direction = str(raw.get("direction") or "none").casefold()
        qualified = raw.get("setup_status") == "confirmed" and futures_decision in {"BUY_WATCH", "SELL_WATCH"} and direction in {"long", "short"}
        entry, stop = raw.get("entry"), raw.get("stop_loss")
        targets = list(raw.get("targets") or ([raw.get("target")] if raw.get("target") is not None else []))
        entry_zone = raw.get("entry_zone") if isinstance(raw.get("entry_zone"), Mapping) else None
        decision = f"QUALIFIED {direction.upper()}" if qualified else "NO_TRADE"
        current_price = raw.get("current_price") or entry
        provider_evidence = {key: raw.get(key) for key in ("gamma_flip", "call_wall", "put_wall", "net_gex", "net_gex_label") if raw.get(key) is not None}
        reasons = list(raw.get("reasons") or [])
        classification, confirmed = "trend" if qualified else "no_trade", qualified

    score = int(raw.get("score") or 0)
    recommended = recommended_risk_percent(score)
    expires_at = raw.get("expires_at") or raw.get("valid_until")
    reference_in_zone = True
    if entry_zone and current_price is not None:
        try:
            reference_in_zone = float(entry_zone["low"]) <= float(current_price) <= float(entry_zone["high"])
        except (KeyError, TypeError, ValueError):
            reference_in_zone = False
    executable = bool(qualified and confirmed and entry is not None and stop is not None and targets and expires_at and reference_in_zone)
    if qualified and not reference_in_zone:
        decision = f"QUALIFIED {direction.upper()} — WAITING FOR ENTRY ZONE"

    return {
        "telegram_request_id": request_id,
        "request_id": request_id,
        "analysis_id": analysis_id,
        "requested_instrument": resolved.requested,
        "canonical_instrument": resolved.canonical,
        "analysis_symbol": resolved.analysis_symbol,
        "analysis_provider": resolved.analysis_provider,
        "analysis_instrument": resolved.analysis_instrument,
        "execution_registry_symbol": resolved.execution_registry_symbol,
        "asset_class": asset_class.value,
        "requested_at": requested_at.isoformat(),
        "analysis_started_at": started_at.isoformat(),
        "analysis_completed_at": completed_at.isoformat(),
        "timeframe": raw.get("interval") or raw.get("timeframe") or "15m",
        "session": dict(session),
        "market_state": raw.get("market_state") or raw.get("market_regime") or classification.upper(),
        "bias": direction.upper(),
        "current_reference_price": current_price,
        "liquidity": raw.get("liquidity") or {},
        "structure": raw.get("market_structure") or {},
        "supply_demand": raw.get("supply_demand") or {},
        "fibonacci": raw.get("fibonacci") or {},
        "order_flow": raw.get("order_flow") or provider_evidence,
        "entry": entry,
        "entry_zone": dict(entry_zone) if entry_zone else None,
        "stop_loss": stop,
        "targets": targets,
        "reward_risk": raw.get("reward_risk"),
        "score": score,
        "score_threshold": int(raw.get("score_threshold") or 7),
        "conviction": raw.get("conviction") if raw.get("conviction") is not None else abs(score),
        "decision": decision,
        "qualified": qualified,
        "executable": executable,
        "confirmation_status": "confirmed" if confirmed else str(raw.get("entry_confirmation_status") or raw.get("setup_status") or "not_confirmed"),
        "reference_price_in_entry_zone": reference_in_zone,
        "expires_at": expires_at,
        "risk_ceiling_percent": str(RISK_CEILING_PERCENT),
        "recommended_risk_percent": str(recommended),
        "reasons": reasons[:8],
        "market_data_provenance": {
            "provider": resolved.analysis_provider,
            "instrument": resolved.analysis_instrument,
            "observed_at": raw.get("market_observed_at") or raw.get("as_of") or raw.get("generated_at") or completed_at.isoformat(),
            "evidence": provider_evidence,
        },
        "raw_audit_reference": raw.get("audit_reference") or raw.get("run_id"),
        "autonomous_execution": False,
    }


def _compact(value: Any, *, maximum: int = 3) -> str:
    if isinstance(value, Mapping):
        parts = []
        for key, item in list(value.items())[:maximum]:
            if item is not None and item != "" and item != [] and item != {}:
                parts.append(f"{str(key).replace('_', ' ')}={item}")
        return "; ".join(parts) or "No decisive evidence"
    if isinstance(value, (list, tuple)):
        return "; ".join(map(str, value[:maximum])) or "No decisive evidence"
    return str(value or "No decisive evidence")


def format_analysis(analysis: Mapping[str, Any]) -> str:
    session = analysis.get("session") or {}
    zone = analysis.get("entry_zone") or {}
    targets = analysis.get("targets") or []
    lines = [
        "MONATISE ANALYSIS",
        f"Request: {analysis['request_id']} | Analysis: {analysis['analysis_id']}",
        f"Instrument: {analysis['canonical_instrument']} | Timeframe: {analysis['timeframe']}",
        f"UTC: {session.get('analysis_timestamp_utc') or analysis['analysis_completed_at']}",
        f"Session: {session.get('market_session') or 'UNKNOWN'} | Market: {'OPEN' if session.get('market_open') is True else 'CLOSED' if session.get('market_open') is False else 'UNKNOWN'}",
        f"Broker break: {session.get('broker_break_proximity') or 'UNKNOWN'}",
        f"Market state: {analysis.get('market_state') or 'UNKNOWN'} | Bias: {analysis.get('bias') or 'NONE'}",
        f"Current reference price: {analysis.get('current_reference_price') if analysis.get('current_reference_price') is not None else 'unavailable'}",
        f"Liquidity: {_compact(analysis.get('liquidity'))}",
        f"Structure: {_compact(analysis.get('structure'))}",
        f"Supply / Demand: {_compact(analysis.get('supply_demand'))}",
        f"Fibonacci: {_compact(analysis.get('fibonacci'))}",
        f"Order flow: {_compact(analysis.get('order_flow'))}",
    ]
    if zone:
        lines.append(f"Entry zone: {zone.get('low')}–{zone.get('high')}")
    elif analysis.get("entry") is not None:
        lines.append(f"Entry reference: {analysis['entry']}")
    if analysis.get("stop_loss") is not None:
        lines.append(f"Structural invalidation / SL: {analysis['stop_loss']}")
    if targets:
        lines.append("Targets: " + " / ".join(map(str, targets[:3])))
    lines.extend((
        f"Conviction: {analysis.get('conviction')}/10 | Threshold: {analysis.get('score_threshold')}",
        f"Risk ceiling: {analysis['risk_ceiling_percent']}% | Recommended risk: {analysis['recommended_risk_percent']}%",
        f"Signal expires: {analysis.get('expires_at') or 'NO EXECUTABLE EXPIRY'}",
        f"Decision: {analysis['decision']}",
        f"Analysis source: {analysis['analysis_provider']} ({analysis['analysis_instrument']})",
    ))
    if not analysis.get("executable"):
        reasons = analysis.get("reasons") or []
        if reasons:
            lines.append("Reason: " + "; ".join(map(str, reasons[:4])))
        lines.append("No trade proposal created.")
    return "\n".join(lines)
