from __future__ import annotations

from dataclasses import asdict, dataclass

from monatise.core.models import Candle


RETRACEMENTS = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTENSIONS = (1.272, 1.618)


@dataclass(frozen=True)
class FibonacciLevel:
    label: str
    ratio: float
    price: float
    kind: str


@dataclass(frozen=True)
class FibonacciAnalysis:
    symbol: str
    interval: str
    candle_count: int
    swing_high: float
    swing_high_time: str
    swing_low: float
    swing_low_time: str
    trend: str
    mark: float
    nearest_level: FibonacciLevel
    grid_floor: float
    grid_ceiling: float
    invalidation: float
    levels: list[FibonacciLevel]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["nearest_level"] = asdict(self.nearest_level)
        payload["levels"] = [asdict(level) for level in self.levels]
        return payload


def analyze_fibonacci(symbol: str, interval: str, candles: list[Candle], mark: float | None = None) -> FibonacciAnalysis:
    if len(candles) < 5:
        raise ValueError("at least 5 candles are required for Fibonacci analysis")

    high_candle = max(candles, key=lambda candle: candle.high)
    low_candle = min(candles, key=lambda candle: candle.low)
    swing_high = high_candle.high
    swing_low = low_candle.low
    span = swing_high - swing_low
    if span <= 0:
        raise ValueError("candle range is too flat for Fibonacci analysis")

    trend = "up" if candles[-1].close >= candles[0].close else "down"
    current_mark = float(mark if mark is not None else candles[-1].close)

    if trend == "up":
        levels = [
            FibonacciLevel(f"{ratio:.3f}", ratio, swing_high - (span * ratio), "retracement")
            for ratio in RETRACEMENTS
        ]
        levels.extend(
            FibonacciLevel(f"{ratio:.3f}", ratio, swing_low + (span * ratio), "extension")
            for ratio in EXTENSIONS
        )
        grid_floor = swing_high - (span * 0.786)
        grid_ceiling = swing_low + (span * 1.272)
        invalidation = swing_low
    else:
        levels = [
            FibonacciLevel(f"{ratio:.3f}", ratio, swing_low + (span * ratio), "retracement")
            for ratio in RETRACEMENTS
        ]
        levels.extend(
            FibonacciLevel(f"{ratio:.3f}", ratio, swing_high - (span * ratio), "extension")
            for ratio in EXTENSIONS
        )
        grid_floor = swing_high - (span * 1.272)
        grid_ceiling = swing_low + (span * 0.786)
        invalidation = swing_high

    ordered_levels = sorted(levels, key=lambda level: level.price)
    nearest = min(ordered_levels, key=lambda level: abs(level.price - current_mark))
    return FibonacciAnalysis(
        symbol=symbol,
        interval=interval,
        candle_count=len(candles),
        swing_high=round(swing_high, 8),
        swing_high_time=high_candle.timestamp,
        swing_low=round(swing_low, 8),
        swing_low_time=low_candle.timestamp,
        trend=trend,
        mark=round(current_mark, 8),
        nearest_level=FibonacciLevel(nearest.label, nearest.ratio, round(nearest.price, 8), nearest.kind),
        grid_floor=round(min(grid_floor, grid_ceiling), 8),
        grid_ceiling=round(max(grid_floor, grid_ceiling), 8),
        invalidation=round(invalidation, 8),
        levels=[
            FibonacciLevel(level.label, level.ratio, round(level.price, 8), level.kind)
            for level in ordered_levels
        ],
    )
