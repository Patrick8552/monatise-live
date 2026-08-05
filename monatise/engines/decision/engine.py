from __future__ import annotations

from monatise.engines.decision.models import (
    DecisionClassification,
    DecisionDirection,
    DecisionEvidence,
    DecisionRequest,
    DecisionResult,
    DecisionState,
)
from monatise.engines.fibonacci_liquidity.models import (
    FibonacciDirection,
    FibonacciZoneType,
)
from monatise.engines.liquidity_sweep.models import (
    SweepDirection,
    SweepStatus,
)
from monatise.engines.macro.models import (
    MacroBias,
    MacroRiskState,
)
from monatise.engines.market_data.models import DataStatus
from monatise.engines.market_structure.models import (
    StructureBias,
    StructureState,
)
from monatise.engines.order_flow.models import (
    FlowBias,
    FlowHealth,
)
from monatise.engines.reclaim.models import (
    ReclaimDirection,
    ReclaimStatus,
)
from monatise.engines.regime.models import RegimeState
from monatise.engines.supply_demand.models import ZoneStrength


class DecisionEngine:
    """Aggregates evidence and classifies GRID, TREND, or NO_TRADE.

    The Decision Engine does not size positions, create executable stops,
    create orders, or bypass the Risk Validation Engine.
    """

    def assess(self, request: DecisionRequest) -> DecisionResult:
        request.validate()

        evidence: list[DecisionEvidence] = []
        blockers: list[str] = []
        reasons: list[str] = []

        self._hard_blocks(request, blockers)

        if request.macro is not None:
            self._macro_evidence(request, evidence)
        self._regime_evidence(request, evidence)
        self._liquidity_evidence(request, evidence)
        self._sweep_evidence(request, evidence)
        self._zone_evidence(request, evidence)
        self._reclaim_evidence(request, evidence)
        self._structure_evidence(request, evidence)
        self._fibonacci_evidence(request, evidence)
        self._order_flow_evidence(request, evidence)

        long_score = self._direction_score(evidence, DecisionDirection.LONG)
        short_score = self._direction_score(evidence, DecisionDirection.SHORT)
        grid_score = self._grid_score(request, evidence)

        directional_total = long_score + short_score
        conflict_ratio = (
            min(long_score, short_score) / max(long_score, short_score)
            if max(long_score, short_score) > 0
            else 0.0
        )

        signed_signal_score = round((long_score - short_score) * 10)
        grid_signal_score = round(grid_score * 10)

        classification, direction = self._classify(
            request=request,
            long_score=long_score,
            short_score=short_score,
            grid_score=grid_score,
            blockers=blockers,
        )

        grid_blockers = [blocker for blocker in blockers if blocker != "order flow unavailable"]
        if (
            request.minimum_signal_score > 0
            and not grid_blockers
            and grid_signal_score >= request.minimum_signal_score
        ):
            classification = DecisionClassification.GRID
            direction = DecisionDirection.TWO_SIDED
            blockers = grid_blockers

        if classification is DecisionClassification.TREND and abs(signed_signal_score) < request.minimum_signal_score:
            blockers.append(
                f"signed signal score {signed_signal_score:+d} is below threshold "
                f"{request.minimum_signal_score:+d}"
            )
            classification = DecisionClassification.NO_TRADE
            direction = DecisionDirection.NONE
        elif classification is DecisionClassification.GRID and grid_signal_score < request.minimum_signal_score:
            blockers.append(
                f"grid signal score {grid_signal_score} is below threshold "
                f"{request.minimum_signal_score}"
            )
            classification = DecisionClassification.NO_TRADE
            direction = DecisionDirection.NONE

        conviction = self._conviction(
            classification=classification,
            long_score=long_score,
            short_score=short_score,
            grid_score=grid_score,
            conflict_ratio=conflict_ratio,
        )

        if classification is DecisionClassification.TREND and conflict_ratio > request.maximum_conflict_ratio:
            blockers.append(
                f"evidence conflict ratio {conflict_ratio:.3f} exceeds limit "
                f"{request.maximum_conflict_ratio:.3f}"
            )
            classification = DecisionClassification.NO_TRADE
            direction = DecisionDirection.NONE
            conviction = 0.0

        state = self._state(
            classification=classification,
            conviction=conviction,
            blockers=blockers,
            request=request,
        )

        if classification is DecisionClassification.GRID:
            reasons.append("two-sided liquidity and range conditions favor grid logic")
        elif classification is DecisionClassification.TREND:
            reasons.append("directional structure and aligned evidence favor trend logic")
        else:
            reasons.append("current evidence does not justify a trade setup")

        if conviction >= request.high_conviction:
            reasons.append("decision conviction is high")
        elif conviction >= request.minimum_conviction:
            reasons.append("decision conviction meets minimum threshold")
        else:
            reasons.append("decision conviction is below minimum threshold")

        return DecisionResult(
            symbol=request.market.symbol,
            classification=classification,
            direction=direction,
            state=state,
            conviction=round(conviction, 4),
            long_score=round(long_score, 4),
            short_score=round(short_score, 4),
            grid_score=round(grid_score, 4),
            conflict_ratio=round(conflict_ratio, 4),
            evidence=tuple(evidence),
            blockers=tuple(dict.fromkeys(blockers)),
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "directional_evidence_total": round(directional_total, 4),
                "evidence_count": len(evidence),
                "requires_risk_validation": True,
                "execution_enabled": False,
                "signed_signal_score": signed_signal_score,
                "grid_signal_score": grid_signal_score,
                "minimum_signal_score": request.minimum_signal_score,
            },
        )

    @staticmethod
    def _hard_blocks(
        request: DecisionRequest,
        blockers: list[str],
    ) -> None:
        if request.market.quality.status is DataStatus.NO_DATA:
            blockers.append("market data unavailable")
        if request.market.quality.status is DataStatus.DEGRADED:
            blockers.append("market data is degraded")
        if request.macro is not None and request.macro.risk_state is MacroRiskState.EVENT_LOCK:
            blockers.append("macro event lock is active")
        if request.macro is not None and request.macro.risk_state is MacroRiskState.DATA_UNAVAILABLE:
            blockers.append("macro context unavailable")
        if request.regime.state in {
            RegimeState.UNKNOWN,
            RegimeState.UNSTABLE,
        }:
            blockers.append(f"regime is {request.regime.state.value}")
        if request.structure.state in {
            StructureState.UNKNOWN,
            StructureState.UNSTABLE,
        }:
            blockers.append(f"market structure is {request.structure.state.value}")
        if request.order_flow.health is FlowHealth.UNAVAILABLE:
            blockers.append("order flow unavailable")

    @staticmethod
    def _macro_evidence(
        request: DecisionRequest,
        evidence: list[DecisionEvidence],
    ) -> None:
        assert request.macro is not None
        mapping = {
            MacroBias.BULLISH: DecisionDirection.LONG,
            MacroBias.BEARISH: DecisionDirection.SHORT,
            MacroBias.NEUTRAL: DecisionDirection.NONE,
            MacroBias.CONFLICTED: DecisionDirection.NONE,
            MacroBias.UNKNOWN: DecisionDirection.NONE,
        }
        evidence.append(
            DecisionEvidence(
                source="macro",
                score=request.macro.conviction,
                direction=mapping[request.macro.bias],
                weight=0.55,
                reason=f"macro bias is {request.macro.bias.value}",
            )
        )

    @staticmethod
    def _regime_evidence(
        request: DecisionRequest,
        evidence: list[DecisionEvidence],
    ) -> None:
        state = request.regime.state
        if state is RegimeState.TREND_UP:
            direction = DecisionDirection.LONG
            score = request.regime.score
        elif state is RegimeState.TREND_DOWN:
            direction = DecisionDirection.SHORT
            score = request.regime.score
        elif state in {RegimeState.RANGE, RegimeState.COMPRESSION}:
            direction = DecisionDirection.TWO_SIDED
            score = request.regime.score
        else:
            direction = DecisionDirection.NONE
            score = request.regime.score

        evidence.append(
            DecisionEvidence(
                source="regime",
                score=score,
                direction=direction,
                weight=1.00,
                reason=f"regime is {state.value}",
            )
        )

    @staticmethod
    def _liquidity_evidence(
        request: DecisionRequest,
        evidence: list[DecisionEvidence],
    ) -> None:
        if request.liquidity.balanced:
            evidence.append(
                DecisionEvidence(
                    source="liquidity",
                    score=0.75,
                    direction=DecisionDirection.TWO_SIDED,
                    weight=1.00,
                    reason="buy-side and sell-side liquidity are both mapped",
                )
            )
        elif request.liquidity.nearest_buy_side:
            evidence.append(
                DecisionEvidence(
                    source="liquidity",
                    score=0.45,
                    direction=DecisionDirection.LONG,
                    weight=0.50,
                    reason="buy-side liquidity is the dominant mapped objective",
                )
            )
        elif request.liquidity.nearest_sell_side:
            evidence.append(
                DecisionEvidence(
                    source="liquidity",
                    score=0.45,
                    direction=DecisionDirection.SHORT,
                    weight=0.50,
                    reason="sell-side liquidity is the dominant mapped objective",
                )
            )

    @staticmethod
    def _sweep_evidence(
        request: DecisionRequest,
        evidence: list[DecisionEvidence],
    ) -> None:
        event = request.sweep.strongest_event
        if event is None:
            return

        score = 0.85 if event.status is SweepStatus.CONFIRMED else 0.45

        direction = (
            DecisionDirection.LONG
            if event.direction is SweepDirection.SELL_SIDE_TAKEN
            else DecisionDirection.SHORT
        )

        evidence.append(
            DecisionEvidence(
                source="liquidity_sweep",
                score=score,
                direction=direction,
                weight=0.85,
                reason=(
                    f"{event.status.value} {event.direction.value} event detected"
                ),
            )
        )

    @staticmethod
    def _zone_evidence(
        request: DecisionRequest,
        evidence: list[DecisionEvidence],
    ) -> None:
        if request.zones.active_demand is not None:
            strength = {
                ZoneStrength.HIGH: 0.85,
                ZoneStrength.MEDIUM: 0.65,
                ZoneStrength.LOW: 0.40,
            }[request.zones.active_demand.strength]
            evidence.append(
                DecisionEvidence(
                    source="supply_demand",
                    score=strength,
                    direction=DecisionDirection.LONG,
                    weight=0.75,
                    reason="price is inside an active demand zone",
                )
            )

        if request.zones.active_supply is not None:
            strength = {
                ZoneStrength.HIGH: 0.85,
                ZoneStrength.MEDIUM: 0.65,
                ZoneStrength.LOW: 0.40,
            }[request.zones.active_supply.strength]
            evidence.append(
                DecisionEvidence(
                    source="supply_demand",
                    score=strength,
                    direction=DecisionDirection.SHORT,
                    weight=0.75,
                    reason="price is inside an active supply zone",
                )
            )

    @staticmethod
    def _reclaim_evidence(
        request: DecisionRequest,
        evidence: list[DecisionEvidence],
    ) -> None:
        event = request.reclaim.strongest_event
        if event is None:
            return

        score = {
            ReclaimStatus.CONFIRMED: 0.90,
            ReclaimStatus.POSSIBLE: 0.55,
            ReclaimStatus.FAILED: 0.20,
            ReclaimStatus.NONE: 0.0,
            ReclaimStatus.INVALID: 0.0,
        }[event.status]

        direction = (
            DecisionDirection.LONG
            if event.direction is ReclaimDirection.BULLISH_RECLAIM
            else DecisionDirection.SHORT
        )

        evidence.append(
            DecisionEvidence(
                source="reclaim",
                score=score,
                direction=direction,
                weight=1.00,
                reason=f"reclaim status is {event.status.value}",
            )
        )

    @staticmethod
    def _structure_evidence(
        request: DecisionRequest,
        evidence: list[DecisionEvidence],
    ) -> None:
        direction = {
            StructureBias.BULLISH: DecisionDirection.LONG,
            StructureBias.BEARISH: DecisionDirection.SHORT,
            StructureBias.NEUTRAL: DecisionDirection.TWO_SIDED,
            StructureBias.CONFLICTED: DecisionDirection.NONE,
            StructureBias.UNKNOWN: DecisionDirection.NONE,
        }[request.structure.bias]

        evidence.append(
            DecisionEvidence(
                source="market_structure",
                score=request.structure.confidence,
                direction=direction,
                weight=1.20,
                reason=(
                    f"structure is {request.structure.state.value} "
                    f"with {request.structure.bias.value} bias"
                ),
            )
        )

    @staticmethod
    def _fibonacci_evidence(
        request: DecisionRequest,
        evidence: list[DecisionEvidence],
    ) -> None:
        if not request.fibonacci.has_valid_anchor:
            return

        direction = (
            DecisionDirection.LONG
            if request.fibonacci.direction is FibonacciDirection.BULLISH
            else DecisionDirection.SHORT
        )

        score = request.fibonacci.primary_anchor.score if request.fibonacci.primary_anchor else 0.0

        if request.fibonacci.active_zone is not None:
            score = max(score, request.fibonacci.active_zone.score)

        evidence.append(
            DecisionEvidence(
                source="fibonacci",
                score=score,
                direction=direction,
                weight=0.65,
                reason=(
                    "validated Fibonacci anchor and active confluence zone"
                    if request.fibonacci.active_zone
                    else "validated Fibonacci anchor"
                ),
            )
        )

    @staticmethod
    def _order_flow_evidence(
        request: DecisionRequest,
        evidence: list[DecisionEvidence],
    ) -> None:
        direction = {
            FlowBias.BULLISH: DecisionDirection.LONG,
            FlowBias.BEARISH: DecisionDirection.SHORT,
            FlowBias.NEUTRAL: DecisionDirection.NONE,
            FlowBias.CONFLICTED: DecisionDirection.NONE,
            FlowBias.UNKNOWN: DecisionDirection.NONE,
        }[request.order_flow.bias]

        score = (
            request.order_flow.score * 0.55
            + request.order_flow.execution_timing_score * 0.45
        )

        evidence.append(
            DecisionEvidence(
                source="order_flow",
                score=score,
                direction=direction,
                weight=1.20,
                reason=(
                    f"order flow is {request.order_flow.bias.value}, "
                    f"{request.order_flow.health.value}"
                ),
            )
        )

    @staticmethod
    def _direction_score(
        evidence: list[DecisionEvidence],
        direction: DecisionDirection,
    ) -> float:
        relevant = [
            item for item in evidence
            if item.direction is direction
        ]
        total_weight = sum(item.weight for item in relevant)
        if total_weight == 0:
            return 0.0
        return sum(
            item.score * item.weight
            for item in relevant
        ) / total_weight

    @staticmethod
    def _grid_score(
        request: DecisionRequest,
        evidence: list[DecisionEvidence],
    ) -> float:
        relevant = [
            item for item in evidence
            if item.direction is DecisionDirection.TWO_SIDED
        ]

        weighted = 0.0
        total_weight = 0.0
        for item in relevant:
            weighted += item.score * item.weight
            total_weight += item.weight

        score = weighted / total_weight if total_weight else 0.0

        if request.regime.state in {
            RegimeState.RANGE,
            RegimeState.COMPRESSION,
        }:
            score += request.grid_regime_bonus

        if request.require_two_sided_liquidity_for_grid and not request.liquidity.balanced:
            return 0.0

        if request.regime.state in {
            RegimeState.EXPANSION,
            RegimeState.HIGH_VOLATILITY,
            RegimeState.TREND_UP,
            RegimeState.TREND_DOWN,
        }:
            score -= 0.20

        return max(0.0, min(1.0, score))

    @staticmethod
    def _classify(
        *,
        request: DecisionRequest,
        long_score: float,
        short_score: float,
        grid_score: float,
        blockers: list[str],
    ) -> tuple[DecisionClassification, DecisionDirection]:
        if blockers:
            return DecisionClassification.NO_TRADE, DecisionDirection.NONE

        directional_score = max(long_score, short_score)
        direction = (
            DecisionDirection.LONG
            if long_score > short_score
            else DecisionDirection.SHORT
        )

        trend_allowed = request.structure.directional
        if request.require_structure_for_trend and not trend_allowed:
            directional_score = 0.0

        if grid_score >= directional_score and grid_score >= request.minimum_conviction:
            return DecisionClassification.GRID, DecisionDirection.TWO_SIDED

        if directional_score >= request.minimum_conviction:
            return DecisionClassification.TREND, direction

        return DecisionClassification.NO_TRADE, DecisionDirection.NONE

    @staticmethod
    def _conviction(
        *,
        classification: DecisionClassification,
        long_score: float,
        short_score: float,
        grid_score: float,
        conflict_ratio: float,
    ) -> float:
        if classification is DecisionClassification.GRID:
            base = grid_score
        elif classification is DecisionClassification.TREND:
            base = max(long_score, short_score)
        else:
            return 0.0

        conflict_penalty = conflict_ratio * 0.40
        return max(0.0, min(1.0, base - conflict_penalty))

    @staticmethod
    def _state(
        *,
        classification: DecisionClassification,
        conviction: float,
        blockers: list[str],
        request: DecisionRequest,
    ) -> DecisionState:
        if blockers or classification is DecisionClassification.NO_TRADE:
            return DecisionState.BLOCKED
        if conviction >= request.minimum_conviction:
            return DecisionState.APPROVED_FOR_RISK_REVIEW
        return DecisionState.CONDITIONAL
