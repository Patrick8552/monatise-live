from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from monatise.application.flashalpha_analysis import flashalpha_directional_bias


def build_stock_analysis(
    context: dict[str, Any], *, bars: list[dict[str, Any]] | None = None,
    trigger_bars: list[dict[str, Any]] | None = None, snapshot: dict[str, Any] | None = None,
    finnhub: dict[str, Any] | None = None, flashalpha: dict[str, Any] | None = None,
    now: datetime | None = None, validity_minutes: int = 60,
) -> dict[str, Any]:
    """Convert Quiver alternative data into an analysis-only stock watch signal."""
    summary = context.get("summary") if isinstance(context.get("summary"), dict) else {}
    score = int(summary.get("score") or 0)
    available = bool(context.get("available"))
    if not available:
        decision, reason = "NO_TRADE", "QUIVER_DATA_UNAVAILABLE"
    elif score >= 2:
        decision, reason = "BUY_WATCH", "ALTERNATIVE_DATA_SUPPORTIVE"
    elif score <= -2:
        decision, reason = "SELL_WATCH", "ALTERNATIVE_DATA_CAUTIOUS"
    else:
        decision, reason = "NO_TRADE", "CONFLUENCE_BELOW_THRESHOLD"
    flashalpha_summary = summarize_flashalpha_context(flashalpha or {})
    expected_bias = "bullish" if decision == "BUY_WATCH" else "bearish" if decision == "SELL_WATCH" else None
    if expected_bias and flashalpha_summary["available"] and flashalpha_summary["directional_bias"] != expected_bias:
        decision, reason = "NO_TRADE", "FLASHALPHA_POSITIONING_CONFLICT"
    result = {
        "asset": context.get("symbol"),
        "asset_class": "stock",
        "decision": decision,
        "score": score,
        "score_threshold": 2,
        "reason_code": reason,
        "reasons": list(summary.get("drivers") or [])[:4],
        "cautions": list(summary.get("cautions") or [])[:3],
        "activity": summary.get("activity") or {},
        "data_source": context.get("source") or "Quiver Quantitative",
        "direction_authority": "Quiver insider and Congress activity",
        "additional_context": {
            **summarize_finnhub_context(finnhub or {}, snapshot or {}),
            "flashalpha": flashalpha_summary,
        },
        "execution": {"enabled": False, "orders_placed": 0},
    }
    current_time = now or datetime.now(timezone.utc)
    evidence_bars = trigger_bars if trigger_bars is not None else bars or []
    result.update(build_directional_levels(decision, evidence_bars, snapshot or {}, now=current_time, candle_minutes=15 if trigger_bars is not None else 60))
    result.update(build_setup_lifecycle(result, evidence_bars, current_time, validity_minutes=validity_minutes))
    return result


def build_setup_lifecycle(
    analysis: dict[str, Any], bars: list[dict[str, Any]], now: datetime,
    *, validity_minutes: int = 60,
) -> dict[str, Any]:
    generated_at = now.astimezone(timezone.utc)
    clean = [row for row in bars if _bar_time(row.get("t")) is not None]
    confirmed_close = _bar_time(clean[-1].get("t")) if clean else None
    market_data_as_of = confirmed_close.isoformat() if confirmed_close else None
    setup_status = str(analysis.get("setup_status") or "watch")
    actionable = analysis.get("decision") in {"BUY_WATCH", "SELL_WATCH"} and setup_status == "confirmed" and confirmed_close is not None
    nominal_expiry = confirmed_close + timedelta(minutes=max(1, validity_minutes)) if actionable and confirmed_close else None
    session_expiry = _regular_session_close(confirmed_close) if actionable and confirmed_close else None
    expires_at = min(nominal_expiry, session_expiry) if nominal_expiry and session_expiry else nominal_expiry
    state = "ACTIVE" if actionable else "NO_TRADE"
    expiry_reason = None
    remaining = max(0, int((expires_at - generated_at).total_seconds())) if expires_at else 0
    if actionable and expires_at and generated_at >= expires_at:
        state = "EXPIRED"
        expiry_reason = "SESSION_EXPIRED" if session_expiry and expires_at == session_expiry and nominal_expiry and session_expiry < nominal_expiry else "SETUP_EXPIRED"
        remaining = 0
        analysis.update({
            "decision": "NO_TRADE", "reason_code": expiry_reason, "setup_status": "expired",
            "entry": None, "stop_loss": None, "target": None, "reward_risk": None,
        })
    elif setup_status == "entry_missed":
        state, expiry_reason = "INVALIDATED", "ENTRY_MISSED"
    elif setup_status == "market_data_unavailable":
        state, expiry_reason = "NO_TRADE", "MARKET_DATA_STALE"
    return {
        "context_timeframe": "4H/Daily", "analysis_timeframe": "1H", "trigger_timeframe": "15M",
        "analysis_generated_at": generated_at.isoformat(), "market_data_as_of": market_data_as_of,
        "last_confirmed_candle_close": market_data_as_of,
        "setup_created_at": confirmed_close.isoformat() if actionable and confirmed_close else None,
        "setup_expires_at": expires_at.isoformat() if expires_at else None,
        "validity_remaining_seconds": remaining, "setup_state": state, "expiry_reason": expiry_reason,
    }


