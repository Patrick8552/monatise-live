from __future__ import annotations

from datetime import timezone

from monatise.engines.capital_allocation.models import (
    AllocationDecision,
    AllocationProfile,
)
from monatise.engines.decision.models import (
    DecisionClassification,
    DecisionDirection,
    DecisionState,
)
from monatise.engines.execution_policy.models import (
    ExecutionDecision,
    ExecutionMode,
    ExecutionPolicyRequest,
    ExecutionPolicyResult,
    ExecutionProposal,
)
from monatise.engines.risk_validation.models import RiskDecision


class ExecutionPolicyEngine:
    """Builds a controlled execution proposal.

    This engine does not submit orders. It only decides whether a proposal is
    blocked, ready for paper simulation, or requires explicit human approval.
    """

    def assess(
        self,
        request: ExecutionPolicyRequest,
    ) -> ExecutionPolicyResult:
        request.validate()

        blockers: list[str] = []
        warnings: list[str] = []
        reasons: list[str] = []

        self._validate_upstream(request, blockers)
        self._validate_freshness(request, blockers)
        self._validate_market_costs(request, blockers, warnings)
        self._validate_mode(request, blockers)

        proposal = None
        if not blockers:
            proposal = self._proposal(request)

        if blockers:
            decision = ExecutionDecision.BLOCKED
            reasons.append("execution policy blocked the proposal")
        elif request.mode is ExecutionMode.PAPER:
            decision = ExecutionDecision.PAPER_READY
            reasons.append("proposal is ready for paper execution only")
        elif request.mode is ExecutionMode.LIVE_APPROVAL_REQUIRED:
            decision = ExecutionDecision.APPROVAL_REQUIRED
            reasons.append("explicit human approval is required before any live adapter call")
        else:
            decision = ExecutionDecision.BLOCKED
            reasons.append("execution mode is disabled")

        return ExecutionPolicyResult(
            symbol=request.decision.symbol,
            mode=request.mode,
            decision=decision,
            proposal=proposal,
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "autonomous_execution": False,
                "adapter_submission_enabled": False,
                "manual_approval_required": (
                    request.mode is ExecutionMode.LIVE_APPROVAL_REQUIRED
                ),
                "paper_only": request.mode is ExecutionMode.PAPER,
            },
        )

    @staticmethod
    def _validate_upstream(
        request: ExecutionPolicyRequest,
        blockers: list[str],
    ) -> None:
        if request.decision.state is not DecisionState.APPROVED_FOR_RISK_REVIEW:
            blockers.append("Decision Engine did not approve the setup")
        if request.decision.classification is DecisionClassification.NO_TRADE:
            blockers.append("NO_TRADE classification cannot reach execution policy")
        if request.risk.decision is not RiskDecision.APPROVED:
            blockers.append(
                f"risk validation decision is {request.risk.decision.value}"
            )
        if request.allocation.decision not in {
            AllocationDecision.APPROVED,
            AllocationDecision.REDUCED,
        }:
            blockers.append(
                f"capital allocation decision is {request.allocation.decision.value}"
            )

    @staticmethod
    def _validate_freshness(
        request: ExecutionPolicyRequest,
        blockers: list[str],
    ) -> None:
        observed = request.observed_at
        expires = request.risk.signal_expires_at

        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)

        if observed >= expires:
            blockers.append("signal expired before execution-policy review")

    @staticmethod
    def _validate_market_costs(
        request: ExecutionPolicyRequest,
        blockers: list[str],
        warnings: list[str],
    ) -> None:
        if request.current_spread_pct is None:
            warnings.append("current spread is unavailable")
        elif request.current_spread_pct > request.maximum_spread_pct:
            blockers.append(
                f"spread {request.current_spread_pct:.4%} exceeds limit "
                f"{request.maximum_spread_pct:.4%}"
            )

        if request.estimated_slippage_pct is None:
            warnings.append("estimated slippage is unavailable")
        elif request.estimated_slippage_pct > request.maximum_slippage_pct:
            blockers.append(
                f"estimated slippage {request.estimated_slippage_pct:.4%} "
                f"exceeds limit {request.maximum_slippage_pct:.4%}"
            )

    @staticmethod
    def _validate_mode(
        request: ExecutionPolicyRequest,
        blockers: list[str],
    ) -> None:
        if request.mode is ExecutionMode.DISABLED:
            blockers.append("execution mode is disabled")

        if request.requested_leverage > request.maximum_leverage:
            blockers.append(
                f"requested leverage {request.requested_leverage:g} exceeds "
                f"maximum {request.maximum_leverage:g}"
            )

        if request.mode is ExecutionMode.LIVE_APPROVAL_REQUIRED:
            if request.allocation.profile is AllocationProfile.PAPER_TEST:
                blockers.append("paper-test allocation cannot authorize live mode")
            if not request.manual_approval_id:
                blockers.append("manual approval id is required for live mode")
            if not request.exchange_name:
                blockers.append("exchange name is required for live mode")

    @staticmethod
    def _proposal(
        request: ExecutionPolicyRequest,
    ) -> ExecutionProposal:
        side = {
            DecisionDirection.LONG: "buy",
            DecisionDirection.SHORT: "sell",
            DecisionDirection.TWO_SIDED: "two_sided",
            DecisionDirection.NONE: "none",
        }[request.decision.direction]

        return ExecutionProposal(
            symbol=request.decision.symbol,
            side=side,
            order_type=request.requested_order_type,
            reference_entry=request.risk.validated_entry,
            reference_invalidation=request.risk.validated_invalidation,
            reference_target=request.risk.validated_target,
            approved_capital=request.allocation.approved_capital,
            approved_risk_amount=request.allocation.approved_risk_amount,
            requested_leverage=request.requested_leverage,
            expires_at=request.risk.signal_expires_at,
            exchange_name=request.exchange_name,
            metadata={
                "classification": request.decision.classification.value,
                "allocation_profile": request.allocation.profile.value,
                "manual_approval_id": request.manual_approval_id,
                "submission_allowed": False,
            },
        )
