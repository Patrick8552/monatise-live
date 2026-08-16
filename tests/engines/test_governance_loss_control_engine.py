from datetime import datetime, timedelta, timezone

from monatise.engines.capital_allocation.models import (
    AllocationDecision,
    AllocationProfile,
    AllocationResult,
    AllocationTier,
)
from monatise.engines.execution_policy.models import (
    ExecutionDecision,
    ExecutionMode,
    ExecutionPolicyResult,
)
from monatise.engines.governance_loss_control.engine import (
    GovernanceLossControlEngine,
)
from monatise.engines.governance_loss_control.models import (
    GovernanceAction,
    GovernanceDecision,
    GovernanceRequest,
    GovernanceState,
    LossControlSnapshot,
)
from monatise.engines.risk_validation.models import (
    RiskDecision,
    RiskResult,
    RiskSide,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def risk() -> RiskResult:
    return RiskResult(
        symbol="BTCUSDT",
        decision=RiskDecision.APPROVED,
        side=RiskSide.LONG,
        risk_score=0.85,
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
        allocation_score=0.8,
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


def execution() -> ExecutionPolicyResult:
    return ExecutionPolicyResult(
        symbol="BTCUSDT",
        mode=ExecutionMode.PAPER,
        decision=ExecutionDecision.PAPER_READY,
        proposal=None,
        blockers=(),
        warnings=(),
        reasons=(),
    )


def snapshot(**overrides) -> LossControlSnapshot:
    values = dict(
        initial_equity=10_000,
        current_equity=9_800,
        daily_start_equity=10_000,
        daily_realized_pnl=-100,
        daily_unrealized_pnl=0,
        consecutive_losses=1,
        losses_last_24h=1,
        open_risk_amount=100,
        last_loss_at=NOW - timedelta(minutes=30),
        kill_switch_active=False,
        manual_freeze_active=False,
    )
    values.update(overrides)
    return LossControlSnapshot(**values)


def test_normal_state_allows() -> None:
    result = GovernanceLossControlEngine().assess(
        GovernanceRequest(
            snapshot=snapshot(),
            risk=risk(),
            allocation=allocation(),
            execution_policy=execution(),
            portfolio=None,
            observed_at=NOW,
        )
    )

    assert result.state is GovernanceState.NORMAL
    assert result.decision is GovernanceDecision.ALLOW
    assert result.approved_risk_multiplier == 1.0


def test_caution_drawdown_reduces_risk() -> None:
    result = GovernanceLossControlEngine().assess(
        GovernanceRequest(
            snapshot=snapshot(current_equity=9_400),
            risk=risk(),
            allocation=allocation(),
            execution_policy=execution(),
            portfolio=None,
            observed_at=NOW,
            caution_drawdown_pct=0.05,
            maximum_total_drawdown_pct=0.10,
        )
    )

    assert result.state is GovernanceState.CAUTION
    assert result.decision is GovernanceDecision.REDUCE
    assert GovernanceAction.REDUCE_RISK in result.actions


def test_daily_loss_limit_freezes_new_setups() -> None:
    result = GovernanceLossControlEngine().assess(
        GovernanceRequest(
            snapshot=snapshot(
                daily_realized_pnl=-500,
                daily_unrealized_pnl=0,
            ),
            risk=risk(),
            allocation=allocation(),
            execution_policy=execution(),
            portfolio=None,
            observed_at=NOW,
            maximum_daily_loss_pct=0.04,
        )
    )

    assert result.decision is GovernanceDecision.BLOCK
    assert GovernanceAction.FREEZE_NEW_SETUPS in result.actions


def test_total_drawdown_activates_kill_switch() -> None:
    result = GovernanceLossControlEngine().assess(
        GovernanceRequest(
            snapshot=snapshot(current_equity=8_800),
            risk=risk(),
            allocation=allocation(),
            execution_policy=execution(),
            portfolio=None,
            observed_at=NOW,
            maximum_total_drawdown_pct=0.10,
        )
    )

    assert result.state is GovernanceState.KILL_SWITCH
    assert result.decision is GovernanceDecision.BLOCK
    assert GovernanceAction.ACTIVATE_KILL_SWITCH in result.actions


def test_consecutive_losses_start_cooldown() -> None:
    result = GovernanceLossControlEngine().assess(
        GovernanceRequest(
            snapshot=snapshot(consecutive_losses=3),
            risk=risk(),
            allocation=allocation(),
            execution_policy=execution(),
            portfolio=None,
            observed_at=NOW,
            maximum_consecutive_losses=3,
            cooldown_minutes=120,
        )
    )

    assert result.decision is GovernanceDecision.BLOCK
    assert result.cooldown_until is not None
    assert GovernanceAction.START_COOLDOWN in result.actions


def test_kill_switch_cannot_be_manually_overridden() -> None:
    result = GovernanceLossControlEngine().assess(
        GovernanceRequest(
            snapshot=snapshot(kill_switch_active=True),
            risk=risk(),
            allocation=allocation(),
            execution_policy=execution(),
            portfolio=None,
            observed_at=NOW,
            allow_manual_override=True,
            manual_override_id="review-123",
        )
    )

    assert result.state is GovernanceState.KILL_SWITCH
    assert result.decision is GovernanceDecision.BLOCK
    assert result.metadata["manual_override_applied"] is False


def test_daily_loss_limit_cannot_be_manually_overridden() -> None:
    # The daily-loss breaker is the system-wide daily loss control -- it must
    # be as non-overridable as the structurally similar total-drawdown gate,
    # not silently clearable via allow_manual_override.
    result = GovernanceLossControlEngine().assess(
        GovernanceRequest(
            snapshot=snapshot(daily_realized_pnl=-500, daily_unrealized_pnl=0),
            risk=risk(),
            allocation=allocation(),
            execution_policy=execution(),
            portfolio=None,
            observed_at=NOW,
            maximum_daily_loss_pct=0.04,
            allow_manual_override=True,
            manual_override_id="review-123",
        )
    )

    assert result.decision is GovernanceDecision.BLOCK
    assert GovernanceAction.FREEZE_NEW_SETUPS in result.actions
    assert result.metadata["manual_override_applied"] is False


def test_expired_cooldown_does_not_remain_blocked_forever() -> None:
    result = GovernanceLossControlEngine().assess(
        GovernanceRequest(
            snapshot=snapshot(
                consecutive_losses=3,
                last_loss_at=NOW - timedelta(minutes=180),
            ),
            risk=risk(),
            allocation=allocation(),
            execution_policy=execution(),
            portfolio=None,
            observed_at=NOW,
            maximum_consecutive_losses=3,
            cooldown_minutes=120,
        )
    )

    assert result.decision is GovernanceDecision.REDUCE
    assert result.state is GovernanceState.CAUTION


def test_manual_override_cannot_bypass_rejected_risk() -> None:
    rejected_risk = RiskResult(
        **{
            **risk().__dict__,
            "decision": RiskDecision.REJECTED,
        }
    )
    result = GovernanceLossControlEngine().assess(
        GovernanceRequest(
            snapshot=snapshot(),
            risk=rejected_risk,
            allocation=allocation(),
            execution_policy=execution(),
            portfolio=None,
            observed_at=NOW,
            allow_manual_override=True,
            manual_override_id="review-123",
        )
    )

    assert result.decision is GovernanceDecision.BLOCK
    assert result.metadata["manual_override_applied"] is False


def test_engine_does_not_close_or_execute_positions() -> None:
    result = GovernanceLossControlEngine().assess(
        GovernanceRequest(
            snapshot=snapshot(),
            risk=risk(),
            allocation=allocation(),
            execution_policy=execution(),
            portfolio=None,
            observed_at=NOW,
        )
    )

    assert not hasattr(result, "close_positions")
    assert not hasattr(result, "submit_order")
    assert result.metadata["execution_enabled"] is False
    assert result.metadata["position_closure_enabled"] is False
