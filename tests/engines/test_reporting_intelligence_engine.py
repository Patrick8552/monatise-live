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
from monatise.engines.execution_policy.models import (
    ExecutionDecision,
    ExecutionMode,
    ExecutionPolicyResult,
)
from monatise.engines.fibonacci_liquidity.models import (
    FibonacciAssessment,
    FibonacciDirection,
)
from monatise.engines.liquidity.models import LiquidityAssessment
from monatise.engines.liquidity_sweep.models import SweepAssessment
from monatise.engines.macro.models import (
    MacroAssessment,
    MacroBias,
    MacroRiskState,
)
from monatise.engines.market_data.models import (
    DataQuality,
    DataStatus,
    MarketSnapshot,
)
from monatise.engines.market_structure.models import (
    MarketStructureAssessment,
    StructureBias,
    StructureState,
)
from monatise.engines.order_flow.models import (
    FlowBias,
    FlowConfidence,
    FlowHealth,
    OrderFlowAssessment,
    ParticipationState,
)
from monatise.engines.reclaim.models import ReclaimAssessment
from monatise.engines.regime.models import (
    RegimeAssessment,
    RegimeConfidence,
    RegimeState,
)
from monatise.engines.reporting_intelligence.engine import (
    ReportingIntelligenceEngine,
)
from monatise.engines.reporting_intelligence.models import (
    ReportChannel,
    ReportRequest,
    ReportSeverity,
)
from monatise.engines.risk_validation.models import (
    RiskDecision,
    RiskResult,
    RiskSide,
)
from monatise.engines.rsi.models import (
    RSIAssessment,
    RSIBias,
    RSICondition,
    RSIDivergence,
)
from monatise.engines.supply_demand.models import ZoneAssessment


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def request(channel: ReportChannel) -> ReportRequest:
    symbol = "BTCUSDT"

    market = MarketSnapshot(
        symbol=symbol,
        interval="15m",
        price=100.0,
        candles=(),
        quality=DataQuality(
            status=DataStatus.READY,
            source="test",
            observed_at=NOW,
            latest_candle_at=NOW,
            age_seconds=0,
        ),
    )

    macro = MacroAssessment(
        symbol=symbol,
        bias=MacroBias.BULLISH,
        risk_state=MacroRiskState.NORMAL,
        conviction=0.7,
        score=0.6,
        reasons=(),
    )

    regime = RegimeAssessment(
        symbol=symbol,
        state=RegimeState.TREND_UP,
        confidence=RegimeConfidence.HIGH,
        score=0.8,
        reasons=(),
    )

    liquidity = LiquidityAssessment(
        symbol=symbol,
        current_price=100.0,
        buy_side_levels=(),
        sell_side_levels=(),
        nearest_buy_side=None,
        nearest_sell_side=None,
        reasons=(),
    )

    sweep = SweepAssessment(
        symbol=symbol,
        events=(),
        strongest_event=None,
        reasons=(),
    )

    zones = ZoneAssessment(
        symbol=symbol,
        current_price=100.0,
        demand_zones=(),
        supply_zones=(),
        nearest_demand=None,
        nearest_supply=None,
        active_demand=None,
        active_supply=None,
        reasons=(),
    )

    reclaim = ReclaimAssessment(
        symbol=symbol,
        events=(),
        strongest_event=None,
        reasons=(),
    )

    structure = MarketStructureAssessment(
        symbol=symbol,
        bias=StructureBias.BULLISH,
        state=StructureState.BULLISH_CONTINUATION,
        events=(),
        latest_event=None,
        swing_highs=(),
        swing_lows=(),
        confidence=0.85,
        reasons=(),
    )

    fibonacci = FibonacciAssessment(
        symbol=symbol,
        direction=FibonacciDirection.BULLISH,
        primary_anchor=None,
        alternate_anchors=(),
        retracement_levels=(),
        extension_levels=(),
        zones=(),
        invalidation_level=None,
        nearest_retracement=None,
        nearest_extension=None,
        active_zone=None,
        reasons=(),
    )

    order_flow = OrderFlowAssessment(
        symbol=symbol,
        bias=FlowBias.BULLISH,
        participation=ParticipationState.INSTITUTIONAL_BUYING,
        health=FlowHealth.HEALTHY,
        confidence=FlowConfidence.HIGH,
        score=0.8,
        execution_timing_score=0.8,
        inputs_used=6,
        reasons=(),
        normalized_inputs={},
    )

    decision = DecisionResult(
        symbol=symbol,
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

    rsi = RSIAssessment(
        symbol=symbol,
        current_rsi=58.0,
        previous_rsi=55.0,
        condition=RSICondition.BULLISH_MOMENTUM,
        bias=RSIBias.BULLISH,
        divergence=RSIDivergence.NONE,
        confidence=0.7,
        rsi_series=(),
        reasons=(),
    )

    risk = RiskResult(
        symbol=symbol,
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

    allocation = AllocationResult(
        symbol=symbol,
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

    execution = ExecutionPolicyResult(
        symbol=symbol,
        mode=ExecutionMode.PAPER,
        decision=ExecutionDecision.PAPER_READY,
        proposal=None,
        blockers=(),
        warnings=(),
        reasons=(),
    )

    return ReportRequest(
        generated_at=NOW,
        channel=channel,
        market=market,
        macro=macro,
        regime=regime,
        liquidity=liquidity,
        sweep=sweep,
        zones=zones,
        reclaim=reclaim,
        structure=structure,
        fibonacci=fibonacci,
        order_flow=order_flow,
        decision=decision,
        rsi=rsi,
        risk=risk,
        allocation=allocation,
        execution_policy=execution,
    )


def test_dashboard_report_is_publishable() -> None:
    result = ReportingIntelligenceEngine().build(
        request(ReportChannel.DASHBOARD)
    )

    assert result.publishable is True
    assert result.severity is ReportSeverity.APPROVED
    assert "sections" in result.payload


def test_telegram_report_is_compact() -> None:
    result = ReportingIntelligenceEngine().build(
        request(ReportChannel.TELEGRAM)
    )

    assert "compact_sections" in result.payload
    assert "sections" not in result.payload


def test_report_contains_decision_trace() -> None:
    result = ReportingIntelligenceEngine().build(
        request(ReportChannel.AUDIT)
    )

    assert any(
        item.startswith("decision:")
        for item in result.decision_trace
    )
    assert any(
        item.startswith("risk:")
        for item in result.decision_trace
    )


def test_reporting_engine_is_read_only() -> None:
    result = ReportingIntelligenceEngine().build(
        request(ReportChannel.API)
    )

    assert not hasattr(result, "approve")
    assert not hasattr(result, "execute")
    assert result.metadata["decision_mutation_enabled"] is False
    assert result.metadata["execution_enabled"] is False
