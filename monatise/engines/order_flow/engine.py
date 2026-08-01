from __future__ import annotations

from dataclasses import fields
from math import isfinite

from monatise.engines.market_structure.models import StructureBias
from monatise.engines.order_flow.models import (
    FlowBias,
    FlowConfidence,
    FlowHealth,
    FlowInput,
    OrderFlowAssessment,
    OrderFlowRequest,
    ParticipationState,
)
from monatise.engines.regime.models import RegimeState


class OrderFlowIntelligenceEngine:
    """Interprets crypto order flow and institutional participation.

    Responsibilities:
    1. Institutional Participation Analysis
    2. Market State Enhancement
    3. Execution Timing
    4. Trade Health Monitoring

    This engine does not create entries, stops, targets, grids, or orders.
    """

    def assess(self, request: OrderFlowRequest) -> OrderFlowAssessment:
        request.validate()
        reasons: list[str] = []

        values = self._normalize(request.flow, reasons)
        inputs_used = sum(value is not None for value in values.values())

        if inputs_used < request.minimum_inputs:
            return OrderFlowAssessment(
                symbol=request.symbol.upper(),
                bias=FlowBias.UNKNOWN,
                participation=ParticipationState.UNKNOWN,
                health=FlowHealth.UNAVAILABLE,
                confidence=FlowConfidence.NONE,
                score=0.0,
                execution_timing_score=0.0,
                inputs_used=inputs_used,
                reasons=tuple([
                    *reasons,
                    f"insufficient order-flow inputs: required {request.minimum_inputs}, received {inputs_used}",
                ]),
                normalized_inputs=values,
                metadata={"engine_scope": "crypto_only"},
            )

        participation = self._participation(values)
        bias_score = self._bias_score(values)
        bias = self._bias(bias_score)
        health, health_reasons = self._health(values, request)
        reasons.extend(health_reasons)

        context_adjustment = 0.0
        if request.structure is not None:
            if request.structure.bias is StructureBias.BULLISH:
                if bias is FlowBias.BULLISH:
                    context_adjustment += 0.10
                    reasons.append("order flow aligns with bullish market structure")
                elif bias is FlowBias.BEARISH:
                    context_adjustment -= 0.15
                    reasons.append("order flow conflicts with bullish market structure")
            elif request.structure.bias is StructureBias.BEARISH:
                if bias is FlowBias.BEARISH:
                    context_adjustment += 0.10
                    reasons.append("order flow aligns with bearish market structure")
                elif bias is FlowBias.BULLISH:
                    context_adjustment -= 0.15
                    reasons.append("order flow conflicts with bearish market structure")

        if request.regime is not None:
            if request.regime.state in {
                RegimeState.UNKNOWN,
                RegimeState.UNSTABLE,
            }:
                context_adjustment -= 0.25
                reasons.append("unstable regime reduces order-flow reliability")
            elif request.regime.state is RegimeState.HIGH_VOLATILITY:
                context_adjustment -= 0.10
                reasons.append("high volatility reduces timing reliability")

        coverage = min(1.0, inputs_used / 10)
        base_confidence = min(
            1.0,
            abs(bias_score) * 0.65 + coverage * 0.35,
        )
        score = max(0.0, min(1.0, base_confidence + context_adjustment))
        confidence = self._confidence(score)

        timing = self._timing_score(
            values=values,
            bias=bias,
            health=health,
            score=score,
        )

        reasons.append(
            f"{inputs_used} order-flow input(s) contributed to the assessment"
        )
        reasons.append(f"participation classified as {participation.value}")

        return OrderFlowAssessment(
            symbol=request.symbol.upper(),
            bias=bias,
            participation=participation,
            health=health,
            confidence=confidence,
            score=round(score, 4),
            execution_timing_score=round(timing, 4),
            inputs_used=inputs_used,
            reasons=tuple(reasons),
            normalized_inputs=values,
            metadata={
                "engine_scope": "crypto_only",
                "responsibilities": (
                    "institutional_participation",
                    "market_state_enhancement",
                    "execution_timing",
                    "trade_health_monitoring",
                ),
            },
        )

    @staticmethod
    def _normalize(
        flow: FlowInput,
        reasons: list[str],
    ) -> dict[str, float | None]:
        normalized: dict[str, float | None] = {}

        for item in fields(flow):
            if item.name == "metadata":
                continue
            value = getattr(flow, item.name)
            if value is None:
                normalized[item.name] = None
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                normalized[item.name] = None
                reasons.append(f"{item.name} is not numeric")
                continue
            if not isfinite(number):
                normalized[item.name] = None
                reasons.append(f"{item.name} is not finite")
            else:
                normalized[item.name] = number

        return normalized

    @staticmethod
    def _participation(values: dict[str, float | None]) -> ParticipationState:
        price = values.get("price_change_pct")
        oi = values.get("open_interest_change_pct")
        cvd = values.get("cvd_change")
        whale = values.get("large_trade_net_usd")
        imbalance = values.get("bid_ask_imbalance")

        if price is not None and oi is not None:
            if price > 0 and oi > 0:
                if any(
                    value is not None and value > 0
                    for value in (cvd, whale)
                ):
                    return ParticipationState.INSTITUTIONAL_BUYING
            if price < 0 and oi > 0:
                if any(
                    value is not None and value < 0
                    for value in (cvd, whale)
                ):
                    return ParticipationState.INSTITUTIONAL_SELLING
            if price > 0 and oi < 0:
                return ParticipationState.SHORT_COVERING
            if price < 0 and oi < 0:
                return ParticipationState.LONG_LIQUIDATION

        if imbalance is not None:
            if imbalance > 0.20 and (cvd is None or cvd >= 0):
                return ParticipationState.PASSIVE_ACCUMULATION
            if imbalance < -0.20 and (cvd is None or cvd <= 0):
                return ParticipationState.PASSIVE_DISTRIBUTION

        if any(value is not None for value in values.values()):
            return ParticipationState.BALANCED
        return ParticipationState.ABSENT

    @staticmethod
    def _bias_score(values: dict[str, float | None]) -> float:
        contributions: list[float] = []

        def add(value: float | None, scale: float = 1.0) -> None:
            if value is None:
                return
            contributions.append(max(-1.0, min(1.0, value / scale)))

        add(values.get("cvd_change"), 1.0)
        add(values.get("footprint_delta"), 1.0)
        add(values.get("large_trade_net_usd"), 1_000_000)
        add(values.get("bid_ask_imbalance"), 1.0)
        add(values.get("price_change_pct"), 2.0)

        oi = values.get("open_interest_change_pct")
        price = values.get("price_change_pct")
        if oi is not None and price is not None:
            if oi > 0 and price > 0:
                contributions.append(0.5)
            elif oi > 0 and price < 0:
                contributions.append(-0.5)
            elif oi < 0 and price > 0:
                contributions.append(0.2)
            elif oi < 0 and price < 0:
                contributions.append(-0.2)

        longs = values.get("liquidation_long_usd")
        shorts = values.get("liquidation_short_usd")
        if longs is not None and shorts is not None:
            total = longs + shorts
            if total > 0:
                contributions.append((shorts - longs) / total)

        if not contributions:
            return 0.0
        return max(-1.0, min(1.0, sum(contributions) / len(contributions)))

    @staticmethod
    def _bias(score: float) -> FlowBias:
        if score >= 0.25:
            return FlowBias.BULLISH
        if score <= -0.25:
            return FlowBias.BEARISH
        if abs(score) <= 0.10:
            return FlowBias.NEUTRAL
        return FlowBias.CONFLICTED

    @staticmethod
    def _health(
        values: dict[str, float | None],
        request: OrderFlowRequest,
    ) -> tuple[FlowHealth, list[str]]:
        reasons: list[str] = []
        longs = values.get("liquidation_long_usd")
        shorts = values.get("liquidation_short_usd")
        funding = values.get("funding_rate")
        imbalance = values.get("bid_ask_imbalance")
        oi = values.get("open_interest_change_pct")
        price = values.get("price_change_pct")

        if funding is not None and abs(funding) >= request.high_funding_abs:
            reasons.append("funding is extremely one-sided")
            return FlowHealth.FRAGILE, reasons

        if longs is not None and shorts is not None:
            smaller = max(1.0, min(longs, shorts))
            larger = max(longs, shorts)
            ratio = larger / smaller
            if ratio >= request.extreme_liquidation_ratio:
                reasons.append("liquidation imbalance is extreme")
                return FlowHealth.EXHAUSTED, reasons

        if imbalance is not None and abs(imbalance) >= request.extreme_imbalance:
            reasons.append("order-book imbalance is extreme")
            return FlowHealth.FRAGILE, reasons

        if oi is not None and price is not None:
            if oi > 0 and abs(price) < 0.05:
                reasons.append("open interest is rising without price progress")
                return FlowHealth.TRAPPED, reasons

        reasons.append("order flow is internally healthy")
        return FlowHealth.HEALTHY, reasons

    @staticmethod
    def _timing_score(
        *,
        values: dict[str, float | None],
        bias: FlowBias,
        health: FlowHealth,
        score: float,
    ) -> float:
        if bias in {FlowBias.UNKNOWN, FlowBias.NEUTRAL}:
            return 0.0
        if health in {
            FlowHealth.UNAVAILABLE,
            FlowHealth.EXHAUSTED,
            FlowHealth.TRAPPED,
        }:
            return max(0.0, score - 0.35)

        timing = score

        cvd = values.get("cvd_change")
        imbalance = values.get("bid_ask_imbalance")
        whale = values.get("large_trade_net_usd")

        aligned = 0
        if bias is FlowBias.BULLISH:
            aligned += int(cvd is not None and cvd > 0)
            aligned += int(imbalance is not None and imbalance > 0)
            aligned += int(whale is not None and whale > 0)
        else:
            aligned += int(cvd is not None and cvd < 0)
            aligned += int(imbalance is not None and imbalance < 0)
            aligned += int(whale is not None and whale < 0)

        timing += aligned * 0.08

        if health is FlowHealth.FRAGILE:
            timing -= 0.15

        return max(0.0, min(1.0, timing))

    @staticmethod
    def _confidence(score: float) -> FlowConfidence:
        if score >= 0.75:
            return FlowConfidence.HIGH
        if score >= 0.50:
            return FlowConfidence.MEDIUM
        if score > 0:
            return FlowConfidence.LOW
        return FlowConfidence.NONE
