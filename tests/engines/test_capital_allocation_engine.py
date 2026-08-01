from datetime import datetime, timedelta, timezone

from monatise.engines.capital_allocation.engine import CapitalAllocationEngine
from monatise.engines.capital_allocation.models import (
    AllocationDecision,
    AllocationProfile,
    AllocationRequest,
    PortfolioExposure,
    profile_config,
)
from monatise.engines.decision.models import DecisionClassification
from monatise.engines.risk_validation.models import (
    RiskDecision,
    RiskResult,
    RiskSide,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def approved_risk() -> RiskResult:
    return RiskResult(
        symbol="BTCUSDT",
        decision=RiskDecision.APPROVED,
        side=RiskSide.LONG,
        risk_score=0.90,
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


def normal_portfolio() -> PortfolioExposure:
    return PortfolioExposure(
        total_equity=10_000,
        deployed_capital=1_000,
        open_risk_amount=150,
        crypto_exposure_pct=0.10,
        symbol_exposure_pct=0.05,
        correlated_exposure_pct=0.10,
        open_positions=2,
        symbol_positions=1,
    )


def test_all_profiles_keep_mandatory_limits() -> None:
    for profile in AllocationProfile:
        config = profile_config(profile)
        assert config.maximum_crypto_exposure_pct < 1.0
        assert config.maximum_symbol_exposure_pct < 1.0
        assert config.maximum_open_risk_pct < 1.0
        assert config.maximum_open_positions >= 1


def test_aggressive_profile_has_higher_caps_than_balanced() -> None:
    aggressive = profile_config(AllocationProfile.AGGRESSIVE)
    balanced = profile_config(AllocationProfile.BALANCED)

    assert (
        aggressive.maximum_crypto_exposure_pct
        > balanced.maximum_crypto_exposure_pct
    )
    assert (
        aggressive.maximum_open_risk_pct
        > balanced.maximum_open_risk_pct
    )


def test_paper_profile_cannot_authorize_live_execution() -> None:
    result = CapitalAllocationEngine().assess(
        AllocationRequest(
            risk=approved_risk(),
            portfolio=normal_portfolio(),
            decision_classification=DecisionClassification.TREND,
            profile=AllocationProfile.PAPER_TEST,
            requested_capital=2_000,
            live_execution_requested=True,
        )
    )

    assert result.decision is AllocationDecision.BLOCKED
    assert any(
        "cannot authorize live execution" in blocker
        for blocker in result.blockers
    )


def test_rejected_risk_is_blocked_in_aggressive_profile() -> None:
    rejected = RiskResult(
        **{
            **approved_risk().__dict__,
            "decision": RiskDecision.REJECTED,
        }
    )

    result = CapitalAllocationEngine().assess(
        AllocationRequest(
            risk=rejected,
            portfolio=normal_portfolio(),
            decision_classification=DecisionClassification.TREND,
            profile=AllocationProfile.AGGRESSIVE,
        )
    )

    assert result.decision is AllocationDecision.BLOCKED


def test_exposure_caps_remain_active_in_paper_profile() -> None:
    config = profile_config(AllocationProfile.PAPER_TEST)
    overloaded = PortfolioExposure(
        total_equity=10_000,
        deployed_capital=10_000,
        open_risk_amount=4_000,
        crypto_exposure_pct=1.0,
        symbol_exposure_pct=0.9,
        correlated_exposure_pct=0.9,
        open_positions=config.maximum_open_positions,
        symbol_positions=config.maximum_symbol_positions,
    )

    result = CapitalAllocationEngine().assess(
        AllocationRequest(
            risk=approved_risk(),
            portfolio=overloaded,
            decision_classification=DecisionClassification.TREND,
            profile=AllocationProfile.PAPER_TEST,
        )
    )

    assert result.decision is AllocationDecision.BLOCKED
    assert result.metadata["limits_mandatory"] is True


def test_engine_still_does_not_calculate_quantity() -> None:
    result = CapitalAllocationEngine().assess(
        AllocationRequest(
            risk=approved_risk(),
            portfolio=normal_portfolio(),
            decision_classification=DecisionClassification.TREND,
            profile=AllocationProfile.BALANCED,
            requested_capital=1_000,
        )
    )

    assert not hasattr(result, "quantity")
    assert not hasattr(result, "leverage")
    assert result.metadata["quantity_calculated"] is False


def test_crypto_capacity_uses_crypto_exposure_percentage() -> None:
    exposure = PortfolioExposure(
        total_equity=10_000,
        deployed_capital=500,
        open_risk_amount=100,
        crypto_exposure_pct=0.45,
        symbol_exposure_pct=0.05,
        correlated_exposure_pct=0.10,
        open_positions=1,
        symbol_positions=1,
    )

    result = CapitalAllocationEngine().assess(
        AllocationRequest(
            risk=approved_risk(),
            portfolio=exposure,
            decision_classification=DecisionClassification.TREND,
            profile=AllocationProfile.BALANCED,
            requested_capital=2_000,
        )
    )

    assert result.remaining_crypto_capacity == 500.0
    assert result.approved_capital is not None
    assert result.approved_capital <= 500.0


def test_grid_uses_profile_reduction_multiplier() -> None:
    trend = CapitalAllocationEngine().assess(
        AllocationRequest(
            risk=approved_risk(),
            portfolio=normal_portfolio(),
            decision_classification=DecisionClassification.TREND,
        )
    )
    grid = CapitalAllocationEngine().assess(
        AllocationRequest(
            risk=approved_risk(),
            portfolio=normal_portfolio(),
            decision_classification=DecisionClassification.GRID,
        )
    )

    assert grid.capital_multiplier < trend.capital_multiplier
