from monatise.engines.portfolio_intelligence.engine import (
    PortfolioIntelligenceEngine,
)
from monatise.engines.portfolio_intelligence.models import (
    PortfolioHealth,
    PortfolioIntelligenceRequest,
    PortfolioPosition,
    PortfolioRiskFlag,
)


def position(
    position_id: str,
    symbol: str,
    side: str,
    notional: float,
    risk: float,
    leverage: float = 1.0,
    group: str | None = None,
    liquidity: str | None = None,
    expiry: float | None = None,
) -> PortfolioPosition:
    return PortfolioPosition(
        position_id=position_id,
        symbol=symbol,
        side=side,
        notional=notional,
        risk_amount=risk,
        leverage=leverage,
        correlation_group=group,
        liquidity_tier=liquidity,
        signal_expires_at_epoch=expiry,
    )


def test_healthy_portfolio() -> None:
    result = PortfolioIntelligenceEngine().assess(
        PortfolioIntelligenceRequest(
            total_equity=10_000,
            positions=(
                position("1", "BTCUSDT", "long", 1_000, 50, 1.5, "majors"),
                position("2", "ETHUSDT", "short", 800, 40, 1.2, "majors"),
            ),
        )
    )

    assert result.health in {
        PortfolioHealth.HEALTHY,
        PortfolioHealth.ELEVATED,
    }
    assert result.permits_new_allocation is True


def test_high_total_risk_blocks() -> None:
    result = PortfolioIntelligenceEngine().assess(
        PortfolioIntelligenceRequest(
            total_equity=10_000,
            positions=(
                position("1", "BTCUSDT", "long", 2_000, 400),
                position("2", "ETHUSDT", "long", 2_000, 300),
            ),
            maximum_total_risk_pct=0.05,
        )
    )

    assert PortfolioRiskFlag.HIGH_TOTAL_RISK in result.flags
    assert result.health in {
        PortfolioHealth.FRAGILE,
        PortfolioHealth.BLOCKED,
    }


def test_symbol_concentration_is_detected() -> None:
    result = PortfolioIntelligenceEngine().assess(
        PortfolioIntelligenceRequest(
            total_equity=10_000,
            positions=(
                position("1", "BTCUSDT", "long", 3_000, 100),
            ),
            maximum_symbol_notional_pct=0.20,
        )
    )

    assert PortfolioRiskFlag.SYMBOL_CONCENTRATION in result.flags


def test_correlation_cluster_is_detected() -> None:
    result = PortfolioIntelligenceEngine().assess(
        PortfolioIntelligenceRequest(
            total_equity=10_000,
            positions=(
                position("1", "SOLUSDT", "long", 2_000, 80, group="alts"),
                position("2", "SUIUSDT", "long", 2_000, 80, group="alts"),
            ),
            maximum_correlation_group_pct=0.30,
        )
    )

    assert PortfolioRiskFlag.CORRELATION_CLUSTER in result.flags


def test_expiry_cluster_is_detected() -> None:
    result = PortfolioIntelligenceEngine().assess(
        PortfolioIntelligenceRequest(
            total_equity=10_000,
            positions=(
                position("1", "BTCUSDT", "long", 1_000, 50, expiry=1000),
                position("2", "ETHUSDT", "short", 1_000, 50, expiry=1200),
            ),
            expiry_cluster_window_seconds=300,
        )
    )

    assert PortfolioRiskFlag.EXPIRY_CLUSTER in result.flags


def test_engine_is_read_only() -> None:
    result = PortfolioIntelligenceEngine().assess(
        PortfolioIntelligenceRequest(
            total_equity=10_000,
            positions=(),
        )
    )

    assert not hasattr(result, "order")
    assert not hasattr(result, "close_position")
    assert result.metadata["execution_enabled"] is False
