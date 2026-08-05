from datetime import datetime, timezone

from monatise.engines.decision.engine import DecisionEngine
from monatise.engines.decision.models import (
    DecisionClassification,
    DecisionDirection,
    DecisionRequest,
    DecisionState,
)
from monatise.engines.fibonacci_liquidity.models import (
    AnchorQuality,
    FibonacciAnchor,
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
from monatise.engines.supply_demand.models import ZoneAssessment


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def market() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="BTCUSDT",
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


def base_request() -> DecisionRequest:
    symbol = "BTCUSDT"

    macro = MacroAssessment(
        symbol=symbol,
        bias=MacroBias.BULLISH,
        risk_state=MacroRiskState.NORMAL,
        conviction=0.70,
        score=0.60,
        reasons=(),
    )

    regime = RegimeAssessment(
        symbol=symbol,
        state=RegimeState.TREND_UP,
        confidence=RegimeConfidence.HIGH,
        score=0.80,
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

    anchor = FibonacciAnchor(
        direction=FibonacciDirection.BULLISH,
        start_index=1,
        end_index=10,
        start_price=90,
        end_price=110,
        range_size=20,
        range_atr_multiple=4,
        age_candles=2,
        structure_confidence=0.85,
        reclaim_aligned=False,
        quality=AnchorQuality.HIGH,
        score=0.80,
        reasons=(),
    )

    fibonacci = FibonacciAssessment(
        symbol=symbol,
        direction=FibonacciDirection.BULLISH,
        primary_anchor=anchor,
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
        score=0.85,
        execution_timing_score=0.80,
        inputs_used=6,
        reasons=(),
        normalized_inputs={},
    )

    return DecisionRequest(
        market=market(),
        macro=macro,
        regime=regime,
        liquidity=liquidity,
        sweep=sweep,
        zones=zones,
        reclaim=reclaim,
        structure=structure,
        fibonacci=fibonacci,
        order_flow=order_flow,
    )


def test_aligned_directional_evidence_produces_trend() -> None:
    result = DecisionEngine().assess(base_request())

    assert result.classification is DecisionClassification.TREND
    assert result.direction is DecisionDirection.LONG
    assert result.state is DecisionState.APPROVED_FOR_RISK_REVIEW
    assert result.passes_to_risk_engine is True


def test_macro_event_lock_forces_no_trade() -> None:
    request = base_request()
    locked_macro = MacroAssessment(
        symbol="BTCUSDT",
        bias=MacroBias.BULLISH,
        risk_state=MacroRiskState.EVENT_LOCK,
        conviction=0.8,
        score=0.8,
        reasons=("CPI lock",),
    )

    request = DecisionRequest(
        **{
            **request.__dict__,
            "macro": locked_macro,
        }
    )

    result = DecisionEngine().assess(request)

    assert result.classification is DecisionClassification.NO_TRADE
    assert result.state is DecisionState.BLOCKED
    assert any("event lock" in blocker for blocker in result.blockers)


def test_range_and_balanced_liquidity_can_produce_grid() -> None:
    request = base_request()

    balanced_liquidity = LiquidityAssessment(
        symbol="BTCUSDT",
        current_price=100.0,
        buy_side_levels=(object(),),
        sell_side_levels=(object(),),
        nearest_buy_side=object(),
        nearest_sell_side=object(),
        reasons=(),
    )

    range_regime = RegimeAssessment(
        symbol="BTCUSDT",
        state=RegimeState.RANGE,
        confidence=RegimeConfidence.HIGH,
        score=0.85,
        reasons=(),
    )

    neutral_structure = MarketStructureAssessment(
        symbol="BTCUSDT",
        bias=StructureBias.NEUTRAL,
        state=StructureState.RANGE,
        events=(),
        latest_event=None,
        swing_highs=(),
        swing_lows=(),
        confidence=0.75,
        reasons=(),
    )

    request = DecisionRequest(
        **{
            **request.__dict__,
            "liquidity": balanced_liquidity,
            "regime": range_regime,
            "structure": neutral_structure,
            "minimum_conviction": 0.50,
        }
    )

    result = DecisionEngine().assess(request)

    assert result.classification is DecisionClassification.GRID
    assert result.direction is DecisionDirection.TWO_SIDED


def test_conflicting_directional_evidence_can_block() -> None:
    request = base_request()

    bearish_order_flow = OrderFlowAssessment(
        symbol="BTCUSDT",
        bias=FlowBias.BEARISH,
        participation=ParticipationState.INSTITUTIONAL_SELLING,
        health=FlowHealth.HEALTHY,
        confidence=FlowConfidence.HIGH,
        score=0.95,
        execution_timing_score=0.95,
        inputs_used=7,
        reasons=(),
        normalized_inputs={},
    )

    request = DecisionRequest(
        **{
            **request.__dict__,
            "order_flow": bearish_order_flow,
            "maximum_conflict_ratio": 0.20,
        }
    )

    result = DecisionEngine().assess(request)

    assert result.classification is DecisionClassification.NO_TRADE
    assert result.state is DecisionState.BLOCKED


def test_signed_signal_score_threshold_blocks_weak_directional_trade() -> None:
    request = base_request()
    result = DecisionEngine().assess(DecisionRequest(**{**request.__dict__, "minimum_signal_score": 10}))

    assert result.classification is DecisionClassification.NO_TRADE
    assert result.state is DecisionState.BLOCKED
    assert abs(result.metadata["signed_signal_score"]) < 10
    assert result.metadata["minimum_signal_score"] == 10


def test_signed_signal_score_threshold_allows_qualified_directional_trade() -> None:
    request = base_request()
    baseline = DecisionEngine().assess(request)
    threshold = abs(baseline.metadata["signed_signal_score"])
    result = DecisionEngine().assess(DecisionRequest(**{**request.__dict__, "minimum_signal_score": threshold}))

    assert result.classification is DecisionClassification.TREND
    assert result.state is DecisionState.APPROVED_FOR_RISK_REVIEW


def test_qualified_grid_score_takes_priority_over_directional_conflict() -> None:
    request = base_request()
    balanced_liquidity = LiquidityAssessment(
        symbol=request.market.symbol,
        current_price=100.0,
        buy_side_levels=(object(),),
        sell_side_levels=(object(),),
        nearest_buy_side=object(),
        nearest_sell_side=object(),
        reasons=(),
    )
    range_regime = RegimeAssessment(
        symbol=request.market.symbol,
        state=RegimeState.RANGE,
        confidence=RegimeConfidence.HIGH,
        score=0.85,
        reasons=(),
    )
    neutral_structure = MarketStructureAssessment(
        symbol=request.market.symbol,
        bias=StructureBias.NEUTRAL,
        state=StructureState.RANGE,
        events=(),
        latest_event=None,
        swing_highs=(),
        swing_lows=(),
        confidence=0.75,
        reasons=(),
    )
    qualified = DecisionRequest(**{
        **request.__dict__,
        "liquidity": balanced_liquidity,
        "regime": range_regime,
        "structure": neutral_structure,
        "minimum_signal_score": 7,
        "maximum_conflict_ratio": 0.0,
    })

    result = DecisionEngine().assess(qualified)

    assert result.metadata["grid_signal_score"] >= 7
    assert result.classification is DecisionClassification.GRID
    assert result.direction is DecisionDirection.TWO_SIDED
    assert result.state is DecisionState.APPROVED_FOR_RISK_REVIEW


def test_decision_engine_remains_non_executable() -> None:
    result = DecisionEngine().assess(base_request())

    assert not hasattr(result, "quantity")
    assert not hasattr(result, "order")
    assert not hasattr(result, "broker")
    assert result.metadata["execution_enabled"] is False
