from __future__ import annotations

from statistics import mean, pstdev

from monatise.core.models import Candle
from monatise.engines.macro.models import MacroBias, MacroRiskState
from monatise.engines.market_data.models import DataStatus
from monatise.engines.regime.models import (
    RegimeAssessment,
    RegimeConfidence,
    RegimeRequest,
    RegimeState,
)


class RegimeEngine:
    """Classifies crypto market conditions before liquidity analysis."""

    def assess(self, request: RegimeRequest) -> RegimeAssessment:
        request.validate()
        market = request.market
        reasons: list[str] = []

        if market.quality.status is DataStatus.NO_DATA:
            return self._unknown(
                market.symbol,
                "market data unavailable",
            )

        if market.quality.status is DataStatus.DEGRADED:
            reasons.append("market data quality is degraded")

        candles = list(market.candles)
        required = max(
            # baseline_returns below needs slow_window elements out of the
            # len(candles)-1 -sized returns series, so slow_window+1 candles.
            request.slow_window + 1,
            request.atr_window + 1,
            request.compression_window + 1,
        )
        if len(candles) < required:
            return self._unknown(
                market.symbol,
                f"insufficient candles: required {required}, received {len(candles)}",
                reasons,
            )

        closes = [c.close for c in candles]
        fast_ma = mean(closes[-request.fast_window:])
        slow_ma = mean(closes[-request.slow_window:])
        last_close = closes[-1]

        returns = self._returns(closes)
        recent_returns = returns[-request.compression_window:]
        baseline_returns = returns[-request.slow_window:]

        recent_volatility = pstdev(recent_returns) if len(recent_returns) > 1 else 0.0
        baseline_volatility = pstdev(baseline_returns) if len(baseline_returns) > 1 else 0.0
        volatility_ratio = (
            recent_volatility / baseline_volatility
            if baseline_volatility > 0
            else None
        )

        atr = self._atr(candles[-(request.atr_window + 1):])
        atr_pct = atr / last_close if last_close > 0 else None

        slope = (fast_ma - slow_ma) / slow_ma if slow_ma else 0.0
        directional_efficiency = self._directional_efficiency(
            closes[-request.slow_window:]
        )

        state = self._classify(
            slope=slope,
            directional_efficiency=directional_efficiency,
            volatility_ratio=volatility_ratio,
            trend_threshold=request.trend_threshold,
            compression_threshold=request.compression_threshold,
            expansion_threshold=request.expansion_threshold,
            high_volatility_threshold=request.high_volatility_threshold,
        )

        if state is RegimeState.TREND_UP:
            reasons.append("fast average is materially above slow average")
        elif state is RegimeState.TREND_DOWN:
            reasons.append("fast average is materially below slow average")
        elif state is RegimeState.RANGE:
            reasons.append("directional efficiency is low and volatility is stable")
        elif state is RegimeState.COMPRESSION:
            reasons.append("recent volatility is materially below baseline")
        elif state is RegimeState.EXPANSION:
            reasons.append("recent volatility is expanding above baseline")
        elif state is RegimeState.HIGH_VOLATILITY:
            reasons.append("recent volatility is extremely elevated")
        else:
            reasons.append("market structure is internally unstable")

        macro_penalty = 0.0
        if request.macro is not None:
            if request.macro.risk_state is MacroRiskState.EVENT_LOCK:
                state = RegimeState.UNSTABLE
                macro_penalty += 0.45
                reasons.append("macro event lock forces unstable regime")
            elif request.macro.risk_state is MacroRiskState.DATA_UNAVAILABLE:
                macro_penalty += 0.25
                reasons.append("macro context unavailable")
            elif request.macro.risk_state is MacroRiskState.ELEVATED:
                macro_penalty += 0.15
                reasons.append("macro risk is elevated")

            if (
                state is RegimeState.TREND_UP
                and request.macro.bias is MacroBias.BEARISH
            ):
                macro_penalty += 0.15
                reasons.append("bullish price regime conflicts with bearish macro bias")
            elif (
                state is RegimeState.TREND_DOWN
                and request.macro.bias is MacroBias.BULLISH
            ):
                macro_penalty += 0.15
                reasons.append("bearish price regime conflicts with bullish macro bias")

        confidence_score = self._confidence_score(
            state=state,
            slope=slope,
            directional_efficiency=directional_efficiency,
            volatility_ratio=volatility_ratio,
            degraded=market.quality.status is DataStatus.DEGRADED,
            macro_penalty=macro_penalty,
        )
        confidence = self._confidence_label(confidence_score)

        return RegimeAssessment(
            symbol=market.symbol,
            state=state,
            confidence=confidence,
            score=confidence_score,
            reasons=tuple(reasons),
            metrics={
                "fast_ma": fast_ma,
                "slow_ma": slow_ma,
                "slope": slope,
                "directional_efficiency": directional_efficiency,
                "recent_volatility": recent_volatility,
                "baseline_volatility": baseline_volatility,
                "volatility_ratio": volatility_ratio,
                "atr": atr,
                "atr_pct": atr_pct,
            },
            metadata={
                "engine_scope": "crypto_only",
                "candle_count": len(candles),
                "fast_window": request.fast_window,
                "slow_window": request.slow_window,
                "atr_window": request.atr_window,
                "compression_window": request.compression_window,
            },
        )

    @staticmethod
    def _classify(
        *,
        slope: float,
        directional_efficiency: float,
        volatility_ratio: float | None,
        trend_threshold: float,
        compression_threshold: float,
        expansion_threshold: float,
        high_volatility_threshold: float,
    ) -> RegimeState:
        if volatility_ratio is None:
            return RegimeState.UNSTABLE
        if volatility_ratio >= high_volatility_threshold:
            return RegimeState.HIGH_VOLATILITY
        # A strong, efficient trend takes priority over expansion/compression —
        # a breakout with expanding volatility is still a trend, not
        # "expansion" (bug: EXPANSION was checked before the trend checks,
        # so a trending+expanding market was misclassified; COMPRESSION was
        # already correctly ordered after the trend checks below).
        if slope >= trend_threshold and directional_efficiency >= 0.35:
            return RegimeState.TREND_UP
        if slope <= -trend_threshold and directional_efficiency >= 0.35:
            return RegimeState.TREND_DOWN
        if volatility_ratio >= expansion_threshold:
            return RegimeState.EXPANSION
        if volatility_ratio <= compression_threshold:
            return RegimeState.COMPRESSION
        if abs(slope) < trend_threshold and directional_efficiency < 0.35:
            return RegimeState.RANGE
        return RegimeState.UNSTABLE

    @staticmethod
    def _returns(closes: list[float]) -> list[float]:
        result: list[float] = []
        for previous, current in zip(closes, closes[1:]):
            if previous <= 0:
                result.append(0.0)
            else:
                result.append((current - previous) / previous)
        return result

    @staticmethod
    def _atr(candles: list[Candle]) -> float:
        true_ranges: list[float] = []
        for previous, current in zip(candles, candles[1:]):
            true_range = max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
            true_ranges.append(true_range)
        return mean(true_ranges) if true_ranges else 0.0

    @staticmethod
    def _directional_efficiency(closes: list[float]) -> float:
        if len(closes) < 2:
            return 0.0
        net_change = abs(closes[-1] - closes[0])
        gross_change = sum(
            abs(current - previous)
            for previous, current in zip(closes, closes[1:])
        )
        if gross_change == 0:
            return 0.0
        return net_change / gross_change

    @staticmethod
    def _confidence_score(
        *,
        state: RegimeState,
        slope: float,
        directional_efficiency: float,
        volatility_ratio: float | None,
        degraded: bool,
        macro_penalty: float,
    ) -> float:
        if state is RegimeState.UNKNOWN:
            return 0.0

        score = 0.45
        if state in {RegimeState.TREND_UP, RegimeState.TREND_DOWN}:
            score += min(0.25, abs(slope) * 20)
            score += min(0.20, directional_efficiency * 0.30)
        elif state in {RegimeState.RANGE, RegimeState.COMPRESSION}:
            score += min(0.20, (1.0 - directional_efficiency) * 0.25)
            if volatility_ratio is not None:
                score += min(0.15, abs(1.0 - volatility_ratio) * 0.15)
        elif state in {RegimeState.EXPANSION, RegimeState.HIGH_VOLATILITY}:
            if volatility_ratio is not None:
                score += min(0.25, (volatility_ratio - 1.0) * 0.15)
        elif state is RegimeState.UNSTABLE:
            score -= 0.20

        if degraded:
            score -= 0.20
        score -= macro_penalty
        return round(max(0.0, min(1.0, score)), 4)

    @staticmethod
    def _confidence_label(score: float) -> RegimeConfidence:
        if score >= 0.75:
            return RegimeConfidence.HIGH
        if score >= 0.50:
            return RegimeConfidence.MEDIUM
        if score > 0:
            return RegimeConfidence.LOW
        return RegimeConfidence.NONE

    @staticmethod
    def _unknown(
        symbol: str,
        reason: str,
        prior_reasons: list[str] | None = None,
    ) -> RegimeAssessment:
        reasons = [*(prior_reasons or []), reason]
        return RegimeAssessment(
            symbol=symbol,
            state=RegimeState.UNKNOWN,
            confidence=RegimeConfidence.NONE,
            score=0.0,
            reasons=tuple(reasons),
            metadata={"engine_scope": "crypto_only"},
        )
