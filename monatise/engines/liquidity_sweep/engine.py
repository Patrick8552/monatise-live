from __future__ import annotations

from monatise.core.models import Candle
from monatise.engines.liquidity.models import LiquiditySide
from monatise.engines.liquidity_sweep.models import (
    SweepAssessment,
    SweepDirection,
    SweepEvent,
    SweepRequest,
    SweepStatus,
)
from monatise.engines.market_data.models import DataStatus
from monatise.engines.regime.models import RegimeState


class LiquiditySweepEngine:
    """Detects whether mapped liquidity was breached and rejected.

    This engine does not create entries, stops, targets, or trade decisions.
    """

    def assess(self, request: SweepRequest) -> SweepAssessment:
        request.validate()
        market = request.market
        liquidity = request.liquidity
        reasons: list[str] = []

        if market.quality.status is DataStatus.NO_DATA:
            return SweepAssessment(
                symbol=market.symbol,
                events=(),
                strongest_event=None,
                reasons=("market data unavailable",),
                metadata={"engine_scope": "crypto_only"},
            )

        if market.symbol != liquidity.symbol:
            return SweepAssessment(
                symbol=market.symbol,
                events=(),
                strongest_event=None,
                reasons=("market and liquidity symbols do not match",),
                metadata={"engine_scope": "crypto_only"},
            )

        candles = list(market.candles)
        if not candles:
            return SweepAssessment(
                symbol=market.symbol,
                events=(),
                strongest_event=None,
                reasons=("no candles available",),
                metadata={"engine_scope": "crypto_only"},
            )

        if market.quality.status is DataStatus.DEGRADED:
            reasons.append("sweep analysis uses degraded market data")

        if request.regime is not None and request.regime.state in {
            RegimeState.UNKNOWN,
            RegimeState.UNSTABLE,
        }:
            reasons.append(
                f"regime is {request.regime.state.value}; sweep result is informational only"
            )

        start_index = max(0, len(candles) - request.lookback_candles)
        recent = list(enumerate(candles[start_index:], start=start_index))

        events: list[SweepEvent] = []
        for level in liquidity.buy_side_levels:
            event = self._detect_buy_side_sweep(
                recent,
                level,
                request,
            )
            if event is not None:
                events.append(event)

        for level in liquidity.sell_side_levels:
            event = self._detect_sell_side_sweep(
                recent,
                level,
                request,
            )
            if event is not None:
                events.append(event)

        events.sort(
            key=lambda event: (
                self._status_priority(event.status),
                event.breach_pct,
                event.wick_ratio,
                event.candle_index,
            ),
            reverse=True,
        )

        strongest = events[0] if events else None
        if strongest is None:
            reasons.append("no mapped liquidity level was breached")
        elif strongest.status is SweepStatus.CONFIRMED:
            reasons.append("confirmed liquidity sweep detected")
        elif strongest.status is SweepStatus.POSSIBLE:
            reasons.append("possible sweep detected without full confirmation")

        return SweepAssessment(
            symbol=market.symbol,
            events=tuple(events),
            strongest_event=strongest,
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "lookback_candles": request.lookback_candles,
                "levels_checked": (
                    len(liquidity.buy_side_levels)
                    + len(liquidity.sell_side_levels)
                ),
            },
        )

    def _detect_buy_side_sweep(
        self,
        recent: list[tuple[int, Candle]],
        level,
        request: SweepRequest,
    ) -> SweepEvent | None:
        if level.side is not LiquiditySide.BUY_SIDE:
            return None

        best: SweepEvent | None = None
        threshold = level.price * (1 + request.breach_tolerance_pct)

        for index, candle in recent:
            if candle.high < threshold:
                continue

            breach_pct = (candle.high - level.price) / level.price
            upper_wick = candle.high - max(candle.open, candle.close)
            candle_range = candle.high - candle.low
            wick_ratio = upper_wick / candle_range if candle_range > 0 else 0.0
            close_limit = level.price * (1 + request.rejection_close_pct)
            close_back_inside = candle.close <= close_limit

            status, event_reasons = self._status(
                wick_ratio=wick_ratio,
                close_back_inside=close_back_inside,
                require_close_back_inside=request.require_close_back_inside,
                minimum_wick_ratio=request.minimum_wick_ratio,
            )

            event = SweepEvent(
                level=level,
                direction=SweepDirection.BUY_SIDE_TAKEN,
                status=status,
                candle_index=index,
                breach_price=candle.high,
                close_price=candle.close,
                breach_pct=breach_pct,
                wick_ratio=wick_ratio,
                close_back_inside=close_back_inside,
                reasons=event_reasons,
            )
            best = self._stronger(best, event)

        return best

    def _detect_sell_side_sweep(
        self,
        recent: list[tuple[int, Candle]],
        level,
        request: SweepRequest,
    ) -> SweepEvent | None:
        if level.side is not LiquiditySide.SELL_SIDE:
            return None

        best: SweepEvent | None = None
        threshold = level.price * (1 - request.breach_tolerance_pct)

        for index, candle in recent:
            if candle.low > threshold:
                continue

            breach_pct = (level.price - candle.low) / level.price
            lower_wick = min(candle.open, candle.close) - candle.low
            candle_range = candle.high - candle.low
            wick_ratio = lower_wick / candle_range if candle_range > 0 else 0.0
            close_limit = level.price * (1 - request.rejection_close_pct)
            close_back_inside = candle.close >= close_limit

            status, event_reasons = self._status(
                wick_ratio=wick_ratio,
                close_back_inside=close_back_inside,
                require_close_back_inside=request.require_close_back_inside,
                minimum_wick_ratio=request.minimum_wick_ratio,
            )

            event = SweepEvent(
                level=level,
                direction=SweepDirection.SELL_SIDE_TAKEN,
                status=status,
                candle_index=index,
                breach_price=candle.low,
                close_price=candle.close,
                breach_pct=breach_pct,
                wick_ratio=wick_ratio,
                close_back_inside=close_back_inside,
                reasons=event_reasons,
            )
            best = self._stronger(best, event)

        return best

    @staticmethod
    def _status(
        *,
        wick_ratio: float,
        close_back_inside: bool,
        require_close_back_inside: bool,
        minimum_wick_ratio: float,
    ) -> tuple[SweepStatus, tuple[str, ...]]:
        reasons: list[str] = []

        wick_ok = wick_ratio >= minimum_wick_ratio
        if wick_ok:
            reasons.append("rejection wick meets minimum ratio")
        else:
            reasons.append("rejection wick is too small")

        if close_back_inside:
            reasons.append("candle closed back inside the liquidity level")
        else:
            reasons.append("candle did not close back inside the liquidity level")

        if wick_ok and (close_back_inside or not require_close_back_inside):
            return SweepStatus.CONFIRMED, tuple(reasons)
        if wick_ok or close_back_inside:
            return SweepStatus.POSSIBLE, tuple(reasons)
        return SweepStatus.INVALID, tuple(reasons)

    @classmethod
    def _stronger(
        cls,
        current: SweepEvent | None,
        candidate: SweepEvent,
    ) -> SweepEvent:
        if current is None:
            return candidate
        current_key = (
            cls._status_priority(current.status),
            current.wick_ratio,
            current.breach_pct,
            current.candle_index,
        )
        candidate_key = (
            cls._status_priority(candidate.status),
            candidate.wick_ratio,
            candidate.breach_pct,
            candidate.candle_index,
        )
        return candidate if candidate_key > current_key else current

    @staticmethod
    def _status_priority(status: SweepStatus) -> int:
        return {
            SweepStatus.CONFIRMED: 3,
            SweepStatus.POSSIBLE: 2,
            SweepStatus.INVALID: 1,
            SweepStatus.NONE: 0,
        }[status]
