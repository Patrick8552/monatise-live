from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


LEVERAGED_INVERSE_PATTERN = re.compile(r"(?:2X|3X|ULTRA|BEAR|INVERSE|SHORT|BULL)", re.IGNORECASE)


@dataclass(frozen=True)
class StockUniverseConfiguration:
    minimum_price: float = 5.0
    maximum_spread_bps: float = 80.0
    minimum_daily_dollar_volume: float = 5_000_000.0
    maximum_universe_size: int = 6_000
    include_leveraged: bool = False
    shortlist_per_side: int = 5
    minimum_score: int = 7
    minimum_reward_risk: float = 1.5


@dataclass(frozen=True)
class StockCandidate:
    symbol: str
    name: str
    side: str
    rank_score: float
    price: float
    spread_bps: float
    daily_dollar_volume: float
    stage_a_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "name": self.name, "side": self.side,
            "rank_score": round(self.rank_score, 4), "price": self.price,
            "spread_bps": round(self.spread_bps, 2), "daily_dollar_volume": round(self.daily_dollar_volume, 2),
            "stage_a_reasons": list(self.stage_a_reasons),
        }


def eligible_stock_assets(assets: Iterable[dict[str, Any]], configuration: StockUniverseConfiguration) -> tuple[list[dict[str, Any]], dict[str, int]]:
    eligible: list[dict[str, Any]] = []
    exclusions: dict[str, int] = {}
    for asset in assets:
        reason = _asset_exclusion(asset, configuration)
        if reason:
            exclusions[reason] = exclusions.get(reason, 0) + 1
            continue
        eligible.append(asset)
        if len(eligible) >= configuration.maximum_universe_size:
            break
    return eligible, exclusions


def rank_stock_universe(
    assets: Iterable[dict[str, Any]], snapshots: dict[str, dict[str, Any]], configuration: StockUniverseConfiguration
) -> tuple[list[StockCandidate], list[StockCandidate], dict[str, int]]:
    long_candidates: list[StockCandidate] = []
    short_candidates: list[StockCandidate] = []
    exclusions: dict[str, int] = {}
    for asset in assets:
        symbol = str(asset.get("symbol") or "").upper()
        candidate, reason = _rank_snapshot(asset, snapshots.get(symbol) or {}, configuration)
        if reason:
            exclusions[reason] = exclusions.get(reason, 0) + 1
        elif candidate is not None:
            (long_candidates if candidate.side == "long" else short_candidates).append(candidate)
    long_candidates.sort(key=lambda item: (-item.rank_score, -item.daily_dollar_volume, item.symbol))
    short_candidates.sort(key=lambda item: (-item.rank_score, -item.daily_dollar_volume, item.symbol))
    return long_candidates, short_candidates, exclusions


