from __future__ import annotations

from datetime import timezone

from monatise.engines.decision.models import (
    DecisionClassification,
    DecisionDirection,
    DecisionState,
)
from monatise.engines.macro.models import MacroRiskState
from monatise.engines.market_data.models import DataStatus
from monatise.engines.order_flow.models import FlowHealth
from monatise.engines.regime.models import RegimeState
from monatise.engines.risk_validation.models import (
    RiskDecision,
    RiskIssue,
    RiskIssueSeverity,
    RiskRequest,
    RiskResult,
    RiskSide,
)
from monatise.engines.rsi.models import RSIBias, RSICondition


class RiskValidationEngine:
    """Validates a setup before Execution Policy may consider it.

    This engine validates risk only. It does not size executable orders,
    connect to exchanges, or place trades.
    """

    def assess(self, request: RiskRequest) -> RiskResult:
        request.validate()
        issues: list[RiskIssue] = []
        reasons: list[str] = []

        side = self._side(request)
        self._validate_decision(request, issues)
        self._validate_freshness(request, issues)
        self._validate_market_context(request, issues)
        self._validate_rsi_context(request, side, issues)

        entry = request.proposed_entry
        invalidation = self._resolve_invalidation(request, side)
        target = request.proposed_target

        stop_distance = None
        stop_distance_pct = None
        reward_risk = None

        if side in {RiskSide.LONG, RiskSide.SHORT}:
            if entry is None:
                issues.append(
                    RiskIssue(
                        code="missing_entry",
                        severity=RiskIssueSeverity.BLOCKER,
                        message="directional setup requires a proposed entry",
                    )
                )
            if invalidation is None:
                issues.append(
                    RiskIssue(
                        code="missing_invalidation",
                        severity=RiskIssueSeverity.BLOCKER,
                        message="directional setup requires structural invalidation",
                    )
                )

            if entry is not None and invalidation is not None:
                geometry_issue = self._validate_geometry(
                    side=side,
                    entry=entry,
                    invalidation=invalidation,
                )
                if geometry_issue:
                    issues.append(geometry_issue)
                else:
                    stop_distance = abs(entry - invalidation)
                    stop_distance_pct = stop_distance / entry
                    self._validate_stop_distance(
                        request=request,
                        stop_distance_pct=stop_distance_pct,
                        issues=issues,
                    )

            if (
                entry is not None
                and invalidation is not None
                and target is not None
                and stop_distance
                and stop_distance > 0
            ):
                reward_risk = self._reward_risk(
                    side=side,
                    entry=entry,
                    invalidation=invalidation,
                    target=target,
                )
                if reward_risk is None:
                    issues.append(
                        RiskIssue(
                            code="invalid_target_geometry",
                            severity=RiskIssueSeverity.BLOCKER,
                            message="target is on the wrong side of entry",
                        )
                    )
                elif reward_risk < request.minimum_reward_risk:
                    issues.append(
                        RiskIssue(
                            code="reward_risk_too_low",
                            severity=RiskIssueSeverity.BLOCKER,
                            message=(
                                f"reward-to-risk {reward_risk:.2f} is below "
                                f"minimum {request.minimum_reward_risk:.2f}"
                            ),
                        )
                    )
            elif side in {RiskSide.LONG, RiskSide.SHORT} and target is None:
                issues.append(
                    RiskIssue(
                        code="missing_target",
                        severity=RiskIssueSeverity.WARNING,
                        message="target is unavailable; setup cannot be fully validated",
                    )
                )

        elif side is RiskSide.GRID:
            if not request.decision.classification is DecisionClassification.GRID:
                issues.append(
                    RiskIssue(
                        code="grid_classification_mismatch",
                        severity=RiskIssueSeverity.BLOCKER,
                        message="grid risk review requires GRID decision classification",
                    )
                )
            if not request.regime.prefers_grid_logic:
                issues.append(
                    RiskIssue(
                        code="grid_regime_mismatch",
                        severity=RiskIssueSeverity.BLOCKER,
                        message="current regime does not prefer grid logic",
                    )
                )

        risk_amount = (
            request.account_equity * request.risk_percent
            if request.account_equity is not None
            else None
        )
        if request.account_equity is None:
            severity = (
                RiskIssueSeverity.WARNING
                if request.allow_conditional_without_account_equity
                else RiskIssueSeverity.BLOCKER
            )
            issues.append(
                RiskIssue(
                    code="account_equity_unavailable",
                    severity=severity,
                    message="account equity is unavailable for risk-amount validation",
                )
            )

        blockers = [
            issue for issue in issues
            if issue.severity is RiskIssueSeverity.BLOCKER
        ]
        warnings = [
            issue for issue in issues
            if issue.severity is RiskIssueSeverity.WARNING
        ]

        risk_score = self._risk_score(
            request=request,
            blocker_count=len(blockers),
            warning_count=len(warnings),
            reward_risk=reward_risk,
        )

        if blockers:
            decision = RiskDecision.REJECTED
            reasons.append("one or more risk blockers rejected the setup")
        elif warnings:
            decision = RiskDecision.CONDITIONAL
            reasons.append("setup passed hard validation with unresolved warnings")
        else:
            decision = RiskDecision.APPROVED
            reasons.append("setup passed risk validation")

        reasons.append(
            f"approved risk percentage is {request.risk_percent:.4f}"
        )
        if reward_risk is not None:
            reasons.append(f"validated reward-to-risk is {reward_risk:.2f}")

        return RiskResult(
            symbol=request.market.symbol,
            decision=decision,
            side=side,
            risk_score=round(risk_score, 4),
            approved_risk_percent=request.risk_percent,
            risk_amount=round(risk_amount, 8) if risk_amount is not None else None,
            validated_entry=entry,
            validated_invalidation=invalidation,
            validated_target=target,
            stop_distance=round(stop_distance, 8) if stop_distance is not None else None,
            stop_distance_pct=(
                round(stop_distance_pct, 8)
                if stop_distance_pct is not None
                else None
            ),
            reward_risk=round(reward_risk, 4) if reward_risk is not None else None,
            signal_expires_at=request.signal_expires_at,
            issues=tuple(issues),
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "execution_enabled": False,
                "requires_execution_policy": decision is RiskDecision.APPROVED,
                "account_equity_supplied": request.account_equity is not None,
            },
        )

    @staticmethod
    def _side(request: RiskRequest) -> RiskSide:
        if request.decision.classification is DecisionClassification.GRID:
            return RiskSide.GRID
        if request.decision.direction is DecisionDirection.LONG:
            return RiskSide.LONG
        if request.decision.direction is DecisionDirection.SHORT:
            return RiskSide.SHORT
        return RiskSide.NONE

    @staticmethod
    def _validate_decision(
        request: RiskRequest,
        issues: list[RiskIssue],
    ) -> None:
        if request.decision.state is not DecisionState.APPROVED_FOR_RISK_REVIEW:
            issues.append(
                RiskIssue(
                    code="decision_not_approved",
                    severity=RiskIssueSeverity.BLOCKER,
                    message="Decision Engine did not approve setup for risk review",
                )
            )
        if request.decision.classification is DecisionClassification.NO_TRADE:
            issues.append(
                RiskIssue(
                    code="no_trade_decision",
                    severity=RiskIssueSeverity.BLOCKER,
                    message="NO_TRADE decisions cannot pass risk validation",
                )
            )

    @staticmethod
    def _validate_freshness(
        request: RiskRequest,
        issues: list[RiskIssue],
    ) -> None:
        observed = request.observed_at
        expires = request.signal_expires_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)

        if observed >= expires:
            issues.append(
                RiskIssue(
                    code="signal_expired",
                    severity=RiskIssueSeverity.BLOCKER,
                    message="signal has expired",
                )
            )

        if request.market.quality.status is DataStatus.DEGRADED:
            issues.append(
                RiskIssue(
                    code="degraded_market_data",
                    severity=RiskIssueSeverity.BLOCKER,
                    message="degraded market data cannot pass risk validation",
                )
            )
        if request.market.quality.status is DataStatus.NO_DATA:
            issues.append(
                RiskIssue(
                    code="market_data_unavailable",
                    severity=RiskIssueSeverity.BLOCKER,
                    message="market data is unavailable",
                )
            )

    @staticmethod
    def _validate_market_context(
        request: RiskRequest,
        issues: list[RiskIssue],
    ) -> None:
        if request.macro.risk_state in {
            MacroRiskState.EVENT_LOCK,
            MacroRiskState.DATA_UNAVAILABLE,
        }:
            issues.append(
                RiskIssue(
                    code="macro_risk_block",
                    severity=RiskIssueSeverity.BLOCKER,
                    message=f"macro risk state is {request.macro.risk_state.value}",
                )
            )

        if request.regime.state in {
            RegimeState.UNKNOWN,
            RegimeState.UNSTABLE,
        }:
            issues.append(
                RiskIssue(
                    code="regime_block",
                    severity=RiskIssueSeverity.BLOCKER,
                    message=f"regime is {request.regime.state.value}",
                )
            )

        if request.order_flow.health in {
            FlowHealth.UNAVAILABLE,
            FlowHealth.TRAPPED,
            FlowHealth.EXHAUSTED,
        }:
            issues.append(
                RiskIssue(
                    code="order_flow_health_block",
                    severity=RiskIssueSeverity.BLOCKER,
                    message=f"order-flow health is {request.order_flow.health.value}",
                )
            )
        elif request.order_flow.health is FlowHealth.FRAGILE:
            issues.append(
                RiskIssue(
                    code="fragile_order_flow",
                    severity=RiskIssueSeverity.WARNING,
                    message="order flow is fragile",
                )
            )

    @staticmethod
    def _validate_rsi_context(
        request: RiskRequest,
        side: RiskSide,
        issues: list[RiskIssue],
    ) -> None:
        if not request.rsi.usable:
            issues.append(
                RiskIssue(
                    code="rsi_unavailable",
                    severity=RiskIssueSeverity.WARNING,
                    message="RSI context is unavailable",
                )
            )
            return

        if side is RiskSide.LONG:
            if (
                request.rsi.condition is RSICondition.OVERBOUGHT
                and request.rsi.bias is RSIBias.BEARISH
            ):
                issues.append(
                    RiskIssue(
                        code="long_rsi_exhaustion",
                        severity=RiskIssueSeverity.WARNING,
                        message="long setup faces overbought bearish RSI context",
                    )
                )
        elif side is RiskSide.SHORT:
            if (
                request.rsi.condition is RSICondition.OVERSOLD
                and request.rsi.bias is RSIBias.BULLISH
            ):
                issues.append(
                    RiskIssue(
                        code="short_rsi_exhaustion",
                        severity=RiskIssueSeverity.WARNING,
                        message="short setup faces oversold bullish RSI context",
                    )
                )

    @staticmethod
    def _resolve_invalidation(
        request: RiskRequest,
        side: RiskSide,
    ) -> float | None:
        if request.proposed_invalidation is not None:
            return request.proposed_invalidation

        if request.fibonacci.invalidation_level is not None:
            return request.fibonacci.invalidation_level.price

        if side is RiskSide.LONG and request.zones.nearest_demand is not None:
            return request.zones.nearest_demand.distal

        if side is RiskSide.SHORT and request.zones.nearest_supply is not None:
            return request.zones.nearest_supply.distal

        return None

    @staticmethod
    def _validate_geometry(
        *,
        side: RiskSide,
        entry: float,
        invalidation: float,
    ) -> RiskIssue | None:
        if entry <= 0 or invalidation <= 0:
            return RiskIssue(
                code="non_positive_geometry",
                severity=RiskIssueSeverity.BLOCKER,
                message="entry and invalidation must be positive",
            )

        if side is RiskSide.LONG and invalidation >= entry:
            return RiskIssue(
                code="invalid_long_invalidation",
                severity=RiskIssueSeverity.BLOCKER,
                message="long invalidation must be below entry",
            )

        if side is RiskSide.SHORT and invalidation <= entry:
            return RiskIssue(
                code="invalid_short_invalidation",
                severity=RiskIssueSeverity.BLOCKER,
                message="short invalidation must be above entry",
            )

        return None

    @staticmethod
    def _validate_stop_distance(
        *,
        request: RiskRequest,
        stop_distance_pct: float,
        issues: list[RiskIssue],
    ) -> None:
        if stop_distance_pct < request.minimum_stop_distance_pct:
            issues.append(
                RiskIssue(
                    code="stop_too_tight",
                    severity=RiskIssueSeverity.BLOCKER,
                    message=(
                        f"stop distance {stop_distance_pct:.4%} is below "
                        f"minimum {request.minimum_stop_distance_pct:.4%}"
                    ),
                )
            )

        threshold = request.maximum_stop_distance_pct
        if request.regime.state is RegimeState.HIGH_VOLATILITY:
            threshold *= request.volatility_stop_multiplier

        if stop_distance_pct > threshold:
            issues.append(
                RiskIssue(
                    code="stop_too_wide",
                    severity=RiskIssueSeverity.BLOCKER,
                    message=(
                        f"stop distance {stop_distance_pct:.4%} exceeds "
                        f"maximum {threshold:.4%}"
                    ),
                )
            )

    @staticmethod
    def _reward_risk(
        *,
        side: RiskSide,
        entry: float,
        invalidation: float,
        target: float,
    ) -> float | None:
        risk = abs(entry - invalidation)
        if risk <= 0:
            return None

        if side is RiskSide.LONG:
            if target <= entry:
                return None
            reward = target - entry
        else:
            if target >= entry:
                return None
            reward = entry - target

        return reward / risk

    @staticmethod
    def _risk_score(
        *,
        request: RiskRequest,
        blocker_count: int,
        warning_count: int,
        reward_risk: float | None,
    ) -> float:
        score = request.decision.conviction

        if reward_risk is not None:
            score += min(0.15, max(0.0, reward_risk - 1.0) * 0.05)

        if request.order_flow.health is FlowHealth.HEALTHY:
            score += 0.05

        score -= blocker_count * 0.35
        score -= warning_count * 0.10

        return max(0.0, min(1.0, score))
