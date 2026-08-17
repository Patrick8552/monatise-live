"""Pure TradingView alert normalization, validation, and classification.

No HTTP, storage, or session concerns live here -- this module is imported by
both the standalone live server (monatise/live/server.py) and the production
ASGI app (monatise/application/production.py), and must not depend on either.
"""

from __future__ import annotations

import time


STOCK_WATCHLIST = ("SPX", "NDX", "NASDAQ", "QQQ", "SPY", "AAPL", "TSLA", "NVDA")
METALS_WATCHLIST = {"XAG", "XAGUSD", "SILVER"}
TRADINGVIEW_ACTIONS = {
    "BUY": "BUY",
    "BULL": "BUY",
    "BULLISH": "BUY",
    "LONG": "BUY",
    "SELL": "SELL",
    "BEAR": "SELL",
    "BEARISH": "SELL",
    "SHORT": "SELL",
    "WAIT": "WAIT",
    "NEUTRAL": "WAIT",
    "HOLD": "WAIT",
}
TRADINGVIEW_FRESH_SECONDS = 5 * 60
TRADINGVIEW_SNAPSHOT_LOCK_SECONDS = 15 * 60
TRADINGVIEW_ALERT_LIMIT = 50


def normalize_alert_symbol(value: str) -> str:
    raw = str(value).upper().strip()
    if ":" in raw:
        raw = raw.rsplit(":", 1)[-1]
    symbol = "".join(character for character in raw if character.isalnum())
    aliases = {
        "IXIC": "NASDAQ",
        "XAGUSD": "XAG",
        "SILVER": "XAG",
        "SILVERUSD": "XAG",
    }
    if symbol in aliases:
        return aliases[symbol]
    crypto_bases = {"BTC", "ETH", "SOL", "HYPE", "BNB", "XRP", "DOGE"}
    for quote in ("USDT", "USDC", "USD"):
        if symbol.endswith(quote) and symbol[: -len(quote)] in crypto_bases:
            return symbol[: -len(quote)]
    return symbol[:16]


def is_removed_gold_symbol(value: str) -> bool:
    raw = str(value).upper().strip()
    if ":" in raw:
        raw = raw.rsplit(":", 1)[-1]
    symbol = "".join(character for character in raw if character.isalnum())
    return symbol in {"GOLD", "XAU", "XAUUSD", "GOLDUSD"}


def is_removed_forex_symbol(value: str) -> bool:
    raw = str(value).upper().strip()
    if ":" in raw:
        raw = raw.rsplit(":", 1)[-1]
    symbol = "".join(character for character in raw if character.isalpha())
    currencies = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}
    return len(symbol) == 6 and symbol[:3] in currencies and symbol[3:] in currencies and symbol[:3] != symbol[3:]


def normalize_alert_action(value: str) -> str:
    return TRADINGVIEW_ACTIONS.get(str(value).strip().upper(), "WAIT")


def tradingview_route(symbol: str) -> str:
    symbol = str(symbol or "").upper().strip()
    if symbol in METALS_WATCHLIST:
        return "metals and commodities primary signal feed"
    if symbol in STOCK_WATCHLIST:
        return "stocks and indices primary signal feed"
    return "crypto confluence feed"


def float_payload(payload: dict, *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value in {None, ""}:
            continue
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def normalize_tradingview_grid(payload: dict) -> list[dict]:
    raw = payload.get("grid") or payload.get("levels") or payload.get("orders")
    levels: list[dict] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw[:12]):
            if isinstance(item, dict):
                price = float_payload(item, "price", "level", "entry")
                side = str(item.get("side") or item.get("action") or "").strip().lower()
                label = str(item.get("label") or item.get("level_id") or f"tv-{index + 1}").strip()[:32]
            else:
                price = None
                side = ""
                label = f"tv-{index + 1}"
                try:
                    price = float(str(item).replace(",", ""))
                except (TypeError, ValueError):
                    pass
            if price is None or price <= 0:
                continue
            levels.append({"label": label, "price": price, "side": "sell" if side.startswith("s") else "buy"})
    elif isinstance(raw, str):
        for index, part in enumerate(raw.replace("|", ",").split(",")[:12]):
            item = part.strip()
            if not item:
                continue
            side = "sell" if item.lower().startswith(("sell", "short", "resistance")) else "buy"
            number = "".join(character for character in item if character.isdigit() or character in ".-")
            try:
                price = float(number)
            except ValueError:
                continue
            if price > 0:
                levels.append({"label": f"tv-{index + 1}", "price": price, "side": side})
    return levels


