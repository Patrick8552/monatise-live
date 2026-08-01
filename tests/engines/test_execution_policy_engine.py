from datetime import datetime, timedelta, timezone

from monatise.engines.capital_allocation.models import (
    AllocationDecision,
    AllocationProfile,
    AllocationResult,
    AllocationTier,
)
from monatise.engines.decision.models import (
    DecisionClassification,
    DecisionDirection,
    DecisionResult,
    DecisionState,
)
from monatise.engines.execution_policy.engine import ExecutionPolicyEngine
from monatise.engines.execution_policy.models import (
    ExecutionDecision,
    ExecutionMode,
    ExecutionPolicyRequest,
)
from monatise.engines.risk_validation.models import (
    RiskDecision,
    RiskResult,
    RiskSide,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def decision() -> DecisionResult:
    return DecisionResult(
        symbol="BTCUSDT",
        classification=DecisionClassification.TREND,
        direction=DecisionDirection.LONG,
        state=DecisionState.APPROVED_FOR_RISK_REVIEW,
        conviction=0.82,
        long_score=0.85,
        short_score=0.10,
        grid_score=0.20,
        conflict_ratio=0.12,
        evidence=(),
        blockers=(),
        reasons=(),
    )


def risk() -> RiskResult:
    return RiskResult(
        symbol="BTCUSDT",
        decision=RiskDecision.APPROVED,
        side=RiskSide.LONG,
        risk_score=0.88,
        approved_risk_percent=0.01,
        risk_amount=100.0,
        validated_entry=100.0,
        validated_invalidation=97.0,
        validated_target=106.0,
        stop_distance=3.0,
        stop_distance_pct=0.03,
        reward_risk=2.0,
        signal_expires_at=NOW + timedelta(minutes=15),
        issues=(),
        reasons=(),
    )


def allocation() -> AllocationResult:
    return AllocationResult(
        symbol="BTCUSDT",
        profile=AllocationProfile.BALANCED,
        decision=AllocationDecision.APPROVED,
        tier=AllocationTier.FULL,
        allocation_score=0.82,
        capital_multiplier=1.0,
        approved_capital=2_000.0,
        approved_risk_amount=100.0,
        remaining_crypto_capacity=4_000.0,
        remaining_symbol_capacity=1_000.0,
        remaining_correlated_capacity=2_000.0,
        remaining_open_risk_capacity=450.0,
        blockers=(),
        reasons=(),
    )


def test_disabled_mode_is_blocked() -> None:
    result = ExecutionPolicyEngine().assess(
        ExecutionPolicyRequest(
            decision=decision(),
            risk=risk(),
            allocation=allocation(),
            mode=ExecutionMode.DISABLED,
            observed_at=NOW,
        )
    )

    assert result.decision is ExecutionDecision.BLOCKED
    assert result.proposal is None


def test_paper_mode_creates_non_submittable_proposal() -> None:
    result = ExecutionPolicyEngine().assess(
        ExecutionPolicyRequest(
            decision=decision(),
            risk=risk(),
            allocation=allocation(),
            mode=ExecutionMode.PAPER,
            observed_at=NOW,
            current_spread_pct=0.0005,
            estimated_slippage_pct=0.0008,
        )
    )

    assert result.decision is ExecutionDecision.PAPER_READY
    assert result.proposal is not None
    assert result.may_submit_to_execution_adapter is False
    assert result.proposal.metadata["submission_allowed"] is False


def test_live_mode_requires_manual_approval() -> None:
    result = ExecutionPolicyEngine().assess(
        ExecutionPolicyRequest(
            decision=decision(),
            risk=risk(),
            allocation=allocation(),
            mode=ExecutionMode.LIVE_APPROVAL_REQUIRED,
            observed_at=NOW,
            exchange_name="example_exchange",
            current_spread_pct=0.0005,
            estimated_slippage_pct=0.0008,
        )
    )

    assert result.decision is ExecutionDecision.BLOCKED
    assert any(
        "manual approval id" in blocker
        for blocker in result.blockers
    )


def test_live_approval_mode_still_does_not_submit() -> None:
    result = ExecutionPolicyEngine().assess(
        ExecutionPolicyRequest(
            decision=decision(),
            risk=risk(),
            allocation=allocation(),
            mode=ExecutionMode.LIVE_APPROVAL_REQUIRED,
            observed_at=NOW,
            exchange_name="example_exchange",
            manual_approval_id="approval-123",
            current_spread_pct=0.0005,
            estimated_slippage_pct=0.0008,
        )
    )

    assert result.decision is ExecutionDecision.APPROVAL_REQUIRED
    assert result.proposal is not None
    assert result.may_submit_to_execution_adapter is False
    assert result.metadata["adapter_submission_enabled"] is False


def test_expired_signal_is_blocked() -> None:
    result = ExecutionPolicyEngine().assess(
        ExecutionPolicyRequest(
            decision=decision(),
            risk=risk(),
            allocation=allocation(),
            mode=ExecutionMode.PAPER,
            observed_at=NOW + timedelta(minutes=20),
            current_spread_pct=0.0005,
            estimated_slippage_pct=0.0008,
        )
    )

    assert result.decision is ExecutionDecision.BLOCKED


def test_excessive_slippage_is_blocked() -> None:
    result = ExecutionPolicyEngine().assess(
        ExecutionPolicyRequest(
            decision=decision(),
            risk=risk(),
            allocation=allocation(),
            mode=ExecutionMode.PAPER,
            observed_at=NOW,
            current_spread_pct=0.0005,
            estimated_slippage_pct=0.01,
        )
    )

    assert result.decision is ExecutionDecision.BLOCKED
    assert any("slippage" in blocker for blocker in result.blockers)


def test_excessive_leverage_is_structurally_blocked() -> None:
    result = ExecutionPolicyEngine().assess(
        ExecutionPolicyRequest(
            decision=decision(),
            risk=risk(),
            allocation=allocation(),
            mode=ExecutionMode.PAPER,
            observed_at=NOW,
            requested_leverage=4.0,
            maximum_leverage=3.0,
        )
    )

    assert result.decision is ExecutionDecision.BLOCKED
    assert any("leverage" in blocker for blocker in result.blockers)


def test_paper_test_allocation_cannot_reach_live_mode() -> None:
    paper_allocation = AllocationResult(
        **{
            **allocation().__dict__,
            "profile": AllocationProfile.PAPER_TEST,
        }
    )
    result = ExecutionPolicyEngine().assess(
        ExecutionPolicyRequest(
            decision=decision(),
            risk=risk(),
            allocation=paper_allocation,
            mode=ExecutionMode.LIVE_APPROVAL_REQUIRED,
            observed_at=NOW,
            manual_approval_id="approval-123",
            exchange_name="example_exchange",
        )
    )

    assert result.decision is ExecutionDecision.BLOCKED
    assert any("paper-test" in blocker for blocker in result.blockers)
