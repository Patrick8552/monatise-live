from monatise.engines.order_flow.engine import OrderFlowIntelligenceEngine
from monatise.engines.order_flow.models import (
    FlowBias,
    FlowHealth,
    FlowInput,
    OrderFlowRequest,
    ParticipationState,
)


def test_institutional_buying_is_detected() -> None:
    result = OrderFlowIntelligenceEngine().assess(
        OrderFlowRequest(
            symbol="BTCUSDT",
            flow=FlowInput(
                open_interest_change_pct=1.5,
                price_change_pct=1.0,
                cvd_change=0.8,
                footprint_delta=0.7,
                large_trade_net_usd=2_000_000,
                bid_ask_imbalance=0.35,
            ),
        )
    )

    assert result.bias is FlowBias.BULLISH
    assert result.participation is ParticipationState.INSTITUTIONAL_BUYING
    assert result.health is FlowHealth.HEALTHY
    assert result.execution_timing_score > 0


def test_long_liquidation_is_detected() -> None:
    result = OrderFlowIntelligenceEngine().assess(
        OrderFlowRequest(
            symbol="ETHUSDT",
            flow=FlowInput(
                open_interest_change_pct=-2.0,
                price_change_pct=-3.0,
                cvd_change=-0.8,
                liquidation_long_usd=5_000_000,
                liquidation_short_usd=300_000,
            ),
        )
    )

    assert result.participation is ParticipationState.LONG_LIQUIDATION
    assert result.bias is FlowBias.BEARISH


def test_rising_oi_without_price_progress_is_trapped() -> None:
    result = OrderFlowIntelligenceEngine().assess(
        OrderFlowRequest(
            symbol="SOLUSDT",
            flow=FlowInput(
                open_interest_change_pct=2.0,
                price_change_pct=0.01,
                cvd_change=0.2,
                bid_ask_imbalance=0.1,
            ),
        )
    )

    assert result.health is FlowHealth.TRAPPED


def test_missing_inputs_are_not_treated_as_zero() -> None:
    result = OrderFlowIntelligenceEngine().assess(
        OrderFlowRequest(
            symbol="BTCUSDT",
            flow=FlowInput(
                cvd_change=0.4,
            ),
            minimum_inputs=3,
        )
    )

    assert result.bias is FlowBias.UNKNOWN
    assert result.health is FlowHealth.UNAVAILABLE
    assert result.inputs_used == 1


def test_engine_remains_non_executable() -> None:
    result = OrderFlowIntelligenceEngine().assess(
        OrderFlowRequest(
            symbol="BTCUSDT",
            flow=FlowInput(
                open_interest_change_pct=1.0,
                price_change_pct=0.5,
                cvd_change=0.5,
            ),
        )
    )

    assert not hasattr(result, "entry")
    assert not hasattr(result, "stop_loss")
    assert not hasattr(result, "target")
    assert not hasattr(result, "order")
