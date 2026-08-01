from __future__ import annotations

from statistics import mean

from monatise.engines.market_data.models import DataStatus
from monatise.engines.market_structure.models import StructureBias
from monatise.engines.regime.models import RegimeState
from monatise.engines.rsi.models import (
    RSIAssessment,
    RSIBias,
    RSICondition,
    RSIDivergence,
    RSIRequest,
)


class RSIEngine:
    """Crypto RSI momentum and divergence intelligence engine.

    RSI is used as confluence only. Overbought does not automatically mean
    short, and oversold does not automatically mean long.
    """

    def assess(self, request: RSIRequest) -> RSIAssessment:
        request.validate()
        market = request.market
        reasons: list[str] = []

        if market.quality.status is DataStatus.NO_DATA:
            return self._unavailable(market.symbol, "market data unavailable")

        closes = [candle.close for candle in market.candles]
        minimum = max(
            request.period + 2,
            request.divergence_lookback,
            request.swing_window * 2 + 3,
        )
        if len(closes) < minimum:
            return self._unavailable(
                market.symbol,
                f"insufficient candles: required {minimum}, received {len(closes)}",
            )

        if market.quality.status is DataStatus.DEGRADED:
            reasons.append("RSI calculated from degraded market data")

        series = self._rsi_series(closes, request.period)
        current = series[-1]
        previous = next(
            (value for value in reversed(series[:-1]) if value is not None),
            None,
        )

        if current is None:
            return self._unavailable(market.symbol, "RSI calculation unavailable")

        condition = self._condition(current, request)
        divergence = self._divergence(
            closes=closes,
            rsi=series,
            lookback=request.divergence_lookback,
            swing_window=request.swing_window,
            minimum_separation=request.minimum_divergence_separation,
        )

        bias = self._bias(
            current=current,
            previous=previous,
            divergence=divergence,
            structure=request.structure,
        )

        confidence = self._confidence(
            current=current,
            previous=previous,
            divergence=divergence,
            bias=bias,
            request=request,
        )

        if condition is RSICondition.OVERBOUGHT:
            reasons.append("RSI is overbought; this is not a standalone short signal")
        elif condition is RSICondition.OVERSOLD:
            reasons.append("RSI is oversold; this is not a standalone long signal")
        else:
            reasons.append(f"RSI condition is {condition.value}")

        if divergence is not RSIDivergence.NONE:
            reasons.append(f"detected {divergence.value}")

        if request.structure is not None:
            if (
                bias is RSIBias.BULLISH
                and request.structure.bias is StructureBias.BULLISH
            ):
                reasons.append("RSI aligns with bullish market structure")
            elif (
                bias is RSIBias.BEARISH
                and request.structure.bias is StructureBias.BEARISH
            ):
                reasons.append("RSI aligns with bearish market structure")
            elif request.structure.bias in {
                StructureBias.BULLISH,
                StructureBias.BEARISH,
            }:
                reasons.append("RSI conflicts with market structure")

        if request.regime is not None and request.regime.state in {
            RegimeState.UNKNOWN,
            RegimeState.UNSTABLE,
        }:
            confidence = max(0.0, confidence - 0.25)
            reasons.append("unstable regime reduces RSI reliability")

        return RSIAssessment(
            symbol=market.symbol,
            current_rsi=round(current, 4),
            previous_rsi=round(previous, 4) if previous is not None else None,
            condition=condition,
            bias=bias,
            divergence=divergence,
            confidence=round(confidence, 4),
            rsi_series=tuple(
                round(value, 4) if value is not None else None
                for value in series
            ),
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "period": request.period,
                "overbought": request.overbought,
                "oversold": request.oversold,
                "standalone_trigger": False,
            },
        )

    @staticmethod
    def _rsi_series(closes: list[float], period: int) -> list[float | None]:
        result: list[float | None] = [None] * len(closes)
        changes = [
            current - previous
            for previous, current in zip(closes, closes[1:])
        ]

        if len(changes) < period:
            return result

        gains = [max(change, 0.0) for change in changes]
        losses = [max(-change, 0.0) for change in changes]

        average_gain = mean(gains[:period])
        average_loss = mean(losses[:period])
        result[period] = RSIEngine._rsi_value(average_gain, average_loss)

        for index in range(period, len(changes)):
            average_gain = (
                average_gain * (period - 1) + gains[index]
            ) / period
            average_loss = (
                average_loss * (period - 1) + losses[index]
            ) / period
            result[index + 1] = RSIEngine._rsi_value(
                average_gain,
                average_loss,
            )

        return result

    @staticmethod
    def _rsi_value(average_gain: float, average_loss: float) -> float:
        if average_loss == 0 and average_gain == 0:
            return 50.0
        if average_loss == 0:
            return 100.0
        relative_strength = average_gain / average_loss
        return 100.0 - (100.0 / (1.0 + relative_strength))

    @staticmethod
    def _condition(current: float, request: RSIRequest) -> RSICondition:
        if current >= request.overbought:
            return RSICondition.OVERBOUGHT
        if current <= request.oversold:
            return RSICondition.OVERSOLD
        if current >= request.bullish_momentum:
            return RSICondition.BULLISH_MOMENTUM
        if current <= request.bearish_momentum:
            return RSICondition.BEARISH_MOMENTUM
        return RSICondition.NEUTRAL

    @staticmethod
    def _bias(
        *,
        current: float,
        previous: float | None,
        divergence: RSIDivergence,
        structure,
    ) -> RSIBias:
        if divergence in {
            RSIDivergence.REGULAR_BULLISH,
            RSIDivergence.HIDDEN_BULLISH,
        }:
            return RSIBias.BULLISH
        if divergence in {
            RSIDivergence.REGULAR_BEARISH,
            RSIDivergence.HIDDEN_BEARISH,
        }:
            return RSIBias.BEARISH

        rising = previous is not None and current > previous
        falling = previous is not None and current < previous

        if current > 50 and rising:
            return RSIBias.BULLISH
        if current < 50 and falling:
            return RSIBias.BEARISH
        if 47 <= current <= 53:
            return RSIBias.NEUTRAL

        if structure is not None:
            if current > 50 and structure.bias is StructureBias.BULLISH:
                return RSIBias.BULLISH
            if current < 50 and structure.bias is StructureBias.BEARISH:
                return RSIBias.BEARISH

        return RSIBias.CONFLICTED

    @staticmethod
    def _divergence(
        *,
        closes: list[float],
        rsi: list[float | None],
        lookback: int,
        swing_window: int,
        minimum_separation: int,
    ) -> RSIDivergence:
        start = max(0, len(closes) - lookback)
        price_lows = RSIEngine._swing_indices(
            closes,
            start,
            swing_window,
            low=True,
        )
        price_highs = RSIEngine._swing_indices(
            closes,
            start,
            swing_window,
            low=False,
        )

        valid_lows = [
            index for index in price_lows
            if rsi[index] is not None
        ]
        valid_highs = [
            index for index in price_highs
            if rsi[index] is not None
        ]

        if len(valid_lows) >= 2:
            first, second = valid_lows[-2], valid_lows[-1]
            if second - first >= minimum_separation:
                if closes[second] < closes[first] and rsi[second] > rsi[first]:
                    return RSIDivergence.REGULAR_BULLISH
                if closes[second] > closes[first] and rsi[second] < rsi[first]:
                    return RSIDivergence.HIDDEN_BULLISH

        if len(valid_highs) >= 2:
            first, second = valid_highs[-2], valid_highs[-1]
            if second - first >= minimum_separation:
                if closes[second] > closes[first] and rsi[second] < rsi[first]:
                    return RSIDivergence.REGULAR_BEARISH
                if closes[second] < closes[first] and rsi[second] > rsi[first]:
                    return RSIDivergence.HIDDEN_BEARISH

        return RSIDivergence.NONE

    @staticmethod
    def _swing_indices(
        values: list[float],
        start: int,
        window: int,
        *,
        low: bool,
    ) -> list[int]:
        result: list[int] = []
        for index in range(
            max(start + window, window),
            len(values) - window,
        ):
            neighbours = (
                values[index - window:index]
                + values[index + 1:index + 1 + window]
            )
            if low and all(values[index] < value for value in neighbours):
                result.append(index)
            elif not low and all(values[index] > value for value in neighbours):
                result.append(index)
        return result

    @staticmethod
    def _confidence(
        *,
        current: float,
        previous: float | None,
        divergence: RSIDivergence,
        bias: RSIBias,
        request: RSIRequest,
    ) -> float:
        if bias is RSIBias.UNKNOWN:
            return 0.0

        score = 0.35

        if divergence is not RSIDivergence.NONE:
            score += 0.30

        if previous is not None:
            momentum_change = abs(current - previous)
            score += min(0.15, momentum_change / 20)

        distance_from_midline = abs(current - 50)
        score += min(0.15, distance_from_midline / 100)

        if current >= request.overbought or current <= request.oversold:
            score += 0.05

        return min(1.0, score)

    @staticmethod
    def _unavailable(symbol: str, reason: str) -> RSIAssessment:
        return RSIAssessment(
            symbol=symbol,
            current_rsi=None,
            previous_rsi=None,
            condition=RSICondition.UNAVAILABLE,
            bias=RSIBias.UNKNOWN,
            divergence=RSIDivergence.UNKNOWN,
            confidence=0.0,
            rsi_series=(),
            reasons=(reason,),
            metadata={
                "engine_scope": "crypto_only",
                "standalone_trigger": False,
            },
        )