def _regular_session_close(timestamp: datetime) -> datetime:
    eastern = ZoneInfo("America/New_York")
    local = timestamp.astimezone(eastern)
    close = local.replace(hour=16, minute=0, second=0, microsecond=0)
    return close.astimezone(timezone.utc)


def summarize_finnhub_context(finnhub: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    quote = finnhub.get("quote") if isinstance(finnhub.get("quote"), dict) else {}
    recommendations = finnhub.get("recommendations") if isinstance(finnhub.get("recommendations"), list) else []
    latest = recommendations[0] if recommendations and isinstance(recommendations[0], dict) else {}
    alpaca_quote = snapshot.get("latestQuote") if isinstance(snapshot.get("latestQuote"), dict) else {}
    alpaca_mid = None
    if _positive_number(alpaca_quote.get("bp")) and _positive_number(alpaca_quote.get("ap")):
        alpaca_mid = (float(alpaca_quote["bp"]) + float(alpaca_quote["ap"])) / 2
    finnhub_price = float(quote.get("c")) if _positive_number(quote.get("c")) else None
    divergence = abs(finnhub_price - alpaca_mid) / alpaca_mid * 100 if finnhub_price and alpaca_mid else None
    return {
        "source": finnhub.get("source") or "Finnhub",
        "quote": finnhub_price,
        "alpaca_quote_divergence_pct": round(divergence, 3) if divergence is not None else None,
        "news_count": len(finnhub.get("news") or []),
        "analyst_consensus": {key: int(latest.get(key) or 0) for key in ("strongBuy", "buy", "hold", "sell", "strongSell")},
        "authoritative_for_direction": False,
    }


def summarize_flashalpha_context(flashalpha: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": flashalpha.get("source") or "FlashAlpha",
        "available": not flashalpha.get("unavailable") and flashalpha.get("net_gex") is not None,
        "gamma_flip": flashalpha.get("gamma_flip"),
        "net_gex": flashalpha.get("net_gex"),
        "net_gex_label": flashalpha.get("net_gex_label"),
        "call_wall": flashalpha.get("call_wall"),
        "put_wall": flashalpha.get("put_wall"),
        "underlying_price": flashalpha.get("underlying_price"),
        "as_of": flashalpha.get("as_of"),
        "directional_bias": flashalpha_directional_bias(flashalpha),
        "authoritative_for_direction": "confirmation_only",
    }


def build_directional_levels(
    decision: str, bars: list[dict[str, Any]], snapshot: dict[str, Any], *,
    now: datetime | None = None, candle_minutes: int = 60,
) -> dict[str, Any]:
    clean = [row for row in bars if all(_positive_number(row.get(key)) for key in ("h", "l", "c"))]
    if decision not in {"BUY_WATCH", "SELL_WATCH"} or len(clean) < 22:
        return {"setup_status": "watch", "entry": None, "stop_loss": None, "target": None, "reward_risk": None}
    current_time = now or datetime.now(timezone.utc)
    latest_time = _bar_time(clean[-1].get("t"))
    if latest_time is None or latest_time + timedelta(minutes=max(1, candle_minutes)) > current_time or current_time - latest_time > timedelta(days=4):
        return {"setup_status": "market_data_unavailable", "entry": None, "stop_loss": None, "target": None, "reward_risk": None}
    previous, latest = clean[-21:-1], clean[-1]
    ranges = []
    for index in range(max(1, len(clean) - 14), len(clean)):
        high, low, previous_close = float(clean[index]["h"]), float(clean[index]["l"]), float(clean[index - 1]["c"])
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    atr = sum(ranges) / len(ranges)
    quote = snapshot.get("latestQuote") if isinstance(snapshot.get("latestQuote"), dict) else {}
    bid, ask = quote.get("bp"), quote.get("ap")
    mark = (float(bid) + float(ask)) / 2 if _positive_number(bid) and _positive_number(ask) else float(latest["c"])
    if decision == "BUY_WATCH":
        trigger = max(float(row["h"]) for row in previous)
        confirmed = float(latest["c"]) > trigger
        entry = trigger
        structural_stop = min(float(row["l"]) for row in clean[-10:])
        stop = min(structural_stop, entry - atr * 1.25)
        risk = entry - stop
        target = entry + risk * 2
    else:
        trigger = min(float(row["l"]) for row in previous)
        confirmed = float(latest["c"]) < trigger
        entry = trigger
        structural_stop = max(float(row["h"]) for row in clean[-10:])
        stop = max(structural_stop, entry + atr * 1.25)
        risk = stop - entry
        target = entry - risk * 2
    if not confirmed or not all(math.isfinite(value) and value > 0 for value in (mark, entry, stop, target, risk)):
        return {"setup_status": "awaiting_price_confirmation", "current_price": round(mark, 4), "entry": None, "stop_loss": None, "target": None, "reward_risk": None, "atr": round(atr, 4)}
    if abs(mark - entry) > atr * 0.75:
        return {"setup_status": "entry_missed", "current_price": round(mark, 4), "entry": None, "stop_loss": None, "target": None, "reward_risk": None, "atr": round(atr, 4)}
    return {"setup_status": "confirmed", "current_price": round(mark, 4), "entry": round(entry, 4), "stop_loss": round(stop, 4), "target": round(target, 4), "reward_risk": 2.0, "atr": round(atr, 4), "level_source": "Alpaca IEX hourly bars"}


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0


def _bar_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
