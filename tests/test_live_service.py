from monatise.adapters.hyperliquid import HyperliquidAdapter
from monatise.live.config import RuntimeConfig
from monatise.live.service import TradingService


class FakeMarketAdapter:
    def latest_price(self, symbol: str) -> float:
        assert symbol == "BTC"
        return 63_816.5


def test_live_tick_initializes_risk_baseline_from_live_mark() -> None:
    service = TradingService(
        RuntimeConfig(
            mode="live",
            network="mainnet",
            symbol="BTC",
            max_daily_loss=100,
            max_base_inventory=1,
        )
    )
    service._adapter = FakeMarketAdapter()

    service._live_tick()
    snapshot = service.snapshot()

    assert snapshot["markPrice"] == 63_816.5
    assert snapshot["riskStatus"] == "live dry-run"
    assert "max daily loss reached" not in [event["message"] for event in snapshot["events"]]
    assert snapshot["executionMode"] == "dry_run"
    assert "risk" in snapshot


def test_market_shock_guard_blocks_fast_mark_move() -> None:
    service = TradingService(
        RuntimeConfig(
            mode="live",
            network="testnet",
            symbol="BTC",
            max_mark_move_pct=0.01,
        )
    )
    service.state.last_mark_price = 100.0

    decision = service._market_guard(103.0, {})

    assert not decision.allowed
    assert "market shock guard" in decision.reason


def test_hyperliquid_order_values_are_rounded_for_wire_format() -> None:
    adapter = HyperliquidAdapter.__new__(HyperliquidAdapter)

    assert adapter._order_quantity(0.0041410259) == 0.00414
    assert adapter._order_price(61919.54321) == 61919.5
