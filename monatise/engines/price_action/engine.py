from __future__ import annotations

from monatise.core.models import Candle
from monatise.engines.price_action.models import (
    PriceActionAssessment,
    PriceActionDirection,
    PriceActionFamily,
    PriceActionRequest,
    PriceActionSignal,
)


class PriceActionEngine:
    """Detect confirmation candidates without creating entries or orders."""

    def assess(self, request: PriceActionRequest) -> PriceActionAssessment:
        request.validate()
        candles = request.market.candles
        if len(candles) < request.minimum_candles:
            return PriceActionAssessment(
                request.market.symbol,
                (),
                ("insufficient candles for price-action confirmation",),
            )

        signals = (
            *self._candlestick(candles),
            *self._head_and_shoulders(candles),
            *self._order_blocks(candles),
            *self._wyckoff(candles),
        )
        reasons = (
            tuple(f"{signal.family.value}: {signal.pattern}" for signal in signals)
            if signals
            else ("no registered price-action pattern is confirmed",)
        )
        return PriceActionAssessment(request.market.symbol, tuple(signals), reasons)

    @staticmethod
    def _candlestick(candles: tuple[Candle, ...]) -> tuple[PriceActionSignal, ...]:
        previous, latest = candles[-2], candles[-1]
        output: list[PriceActionSignal] = []
        if previous.close < previous.open and latest.close > latest.open and latest.open <= previous.close and latest.close >= previous.open:
            output.append(PriceActionSignal(PriceActionFamily.CANDLESTICK, "bullish_engulfing", PriceActionDirection.BULLISH, 0.78, True, "bullish body engulfed the prior bearish body"))
        if previous.close > previous.open and latest.close < latest.open and latest.open >= previous.close and latest.close <= previous.open:
            output.append(PriceActionSignal(PriceActionFamily.CANDLESTICK, "bearish_engulfing", PriceActionDirection.BEARISH, 0.78, True, "bearish body engulfed the prior bullish body"))
        span = latest.high - latest.low
        body = abs(latest.close - latest.open)
        if span > 0 and body / span <= 0.35:
            lower_wick = min(latest.open, latest.close) - latest.low
            upper_wick = latest.high - max(latest.open, latest.close)
            if lower_wick >= body * 2 and upper_wick <= max(body, span * 0.15):
                output.append(PriceActionSignal(PriceActionFamily.CANDLESTICK, "hammer", PriceActionDirection.BULLISH, 0.68, True, "long lower wick rejected lower prices"))
            elif upper_wick >= body * 2 and lower_wick <= max(body, span * 0.15):
                output.append(PriceActionSignal(PriceActionFamily.CANDLESTICK, "shooting_star", PriceActionDirection.BEARISH, 0.68, True, "long upper wick rejected higher prices"))
        return tuple(output)

    @staticmethod
    def _head_and_shoulders(candles: tuple[Candle, ...]) -> tuple[PriceActionSignal, ...]:
        sample = candles[-31:]
        highs = [(i, sample[i].high) for i in range(1, len(sample) - 1) if sample[i].high > sample[i - 1].high and sample[i].high >= sample[i + 1].high]
        lows = [(i, sample[i].low) for i in range(1, len(sample) - 1) if sample[i].low < sample[i - 1].low and sample[i].low <= sample[i + 1].low]
        output: list[PriceActionSignal] = []
        if len(highs) >= 3:
            left, head, right = highs[-3:]
            shoulders_close = abs(left[1] - right[1]) / max(left[1], right[1]) <= 0.03
            neckline = min(c.low for c in sample[left[0]: right[0] + 1])
            if shoulders_close and head[1] > max(left[1], right[1]) * 1.005 and sample[-1].close < neckline:
                output.append(PriceActionSignal(PriceActionFamily.HEAD_AND_SHOULDERS, "head_and_shoulders_breakdown", PriceActionDirection.BEARISH, 0.82, True, "three-peak reversal closed below its neckline", {"neckline": neckline}))
        if len(lows) >= 3:
            left, head, right = lows[-3:]
            shoulders_close = abs(left[1] - right[1]) / max(left[1], right[1]) <= 0.03
            neckline = max(c.high for c in sample[left[0]: right[0] + 1])
            if shoulders_close and head[1] < min(left[1], right[1]) * 0.995 and sample[-1].close > neckline:
                output.append(PriceActionSignal(PriceActionFamily.HEAD_AND_SHOULDERS, "inverse_head_and_shoulders_breakout", PriceActionDirection.BULLISH, 0.82, True, "three-trough reversal closed above its neckline", {"neckline": neckline}))
        return tuple(output)

    @staticmethod
    def _order_blocks(candles: tuple[Candle, ...]) -> tuple[PriceActionSignal, ...]:
        recent = candles[-8:]
        output: list[PriceActionSignal] = []
        for index in range(len(recent) - 3, -1, -1):
            anchor = recent[index]
            follow = recent[index + 1:index + 4]
            if len(follow) < 2:
                continue
            anchor_span = max(anchor.high - anchor.low, 1e-12)
            if anchor.close < anchor.open and max(c.close for c in follow) > anchor.high + anchor_span * 0.5:
                held = recent[-1].close >= anchor.low
                if held:
                    output.append(PriceActionSignal(PriceActionFamily.ORDER_BLOCK, "bullish_order_block", PriceActionDirection.BULLISH, 0.72, True, "last bearish candle preceded bullish displacement and its zone held", {"low": anchor.low, "high": anchor.high}))
                    break
            if anchor.close > anchor.open and min(c.close for c in follow) < anchor.low - anchor_span * 0.5:
                held = recent[-1].close <= anchor.high
                if held:
                    output.append(PriceActionSignal(PriceActionFamily.ORDER_BLOCK, "bearish_order_block", PriceActionDirection.BEARISH, 0.72, True, "last bullish candle preceded bearish displacement and its zone held", {"low": anchor.low, "high": anchor.high}))
                    break
        return tuple(output)

    @staticmethod
    def _wyckoff(candles: tuple[Candle, ...]) -> tuple[PriceActionSignal, ...]:
        prior, latest = candles[-21:-1], candles[-1]
        if len(prior) < 7:
            return ()
        range_low = min(c.low for c in prior)
        range_high = max(c.high for c in prior)
        average_volume = sum(c.volume for c in prior) / len(prior)
        volume_confirmed = average_volume <= 0 or latest.volume >= average_volume
        if latest.low < range_low and latest.close > range_low and volume_confirmed:
            return (PriceActionSignal(PriceActionFamily.WYCKOFF, "spring", PriceActionDirection.BULLISH, 0.80, True, "sell-side range break reclaimed on confirming volume", {"range_low": range_low}),)
        if latest.high > range_high and latest.close < range_high and volume_confirmed:
            return (PriceActionSignal(PriceActionFamily.WYCKOFF, "upthrust", PriceActionDirection.BEARISH, 0.80, True, "buy-side range break rejected on confirming volume", {"range_high": range_high}),)
        return ()
