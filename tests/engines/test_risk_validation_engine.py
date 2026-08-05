from dataclasses import replace
from datetime import datetime, timedelta, timezone

from monatise.engines.decision.models import (
    DecisionClassification,
    DecisionDirection,
    DecisionResult,
    DecisionState,
)
from monatise.engines.fibonacci_liquidity.models import FibonacciAssessment, FibonacciDirection
from monatise.engines.macro.models import MacroAssessment, MacroBias, MacroRiskState
from monatise.engines.market_data.models import DataQuality, DataStatus, MarketSnapshot
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
from monatise.engines.regime.models import (
    RegimeAssessment,
    RegimeConfidence,
    RegimeState,
)
from monatise.engines.risk_validation.engine import RiskValidationEngine
from monatise.engines.risk_validation.models import RiskDecision, RiskRequest
from monatise.engines.rsi.models import (
    RSIAssessment,
    RSIBias,
    RSICondition,
    RSIDivergence,
)
from monatise.engines.supply_demand.models import ZoneAssessment


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def request() -> RiskRequest:
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

    decision = DecisionResult(
        symbol=symbol,
        classification=DecisionClassification.TREND,
        direction=DecisionDirection.LONG,
        state=DecisionState.APPROVED_FOR_RISK_REVIEW,
        conviction=0.80,
        long_score=0.85,
        short_score=0.10,
        grid_score=0.20,
        conflict_ratio=0.12,
        evidence=(),
        blockers=(),
        reasons=(),
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

    structure = MarketStructureAssessment(
        symbol=symbol,
        bias=StructureBias.BULLISH,
        state=StructureState.BULLISH_CONTINUATION,
        events=(),
        latest_event=None,
        swing_highs=(),
        swing_lows=(),
        confidence=0.8,
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

    return RiskRequest(
        market=market,
        decision=decision,
        macro=macro,
        regime=regime,
        structure=structure,
        fibonacci=fibonacci,
        zones=zones,
        order_flow=order_flow,
        rsi=rsi,
        observed_at=NOW,
        signal_expires_at=NOW + timedelta(minutes=15),
        proposed_entry=100.0,
        proposed_invalidation=97.0,
        proposed_target=106.0,
        account_equity=10_000,
        risk_percent=0.01,
        maximum_risk_percent=0.02,
        minimum_reward_risk=1.5,
    )


def test_valid_setup_is_approved() -> None:
    result = RiskValidationEngine().assess(request())

    assert result.decision is RiskDecision.APPROVED
    assert result.reward_risk == 2.0
    assert result.risk_amount == 100.0
    assert result.approved_for_execution_policy is True


def test_low_reward_risk_is_rejected() -> None:
    value = request()
    value = RiskRequest(
        **{
            **value.__dict__,
            "proposed_target": 102.0,
        }
    )

    result = RiskValidationEngine().assess(value)

    assert result.decision is RiskDecision.REJECTED
    assert any(
        issue.code == "reward_risk_too_low"
        for issue in result.issues
    )


def test_macro_event_lock_rejects_setup() -> None:
    value = request()
    locked = MacroAssessment(
        symbol="BTCUSDT",
        bias=MacroBias.BULLISH,
        risk_state=MacroRiskState.EVENT_LOCK,
        conviction=0.8,
        score=0.8,
        reasons=(),
    )
    value = RiskRequest(
        **{
            **value.__dict__,
            "macro": locked,
        }
    )

    result = RiskValidationEngine().assess(value)

    assert result.decision is RiskDecision.REJECTED
    assert any(issue.code == "macro_risk_block" for issue in result.issues)


def test_missing_account_equity_is_conditional() -> None:
    value = request()
    value = RiskRequest(
        **{
            **value.__dict__,
            "account_equity": None,
        }
    )

    result = RiskValidationEngine().assess(value)

    assert result.decision is RiskDecision.CONDITIONAL
    assert result.risk_amount is None


def test_no_trade_decision_is_rejected() -> None:
    value = request()
    blocked = DecisionResult(
        symbol="BTCUSDT",
        classification=DecisionClassification.NO_TRADE,
        direction=DecisionDirection.NONE,
        state=DecisionState.BLOCKED,
        conviction=0.0,
        long_score=0.0,
        short_score=0.0,
        grid_score=0.0,
        conflict_ratio=0.0,
        evidence=(),
        blockers=("conflict",),
        reasons=(),
    )
    value = RiskRequest(
        **{
            **value.__dict__,
            "decision": blocked,
        }
    )

    result = RiskValidationEngine().assess(value)

    assert result.decision is RiskDecision.REJECTED


def test_expired_signal_returns_structured_rejection() -> None:
    value = request()
    value = RiskRequest(
        **{
            **value.__dict__,
            "signal_expires_at": NOW - timedelta(seconds=1),
        }
    )

    result = RiskValidationEngine().assess(value)

    assert result.decision is RiskDecision.REJECTED
    assert any(issue.code == "signal_expired" for issue in result.issues)


def test_engine_remains_non_executable() -> None:
    result = RiskValidationEngine().assess(request())

    assert not hasattr(result, "order")
    assert not hasattr(result, "exchange")
    assert result.metadata["execution_enabled"] is False


def test_grid_geometry_is_validated_and_preserved() -> None:
    value = request()
    grid_decision = replace(
        value.decision,
        classification=DecisionClassification.GRID,
        direction=DecisionDirection.TWO_SIDED,
    )
    value = replace(
        value,
        decision=grid_decision,
        regime=replace(value.regime, state=RegimeState.RANGE),
        proposed_invalidation=98.0,
        proposed_target=102.0,
        proposed_grid_buy_levels=(99.0, 98.0, 97.0),
        proposed_grid_sell_levels=(101.0, 102.0, 103.0),
        proposed_grid_lower_invalidation=96.0,
        proposed_grid_upper_invalidation=104.0,
    )

    result = RiskValidationEngine().assess(value)

    assert result.decision is RiskDecision.APPROVED
    assert result.metadata["grid_plan"]["buy_levels"] == [99.0, 98.0, 97.0]
    assert result.metadata["grid_plan"]["sell_levels"] == [101.0, 102.0, 103.0]


def test_inverted_grid_geometry_is_rejected() -> None:
    value = request()
    value = replace(
        value,
        decision=replace(value.decision, classification=DecisionClassification.GRID, direction=DecisionDirection.TWO_SIDED),
        regime=replace(value.regime, state=RegimeState.RANGE),
        proposed_grid_buy_levels=(101.0, 102.0),
        proposed_grid_sell_levels=(99.0, 98.0),
        proposed_grid_lower_invalidation=97.0,
        proposed_grid_upper_invalidation=103.0,
    )

    result = RiskValidationEngine().assess(value)

    assert result.decision is RiskDecision.REJECTED
    assert any(issue.code == "invalid_grid_geometry" for issue in result.issues)
