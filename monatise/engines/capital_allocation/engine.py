from __future__ import annotations

from monatise.engines.capital_allocation.models import (
    AllocationDecision,
    AllocationProfile,
    AllocationRequest,
    AllocationResult,
    AllocationTier,
    profile_config,
)
from monatise.engines.decision.models import DecisionClassification
from monatise.engines.risk_validation.models import RiskDecision


class CapitalAllocationEngine:
    """Applies mandatory portfolio limits through configurable profiles.

    Profiles may change limits, but no profile removes risk approval,
    concentration, exposure, open-risk, or position-count safeguards.
    """

    def assess(self, request: AllocationRequest) -> AllocationResult:
        request.validate()
        config = profile_config(request.profile)

        blockers: list[str] = []
        reasons: list[str] = []
        portfolio = request.portfolio
        risk = request.risk

        if risk.decision is not RiskDecision.APPROVED:
            blockers.append(
                f"risk validation decision is {risk.decision.value}"
            )

        if not risk.approved_for_execution_policy:
            blockers.append("risk result is not approved for execution policy")

        if (
            request.live_execution_requested
            and not config.live_capable
        ):
            blockers.append(
                f"profile {request.profile.value} cannot authorize live execution"
            )

        if portfolio.open_positions >= config.maximum_open_positions:
            blockers.append("maximum open-position count reached")

        if portfolio.symbol_positions >= config.maximum_symbol_positions:
            blockers.append("maximum symbol-position count reached")

        remaining_crypto_capacity = max(
            0.0,
            portfolio.total_equity * config.maximum_crypto_exposure_pct
            - portfolio.total_equity * portfolio.crypto_exposure_pct,
        )
        remaining_symbol_capacity = max(
            0.0,
            portfolio.total_equity * config.maximum_symbol_exposure_pct
            - portfolio.total_equity * portfolio.symbol_exposure_pct,
        )
        remaining_correlated_capacity = max(
            0.0,
            portfolio.total_equity * config.maximum_correlated_exposure_pct
            - portfolio.total_equity * portfolio.correlated_exposure_pct,
        )
        remaining_open_risk_capacity = max(
            0.0,
            portfolio.total_equity * config.maximum_open_risk_pct
            - portfolio.open_risk_amount,
        )

        if remaining_crypto_capacity <= 0:
            blockers.append("crypto exposure capacity exhausted")
        if remaining_symbol_capacity <= 0:
            blockers.append("symbol exposure capacity exhausted")
        if remaining_correlated_capacity <= 0:
            blockers.append("correlated exposure capacity exhausted")
        if remaining_open_risk_capacity <= 0:
            blockers.append("open-risk capacity exhausted")

        allocation_score = self._allocation_score(request)
        tier, multiplier = self._tier_and_multiplier(
            allocation_score,
            config,
        )

        if request.decision_classification is DecisionClassification.GRID:
            multiplier *= config.grid_multiplier
            reasons.append("grid classification applies profile grid multiplier")

        approved_risk_amount = None
        if risk.risk_amount is not None:
            approved_risk_amount = min(
                risk.risk_amount * multiplier,
                remaining_open_risk_capacity,
            )

        approved_capital = None
        if request.requested_capital is not None:
            approved_capital = min(
                request.requested_capital * multiplier,
                remaining_crypto_capacity,
                remaining_symbol_capacity,
                remaining_correlated_capacity,
            )

        if blockers:
            decision = AllocationDecision.BLOCKED
            tier = AllocationTier.NONE
            multiplier = 0.0
            approved_capital = 0.0 if approved_capital is not None else None
            approved_risk_amount = (
                0.0 if approved_risk_amount is not None else None
            )
            reasons.append("mandatory portfolio safeguards blocked allocation")
        elif tier is AllocationTier.FULL:
            decision = AllocationDecision.APPROVED
            reasons.append("full allocation tier approved")
        elif tier in {AllocationTier.REDUCED, AllocationTier.MINIMAL}:
            decision = AllocationDecision.REDUCED
            reasons.append(f"{tier.value} allocation tier approved")
        else:
            decision = AllocationDecision.BLOCKED
            reasons.append("allocation score is below profile threshold")

        reasons.append(f"allocation profile is {request.profile.value}")

        return AllocationResult(
            symbol=risk.symbol,
            profile=request.profile,
            decision=decision,
            tier=tier,
            allocation_score=round(allocation_score, 4),
            capital_multiplier=round(multiplier, 4),
            approved_capital=(
                round(approved_capital, 8)
                if approved_capital is not None
                else None
            ),
            approved_risk_amount=(
                round(approved_risk_amount, 8)
                if approved_risk_amount is not None
                else None
            ),
            remaining_crypto_capacity=round(remaining_crypto_capacity, 8),
            remaining_symbol_capacity=round(remaining_symbol_capacity, 8),
            remaining_correlated_capacity=round(
                remaining_correlated_capacity, 8
            ),
            remaining_open_risk_capacity=round(
                remaining_open_risk_capacity, 8
            ),
            blockers=tuple(dict.fromkeys(blockers)),
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "execution_enabled": False,
                "quantity_calculated": False,
                "limits_mandatory": True,
                "profile_live_capable": config.live_capable,
                "requires_execution_policy": decision
                in {AllocationDecision.APPROVED, AllocationDecision.REDUCED},
            },
        )

    @staticmethod
    def _allocation_score(request: AllocationRequest) -> float:
        risk = request.risk
        portfolio = request.portfolio

        score = risk.risk_score * 0.70
        open_risk_ratio = portfolio.open_risk_amount / portfolio.total_equity

        score -= min(
            0.25,
            portfolio.crypto_exposure_pct * 0.15
            + portfolio.correlated_exposure_pct * 0.10
            + open_risk_ratio * 0.20,
        )
        score -= min(
            0.15,
            portfolio.symbol_exposure_pct * 0.20,
        )

        if risk.reward_risk is not None:
            score += min(
                0.15,
                max(0.0, risk.reward_risk - 1.0) * 0.05,
            )

        return max(0.0, min(1.0, score))

    @staticmethod
    def _tier_and_multiplier(score, config):
        if score >= config.full_allocation_score:
            return AllocationTier.FULL, config.full_multiplier
        if score >= config.reduced_allocation_score:
            return AllocationTier.REDUCED, config.reduced_multiplier
        if score >= config.minimal_allocation_score:
            return AllocationTier.MINIMAL, config.minimal_multiplier
        return AllocationTier.NONE, 0.0