def indicator_bias_value(value: str) -> int:
    text = str(value or "").lower()
    if not text or text in {"0", "none", "neutral", "wait", "n/a", "na"}:
        return 0
    bearish_terms = ("sell", "short", "bear", "bearish", "down", "below", "resistance", "reject", "lower", "cross down", "supply")
    bullish_terms = ("buy", "long", "bull", "bullish", "up", "above", "support", "reclaim", "higher", "cross up", "demand")
    if any(term in text for term in bearish_terms):
        return -1
    if any(term in text for term in bullish_terms):
        return 1
    return 0


def classify_tradingview_alert(alert: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    action = str(alert.get("action") or "WAIT").upper()
    try:
        confidence = max(0.0, min(100.0, float(alert.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    received_at = float(alert.get("receivedAt") or 0)
    age_seconds = max(0, int(now - received_at)) if received_at else None
    fresh = received_at > 0 and age_seconds is not None and age_seconds <= TRADINGVIEW_FRESH_SECONDS
    indicators = alert.get("indicators") if isinstance(alert.get("indicators"), dict) else {}
    indicator_score = sum(indicator_bias_value(value) for value in indicators.values())
    indicator_bias = "BUY" if indicator_score > 0 else "SELL" if indicator_score < 0 else "WAIT"
    if action in {"BUY", "SELL"} and indicator_bias in {"BUY", "SELL"}:
        agreement = "confirming" if action == indicator_bias else "conflicting"
    elif action in {"BUY", "SELL"}:
        agreement = "candidate"
    elif indicator_bias in {"BUY", "SELL"}:
        agreement = "indicator-watch"
    else:
        agreement = "informational"
    if not fresh:
        state = "stale"
    elif agreement == "conflicting":
        state = "conflict-watch"
    elif action in {"BUY", "SELL"} and confidence >= 70:
        state = "confirming"
    elif action in {"BUY", "SELL"} and confidence >= 50:
        state = "candidate"
    else:
        state = "watch"
    lock_start = int(received_at) if received_at else int(now)
    return {
        "role": "tradingview_primary_signal",
        "route": tradingview_route(str(alert.get("symbol") or "")),
        "state": state,
        "fresh": fresh,
        "ageSeconds": age_seconds,
        "agreement": agreement,
        "action": action,
        "confidence": confidence,
        "indicatorBias": indicator_bias,
        "indicatorScore": indicator_score,
        "indicatorCount": len(indicators),
        "snapshotWindow": {
            "lockSeconds": TRADINGVIEW_SNAPSHOT_LOCK_SECONDS,
            "fastCheckSeconds": TRADINGVIEW_FRESH_SECONDS,
            "startedAt": lock_start,
            "fastReassessAt": lock_start + TRADINGVIEW_FRESH_SECONDS,
            "reassessAt": lock_start + TRADINGVIEW_SNAPSHOT_LOCK_SECONDS,
        },
        "executionAllowed": False,
        "executionNote": "TradingView is the primary signal feed here; Monatise still keeps execution behind risk and snapshot gates.",
    }


def normalize_indicator_payload(payload: dict) -> dict:
    indicator_keys = {
        "luxalgo",
        "historical_color",
        "liquidity_swings",
        "wick_extremity",
        "equal_highs_lows",
        "liquidity_grabs",
        "dynamic_trend_pivot",
        "auto_fib",
        "daily_vwap",
        "volume_profile",
        "htf_levels",
        "rsi_sma_cross",
    }
    raw = payload.get("indicators")
    indicators = raw if isinstance(raw, dict) else {}
    normalized = {
        str(key).strip().lower(): str(value).strip()[:80]
        for key, value in indicators.items()
        if str(key).strip()
    }
    for key in indicator_keys:
        if key in payload:
            normalized[key] = str(payload.get(key, "")).strip()[:80]
    return normalized


def normalize_tradingview_alert(payload: dict | str) -> dict:
    if isinstance(payload, str):
        raw = payload.strip()
        payload = {"message": raw}
        parts = [part.strip() for part in raw.replace("|", ",").split(",") if part.strip()]
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                payload[key.strip().lower()] = value.strip()
        if "symbol" not in payload and parts:
            payload["symbol"] = parts[0]
        if "action" not in payload and len(parts) > 1:
            payload["action"] = parts[1]
    raw_symbol = str(payload.get("symbol") or payload.get("ticker") or payload.get("pair") or "").strip()
    if not raw_symbol:
        raise ValueError("TradingView alert symbol is required")
    if is_removed_gold_symbol(raw_symbol):
        raise ValueError("Gold/XAU setups are not supported")
    if is_removed_forex_symbol(raw_symbol):
        raise ValueError("Forex setups are not supported")
    symbol = normalize_alert_symbol(raw_symbol)
    raw_action = str(payload.get("action") or payload.get("signal") or payload.get("bias") or "").strip().upper()
    if not raw_action:
        raise ValueError("TradingView alert action is required")
    if raw_action not in TRADINGVIEW_ACTIONS:
        raise ValueError(f"Unsupported TradingView alert action: {raw_action}")
    action = normalize_alert_action(raw_action)
    try:
        confidence = max(0.0, min(100.0, float(payload.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "symbol": symbol,
        "action": action,
        "confidence": confidence,
        "timeframe": str(payload.get("timeframe") or payload.get("interval") or "").strip()[:24],
        "indicator": str(payload.get("indicator") or payload.get("strategy") or "TradingView").strip()[:64],
        "indicators": normalize_indicator_payload(payload),
        "price": str(payload.get("price") or payload.get("close") or "").strip()[:32],
        "priceValue": float_payload(payload, "price", "close", "mark"),
        "setup": {
            "entry": float_payload(payload, "entry", "entryPrice", "plannedEntry"),
            "stop": float_payload(payload, "stop", "stopLoss", "sl", "invalidation"),
            "targetOne": float_payload(payload, "target1", "targetOne", "tp1", "target"),
            "targetTwo": float_payload(payload, "target2", "targetTwo", "tp2"),
            "trigger": str(payload.get("trigger") or "").strip()[:120],
            "thesis": str(payload.get("thesis") or payload.get("setup") or "").strip()[:240],
        },
        "grid": normalize_tradingview_grid(payload),
        "hedge": {
            "side": str(payload.get("hedgeSide") or payload.get("hedge_side") or "").strip().upper()[:12],
            "ratio": float_payload(payload, "hedgeRatio", "hedge_ratio", "hedgePct", "hedgePercent"),
            "trigger": float_payload(payload, "hedgeTrigger", "hedge_trigger"),
            "release": float_payload(payload, "hedgeRelease", "hedge_release"),
            "hardExit": float_payload(payload, "hedgeHardExit", "hedge_hard_exit", "hardExit"),
            "note": str(payload.get("hedgeNote") or payload.get("hedge_note") or "").strip()[:180],
        },
        "message": str(payload.get("message") or payload.get("note") or "").strip()[:240],
        "receivedAt": time.time(),
    }


def enrich_tradingview_alert(alert: dict, now: float | None = None) -> dict:
    enriched = dict(alert)
    enriched["classification"] = classify_tradingview_alert(enriched, now=now)
    return enriched
