from __future__ import annotations

from dataclasses import asdict, dataclass

from monatise.core.models import Candle


@dataclass(frozen=True)
class FairValueGap:
    direction: str
    start_time: str
    middle_time: str
    end_time: str
    low: float
    high: float
    midpoint: float
    size: float
    size_pct: float
    filled: bool
    distance_to_mark: float


@dataclass(frozen=True)
class FvgAnalysis:
    symbol: str
    interval: str
    candle_count: int
    mark: float
    bias: str
    active_count: int
    nearest_gap: FairValueGap | None
    gaps: list[FairValueGap]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["nearest_gap"] = asdict(self.nearest_gap) if self.nearest_gap else None
        payload["gaps"] = [asdict(gap) for gap in self.gaps]
        return payload


def analyze_fvg(
    symbol: str,
    interval: str,
    candles: list[Candle],
    mark: float | None = None,
    *,
    max_gaps: int = 12,
) -> FvgAnalysis:
    if len(candles) < 3:
        raise ValueError("at least 3 candles are required for FVG analysis")

    current_mark = float(mark if mark is not None else candles[-1].close)
    gaps: list[FairValueGap] = []
    for index in range(2, len(candles)):
        first = candles[index - 2]
        middle = candles[index - 1]
        third = candles[index]
        if first.high < third.low:
            gaps.append(
                _build_gap(
                    "bullish",
                    first,
                    middle,
                    third,
                    low=first.high,
                    high=third.low,
                    mark=current_mark,
                    filled=_gap_filled("bullish", first.high, third.low, candles[index + 1 :]),
                )
            )
        if first.low > third.high:
            gaps.append(
                _build_gap(
                    "bearish",
                    first,
                    middle,
                    third,
                    low=third.high,
                    high=first.low,
                    mark=current_mark,
                    filled=_gap_filled("bearish", third.high, first.low, candles[index + 1 :]),
                )
            )

    active_gaps = [gap for gap in gaps if not gap.filled]
    nearest_gap = min(active_gaps, key=lambda gap: gap.distance_to_mark, default=None)
    selected_gaps = sorted(active_gaps, key=lambda gap: gap.distance_to_mark)[:max_gaps]
    return FvgAnalysis(
        symbol=symbol,
        interval=interval,
        candle_count=len(candles),
        mark=round(current_mark, 8),
        bias=nearest_gap.direction if nearest_gap else "balanced",
        active_count=len(active_gaps),
        nearest_gap=nearest_gap,
        gaps=selected_gaps,
    )


def _build_gap(
    direction: str,
    first: Candle,
    middle: Candle,
    third: Candle,
    *,
    low: float,
    high: float,
    mark: float,
    filled: bool,
) -> FairValueGap:
    midpoint = (low + high) / 2
    size = high - low
    distance = _distance_to_range(mark, low, high)
    return FairValueGap(
        direction=direction,
        start_time=first.timestamp,
        middle_time=middle.timestamp,
        end_time=third.timestamp,
        low=round(low, 8),
        high=round(high, 8),
        midpoint=round(midpoint, 8),
        size=round(size, 8),
        size_pct=round(size / midpoint * 100, 4) if midpoint else 0.0,
        filled=filled,
        distance_to_mark=round(distance, 8),
    )


def _gap_filled(direction: str, low: float, high: float, later_candles: list[Candle]) -> bool:
    if direction == "bullish":
        return any(candle.low <= low for candle in later_candles)
    return any(candle.high >= high for candle in later_candles)


def _distance_to_range(mark: float, low: float, high: float) -> float:
    if low <= mark <= high:
        return 0.0
    return min(abs(mark - low), abs(mark - high))