def build_technical_stock_setup(
    candidate: StockCandidate,
    hourly_bars: list[dict[str, Any]],
    daily_bars: list[dict[str, Any]],
    *,
    configuration: StockUniverseConfiguration,
    quiver: dict[str, Any] | None = None,
    flashalpha: dict[str, Any] | None = None,
    finnhub: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "asset": candidate.symbol, "company_name": candidate.name, "asset_class": "stock",
        "direction": candidate.side.upper(), "decision": "NO_TRADE", "score": 0,
        "score_threshold": configuration.minimum_score, "setup_status": "insufficient_market_data",
        "stage_a": candidate.to_dict(), "execution": {"enabled": False, "orders_placed": 0},
        "suppression_reasons": [],
    }
    hourly = _clean_bars(hourly_bars)
    daily = _clean_bars(daily_bars)
    if len(hourly) < 55 or len(daily) < 55:
        result["suppression_reasons"].append("insufficient_bars")
        return _attach_context(result, quiver, flashalpha, finnhub)
    latest_time = _bar_time(hourly[-1].get("t"))
    if latest_time is None or current_time - latest_time > timedelta(days=4):
        result["setup_status"] = "stale_market_data"
        result["suppression_reasons"].append("stale_market_data")
        return _attach_context(result, quiver, flashalpha, finnhub)

    closes = [float(row["c"]) for row in daily]
    volumes = [float(row.get("v") or 0) for row in daily]
    price = closes[-1]
    ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
    rsi = _rsi(closes, 14)
    atr = _atr(hourly, 14)
    previous_high = max(float(row["h"]) for row in hourly[-21:-1])
    previous_low = min(float(row["l"]) for row in hourly[-21:-1])
    volume_ratio = volumes[-1] / (sum(volumes[-21:-1]) / 20) if sum(volumes[-21:-1]) > 0 else 0
    side = candidate.side
    score = 0
    reasons: list[str] = []
    if side == "long":
        if ema20 > ema50: score += 2; reasons.append("daily EMA20 above EMA50")
        if price > ema20: score += 1; reasons.append("price above daily EMA20")
        if float(hourly[-1]["c"]) > previous_high: score += 2; reasons.append("confirmed 20-hour breakout")
        if 52 <= rsi <= 75: score += 1; reasons.append(f"daily RSI {rsi:.1f}")
        if closes[-1] > closes[-2]: score += 1; reasons.append("positive daily momentum")
        trigger_confirmed = float(hourly[-1]["c"]) > previous_high
        entry = float(hourly[-1]["c"])
        stop = min(min(float(row["l"]) for row in hourly[-10:]), entry - 1.25 * atr)
    else:
        if ema20 < ema50: score += 2; reasons.append("daily EMA20 below EMA50")
        if price < ema20: score += 1; reasons.append("price below daily EMA20")
        if float(hourly[-1]["c"]) < previous_low: score += 2; reasons.append("confirmed 20-hour breakdown")
        if 25 <= rsi <= 48: score += 1; reasons.append(f"daily RSI {rsi:.1f}")
        if closes[-1] < closes[-2]: score += 1; reasons.append("negative daily momentum")
        trigger_confirmed = float(hourly[-1]["c"]) < previous_low
        entry = float(hourly[-1]["c"])
        stop = max(max(float(row["h"]) for row in hourly[-10:]), entry + 1.25 * atr)
    if volume_ratio >= 1.2: score += 1; reasons.append(f"volume expansion {volume_ratio:.2f}x")
    if candidate.rank_score >= 2: score += 1; reasons.append("top Stage-A relative-momentum rank")
    previous_ema20 = _ema(closes[:-1], 20)
    if side == "long" and closes[-2] <= previous_ema20 < closes[-1]:
        score += 1; reasons.append("daily EMA20 reclaim")
    elif side == "short" and closes[-2] >= previous_ema20 > closes[-1]:
        score += 1; reasons.append("daily EMA20 rejection")
    if side == "long" and float(hourly[-1]["l"]) > float(hourly[-3]["h"]):
        score += 1; reasons.append("bullish hourly fair-value gap")
    elif side == "short" and float(hourly[-1]["h"]) < float(hourly[-3]["l"]):
        score += 1; reasons.append("bearish hourly fair-value gap")
    score = min(score, 10)
    signed_score = score if side == "long" else -score
    risk = entry - stop if side == "long" else stop - entry
    target = entry + 2 * risk if side == "long" else entry - 2 * risk
    reward_risk = abs(target - entry) / risk if risk > 0 else 0
    suppressions: list[str] = []
    if not trigger_confirmed: suppressions.append("entry_trigger_unconfirmed")
    if abs(signed_score) < configuration.minimum_score: suppressions.append("score_below_threshold")
    if reward_risk < configuration.minimum_reward_risk: suppressions.append("reward_risk_below_threshold")
    if _earnings_imminent(finnhub or {}, current_time): suppressions.append("imminent_earnings")
    quiver_score = int((((quiver or {}).get("summary") or {}).get("score") or 0))
    if (side == "long" and quiver_score <= -2) or (side == "short" and quiver_score >= 2):
        suppressions.append("quiver_material_conflict")
    flash_bias = _flashalpha_bias(flashalpha or {})
    if flash_bias not in {"neutral", "unavailable", "bullish" if side == "long" else "bearish"}:
        suppressions.append("flashalpha_positioning_conflict")

    result.update({
        "score": signed_score, "current_price": round(entry, 4), "entry": round(entry, 4),
        "stop_loss": round(stop, 4), "target": round(target, 4), "targets": [round(target, 4)],
        "reward_risk": round(reward_risk, 2), "timeframe": "1h trigger / 1d regime",
        "confirmation_trigger": f"closed {'above' if side == 'long' else 'below'} 20-hour {'high' if side == 'long' else 'low'}",
        "valid_until": (current_time + timedelta(hours=24)).isoformat(), "reasons": reasons,
        "suppression_reasons": suppressions, "setup_status": "confirmed" if not suppressions else "suppressed",
        "decision": ("BUY_WATCH" if side == "long" else "SELL_WATCH") if not suppressions else "NO_TRADE",
        "data_freshness": {"latest_hourly_bar": latest_time.isoformat()},
    })
    return _attach_context(result, quiver, flashalpha, finnhub)


