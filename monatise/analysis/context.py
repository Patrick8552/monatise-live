from __future__ import annotations

from dataclasses import dataclass
from math import log10

from monatise.core.models import Candle


@dataclass(frozen=True)
class IndicatorSnapshot:
    atr: float
    atr_pct: float
    choppiness: float
    ema_fast: float
    ema_slow: float
    rsi: float
    trend: str


def indicator_snapshot(candles: list[Candle]) -> IndicatorSnapshot:
    if len(candles) < 20:
        raise ValueError("at least 20 candles are required for context indicators")
    closes = [candle.close for candle in candles]
    atr = _atr(candles[-20:])
    mark = closes[-1]
    ema_fast = _ema(closes, 20)
    ema_slow = _ema(closes, min(50, len(closes)))
    return IndicatorSnapshot(
        atr=round(atr, 8),
        atr_pct=round(atr / mark, 8) if mark > 0 else 0.0,
        choppiness=round(_choppiness(candles[-20:]), 4),
        ema_fast=round(ema_fast, 8),
        ema_slow=round(ema_slow, 8),
        rsi=round(_rsi(closes[-15:]), 4),
        trend="up" if ema_fast > ema_slow else "down" if ema_fast < ema_slow else "flat",
    )


def grid_instruction(indicators: IndicatorSnapshot, event_risk: str = "normal") -> dict:
    reasons: list[str] = []
    action = "normal"
    if event_risk == "elevated":
        action = "reduce"
        reasons.append("scheduled or macro context risk is elevated")
    if indicators.atr_pct >= 0.025:
        action = "pause" if indicators.choppiness < 38 else "widen"
        reasons.append("ATR is elevated")
    elif indicators.atr_pct >= 0.012:
        action = "widen" if action == "normal" else action
        reasons.append("volatility is above baseline")
    if indicators.choppiness < 35:
        action = "pause" if action in {"normal", "widen"} else action
        reasons.append("market is trending more than ranging")
    elif indicators.choppiness < 45 and action == "normal":
        action = "reduce"
        reasons.append("range quality is only moderate")
    if indicators.rsi >= 72 or indicators.rsi <= 28:
        action = "reduce" if action == "normal" else action
        reasons.append("momentum is stretched")
    if not reasons:
        reasons.append("volatility and range quality are acceptable for grid planning")
    spacing_multiplier = {
        "normal": 1.0,
        "widen": 1.6,
        "reduce": 1.25,
        "pause": 0.0,
    }[action]
    size_multiplier = {
        "normal": 1.0,
        "widen": 0.75,
        "reduce": 0.5,
        "pause": 0.0,
    }[action]
    return {
        "action": action,
        "reasons": reasons,
        "spacingMultiplier": spacing_multiplier,
        "sizeMultiplier": size_multiplier,
    }


def context_assets(symbol: str, prices: dict[str, float]) -> list[dict]:
    symbol = symbol.upper()
    if symbol == "GOLD":
        watch = [
            ("GOLD", "Gold mark"),
            ("XAG", "Silver confirmation"),
            ("xyz:COPPER", "Copper growth proxy"),
            ("SPX", "Risk proxy"),
            ("DXY", "Dollar index"),
            ("US10Y_REAL", "10Y real yield"),
        ]
    elif symbol in {"CL", "BRENTOIL"}:
        watch = [
            ("CL", "WTI crude"),
            ("BRENTOIL", "Brent crude"),
            ("xyz:COPPER", "Industrial demand proxy"),
            ("DXY", "Dollar index"),
            ("EIA_WPSR", "EIA weekly petroleum status"),
            ("OPEC", "OPEC headline/calendar risk"),
        ]
    else:
        watch = [
            (symbol, "Selected market"),
            ("BTC", "Crypto beta"),
            ("ETH", "Crypto beta"),
            ("HYPE", "Venue beta"),
        ]
    return [
        {
            "symbol": item,
            "label": label,
            "price": prices.get(item),
            "available": item in prices,
        }
        for item, label in watch
    ]


def _ema(values: list[float], period: int) -> float:
    alpha = 2 / (period + 1)
    ema = values[0]
    for value in values[1:]:
        ema = (value * alpha) + (ema * (1 - alpha))
    return ema


def _rsi(values: list[float]) -> float:
    gains = 0.0
    losses = 0.0
    for previous, current in zip(values, values[1:]):
        change = current - previous
        if change >= 0:
            gains += change
        else:
            losses += abs(change)
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))


def _true_ranges(candles: list[Candle]) -> list[float]:
    ranges = []
    previous_close = candles[0].close
    for candle in candles:
        ranges.append(max(candle.high - candle.low, abs(candle.high - previous_close), abs(candle.low - previous_close)))
        previous_close = candle.close
    return ranges


def _atr(candles: list[Candle]) -> float:
    ranges = _true_ranges(candles)
    return sum(ranges) / len(ranges)


def _choppiness(candles: list[Candle]) -> float:
    ranges = _true_ranges(candles)
    high = max(candle.high for candle in candles)
    low = min(candle.low for candle in candles)
    span = high - low
    if span <= 0 or len(candles) <= 1:
        return 100.0
    return 100 * log10(sum(ranges) / span) / log10(len(candles))
