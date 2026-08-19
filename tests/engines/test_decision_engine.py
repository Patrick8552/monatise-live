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
from monatise.engines.liquidity.models import (
    LiquidityAssessment,
    LiquidityLevel,
    LiquidityLevelType,
    LiquiditySide,
    LiquidityStrength,
)
from monatise.engines.liquidity_sweep.models import (
    SweepAssessment,
    SweepDirection,
    SweepEvent,
    SweepStatus,
)
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


def test_range_and_balanced_liquidity_never_produces_grid() -> None:
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

    assert result.classification is DecisionClassification.NO_TRADE
    assert result.direction is DecisionDirection.NONE


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


def test_two_sided_evidence_cannot_override_directional_conflict() -> None:
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
        state=RegimeState.UNSTABLE,
        confidence=RegimeConfidence.HIGH,
        score=0.85,
        reasons=(),
    )
    neutral_structure = MarketStructureAssessment(
        symbol=request.market.symbol,
        bias=StructureBias.NEUTRAL,
        state=StructureState.UNSTABLE,
        events=(),
        latest_event=None,
        swing_highs=(),
        swing_lows=(),
        confidence=0.75,
        reasons=(),
    )
    unavailable_order_flow = OrderFlowAssessment(**{
        **request.order_flow.__dict__,
        "bias": FlowBias.UNKNOWN,
        "participation": ParticipationState.UNKNOWN,
        "health": FlowHealth.UNAVAILABLE,
        "confidence": FlowConfidence.NONE,
        "score": 0.0,
        "execution_timing_score": 0.0,
        "inputs_used": 0,
    })
    qualified = DecisionRequest(**{
        **request.__dict__,
        "liquidity": balanced_liquidity,
        "regime": range_regime,
        "structure": neutral_structure,
        "order_flow": unavailable_order_flow,
        "minimum_signal_score": 7,
        "maximum_conflict_ratio": 0.0,
    })

    result = DecisionEngine().assess(qualified)

    assert "grid_signal_score" not in result.metadata
    assert result.classification is DecisionClassification.NO_TRADE
    assert result.direction is DecisionDirection.NONE
    assert result.state is DecisionState.BLOCKED
    assert result.grid_score == 0
    assert "order flow unavailable" in result.blockers
    assert "regime is unstable" in result.blockers
    assert "market structure is unstable" in result.blockers


def test_signal_score_override_does_not_beat_a_clean_stronger_trend() -> None:
    # Regime RANGE (no trend penalty on grid_score, unlike TREND_UP/DOWN),
    # but structure/order_flow/fibonacci are all clean, healthy, and
    # unambiguously bullish with zero conflicting evidence. No blockers are
    # present at all, so the minimum_signal_score override must not fire —
    # _classify()'s own directional_score > grid_score comparison should
    # stand. (bug: the override used to fire whenever grid_blockers was
    # empty, which is also true when there were never any blockers to
    # exempt in the first place, silently discarding a stronger trend call.)
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
        score=0.80,
        reasons=(),
    )
    strong_structure = MarketStructureAssessment(
        symbol=request.market.symbol,
        bias=StructureBias.BULLISH,
        state=StructureState.BULLISH_CONTINUATION,
        events=(),
        latest_event=None,
        swing_highs=(),
        swing_lows=(),
        confidence=0.95,
        reasons=(),
    )
    strong_order_flow = OrderFlowAssessment(**{
        **request.order_flow.__dict__,
        "bias": FlowBias.BULLISH,
        "score": 0.95,
        "execution_timing_score": 0.95,
    })
    strong_fibonacci = FibonacciAssessment(**{
        **request.fibonacci.__dict__,
        "primary_anchor": FibonacciAnchor(**{**request.fibonacci.primary_anchor.__dict__, "score": 0.90}),
    })
    qualified = DecisionRequest(**{
        **request.__dict__,
        "macro": None,  # isolate directional strength to structure/order_flow/fibonacci only
        "liquidity": balanced_liquidity,
        "regime": range_regime,
        "structure": strong_structure,
        "order_flow": strong_order_flow,
        "fibonacci": strong_fibonacci,
        "minimum_signal_score": 7,
        "maximum_conflict_ratio": 1.0,
    })

    result = DecisionEngine().assess(qualified)

    assert result.long_score > result.grid_score
    assert result.short_score == 0.0
    assert not result.blockers
    assert result.classification is DecisionClassification.TREND
    assert result.direction is DecisionDirection.LONG


def test_decision_engine_remains_non_executable() -> None:
    result = DecisionEngine().assess(base_request())

    assert not hasattr(result, "quantity")
    assert not hasattr(result, "order")
    assert not hasattr(result, "broker")
    assert result.metadata["execution_enabled"] is False


def test_invalid_sweep_contributes_no_score_only_neutral_weight() -> None:
    # A SweepStatus.INVALID event is one the sweep engine itself decided is
    # NOT a real sweep. It must not be scored the same as a real (if
    # unconfirmed) POSSIBLE sweep -- only diluting a direction's average via
    # its weight, never pushing it via a nonzero score.
    level = LiquidityLevel(
        price=100.0,
        side=LiquiditySide.SELL_SIDE,
        level_type=LiquidityLevelType.SWING_LOW,
        strength=LiquidityStrength.MEDIUM,
        touches=1,
        distance_pct=0.01,
        first_index=0,
        last_index=0,
    )
    invalid_event = SweepEvent(
        level=level,
        direction=SweepDirection.SELL_SIDE_TAKEN,
        status=SweepStatus.INVALID,
        candle_index=5,
        breach_price=99.5,
        close_price=100.2,
        breach_pct=0.005,
        wick_ratio=0.2,
        close_back_inside=True,
        reasons=("weak breach ratio",),
    )

    evidence: list = []
    request = DecisionRequest(**{
        **base_request().__dict__,
        "sweep": SweepAssessment(symbol="BTCUSDT", events=(invalid_event,), strongest_event=invalid_event, reasons=()),
    })
    DecisionEngine._sweep_evidence(request, evidence)

    assert len(evidence) == 1
    assert evidence[0].score == 0.0
    assert evidence[0].weight == 0.85