def _asset_exclusion(asset: dict[str, Any], configuration: StockUniverseConfiguration) -> str | None:
    if str(asset.get("status") or "").casefold() != "active" or not asset.get("tradable", False): return "inactive_or_untradable"
    if str(asset.get("exchange") or "").upper() not in {"NASDAQ", "NYSE", "ARCA", "AMEX", "BATS"}: return "unsupported_exchange"
    symbol = str(asset.get("symbol") or "")
    if not symbol or len(symbol) > 12 or "/" in symbol: return "unsupported_symbol"
    if not configuration.include_leveraged and LEVERAGED_INVERSE_PATTERN.search(str(asset.get("name") or "")): return "leveraged_or_inverse"
    return None


def _rank_snapshot(asset: dict[str, Any], snapshot: dict[str, Any], configuration: StockUniverseConfiguration) -> tuple[StockCandidate | None, str | None]:
    daily = snapshot.get("dailyBar") if isinstance(snapshot.get("dailyBar"), dict) else {}
    previous = snapshot.get("prevDailyBar") if isinstance(snapshot.get("prevDailyBar"), dict) else {}
    quote = snapshot.get("latestQuote") if isinstance(snapshot.get("latestQuote"), dict) else {}
    price = _number(daily.get("c")) or _number(snapshot.get("latestTrade", {}).get("p") if isinstance(snapshot.get("latestTrade"), dict) else None)
    previous_close = _number(previous.get("c"))
    volume = _number(daily.get("v"))
    bid, ask = _number(quote.get("bp")), _number(quote.get("ap"))
    if price is None or previous_close is None or volume is None: return None, "missing_snapshot"
    if price < configuration.minimum_price: return None, "price_below_minimum"
    if bid is None or ask is None or ask < bid: return None, "invalid_quote"
    spread_bps = (ask - bid) / ((ask + bid) / 2) * 10_000
    if spread_bps > configuration.maximum_spread_bps: return None, "spread_too_wide"
    dollar_volume = price * volume
    if dollar_volume < configuration.minimum_daily_dollar_volume: return None, "liquidity_below_minimum"
    change = (price - previous_close) / previous_close * 100
    intraday_range = (_number(daily.get("h")) or price) - (_number(daily.get("l")) or price)
    range_pct = intraday_range / previous_close * 100
    side = "long" if change >= 0 else "short"
    score = abs(change) + min(range_pct, 10) * 0.25 + min(math.log10(max(dollar_volume, 1)) - 6, 4) * 0.2
    reasons = (f"daily change {change:+.2f}%", f"range {range_pct:.2f}%", f"dollar volume ${dollar_volume:,.0f}")
    return StockCandidate(str(asset["symbol"]).upper(), str(asset.get("name") or asset["symbol"]), side, score, price, spread_bps, dollar_volume, reasons), None


def _clean_bars(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if all(_number(row.get(key)) is not None for key in ("h", "l", "c"))]


def _ema(values: list[float], period: int) -> float:
    value, alpha = values[0], 2 / (period + 1)
    for item in values[1:]: value = item * alpha + value * (1 - alpha)
    return value


def _rsi(values: list[float], period: int) -> float:
    changes = [values[index] - values[index - 1] for index in range(len(values) - period, len(values))]
    gains = sum(max(change, 0) for change in changes) / period
    losses = sum(max(-change, 0) for change in changes) / period
    return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)


def _atr(rows: list[dict[str, Any]], period: int) -> float:
    values = []
    for index in range(len(rows) - period, len(rows)):
        high, low, previous_close = float(rows[index]["h"]), float(rows[index]["l"]), float(rows[index - 1]["c"])
        values.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return sum(values) / len(values)


def _bar_time(value: Any) -> datetime | None:
    if not isinstance(value, str): return None
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)): return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _flashalpha_bias(context: dict[str, Any]) -> str:
    price, flip = _number(context.get("underlying_price")), _number(context.get("gamma_flip"))
    if price is None or flip is None: return "unavailable"
    return "bullish" if price > flip else "bearish" if price < flip else "neutral"


def _earnings_imminent(context: dict[str, Any], now: datetime) -> bool:
    for row in context.get("earnings") or []:
        raw = row.get("date") if isinstance(row, dict) else None
        if not isinstance(raw, str): continue
        try: event = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        except ValueError: continue
        if now - timedelta(hours=12) <= event <= now + timedelta(days=2): return True
    return False


def _attach_context(result: dict[str, Any], quiver: dict[str, Any] | None, flashalpha: dict[str, Any] | None, finnhub: dict[str, Any] | None) -> dict[str, Any]:
    result["additional_context"] = {
        "quiver": quiver or {"source": "Quiver Quantitative", "available": False},
        "flashalpha": flashalpha or {"source": "FlashAlpha", "unavailable": True},
        "finnhub": finnhub or {"source": "Finnhub", "unavailable": True},
    }
    return result
