import pytest

from monatise.core.models import Fill, OrderSide, Portfolio
from monatise.strategy.harvester import LiquidityHarvester, LiquidityHarvesterConfig


def test_harvester_plans_affordable_orders() -> None:
    harvester = LiquidityHarvester(
        LiquidityHarvesterConfig(
            symbol="BTC-USD",
            center_price=100,
            spacing_pct=0.01,
            levels_each_side=2,
            order_quote_size=50,
            fee_rate=0,
        )
    )

    orders = harvester.plan_orders(Portfolio(quote=100, base=1), mark_price=100)

    assert len(orders) == 4
    assert {order.side for order in orders} == {OrderSide.BUY, OrderSide.SELL}


def test_harvester_funds_nearest_buy_levels_first_when_capital_is_limited() -> None:
    # Limited capital must fund the levels closest to market (most likely to
    # actually fill) before farther, less useful ones.
    harvester = LiquidityHarvester(
        LiquidityHarvesterConfig(
            symbol="BTC-USD",
            center_price=100,
            spacing_pct=0.01,
            levels_each_side=5,
            order_quote_size=100,
            fee_rate=0,
        )
    )

    orders = harvester.plan_orders(Portfolio(quote=250, base=0), mark_price=100)
    buy_levels = [order.level_id for order in orders if order.side is OrderSide.BUY]

    assert buy_levels == ["buy-1", "buy-2"]


def test_harvester_respects_inventory_skew() -> None:
    harvester = LiquidityHarvester(
        LiquidityHarvesterConfig(
            symbol="BTC-USD",
            center_price=100,
            spacing_pct=0.01,
            levels_each_side=2,
            order_quote_size=50,
            target_inventory_ratio=0.5,
            max_inventory_skew=0.1,
        )
    )

    orders = harvester.plan_orders(Portfolio(quote=10_000, base=0), mark_price=100)

    assert orders
    assert all(order.side is OrderSide.BUY for order in orders)


def test_harvester_records_paired_harvest() -> None:
    harvester = LiquidityHarvester(
        LiquidityHarvesterConfig(symbol="BTC-USD", center_price=100, fee_rate=0)
    )
    portfolio = Portfolio(quote=1_000, base=0)

    harvester.record_fill(
        Fill("1", "BTC-USD", OrderSide.BUY, 99, 1, 0, "t1", "buy-1"),
        portfolio,
    )
    harvester.record_fill(
        Fill("2", "BTC-USD", OrderSide.SELL, 101, 1, 0, "t2", "sell-1"),
        portfolio,
    )

    assert portfolio.realized_harvest == 2
    assert portfolio.quote == 1_002
    assert portfolio.base == 0


def test_harvester_keeps_leftover_quantity_from_a_partial_match() -> None:
    # Buy and sell quantities almost never match exactly (they're computed
    # from order_quote_size / price at two different price levels) -- a
    # smaller sell must not silently discard the buy's unmatched remainder.
    harvester = LiquidityHarvester(
        LiquidityHarvesterConfig(symbol="BTC-USD", center_price=100, fee_rate=0)
    )
    portfolio = Portfolio(quote=1_000, base=1)

    harvester.record_fill(
        Fill("1", "BTC-USD", OrderSide.BUY, 99, 1.0, 0.4, "t1", "buy-1"),
        portfolio,
    )
    # Partial sell: only 0.6 of the 1.0 bought quantity.
    harvester.record_fill(
        Fill("2", "BTC-USD", OrderSide.SELL, 101, 0.6, 0.24, "t2", "sell-1"),
        portfolio,
    )

    # Matched portion: (101-99)*0.6 - (0.4*0.6 + 0.24) = 1.2 - 0.48 = 0.72
    assert portfolio.realized_harvest == pytest.approx(0.72)
    # The remaining 0.4 buy quantity (with its proportional fee) must still
    # be tracked, not dropped.
    remainder = harvester._matched_buys["buy-1"]
    assert remainder.quantity == pytest.approx(0.4)
    assert remainder.fee == pytest.approx(0.16)

    # A later sell that exactly matches the remainder completes the harvest
    # for it too -- nothing was permanently lost.
    harvester.record_fill(
        Fill("3", "BTC-USD", OrderSide.SELL, 102, 0.4, 0.0, "t3", "sell-1"),
        portfolio,
    )
    assert portfolio.realized_harvest == pytest.approx(0.72 + 1.04)
    assert "buy-1" not in harvester._matched_buys


def test_harvester_tracks_excess_sell_quantity_for_a_later_buy() -> None:
    # Symmetric case: a sell arrives with more quantity than any tracked
    # buy at the paired level (or none at all) -- the excess must wait for
    # a future buy instead of vanishing.
    harvester = LiquidityHarvester(
        LiquidityHarvesterConfig(symbol="BTC-USD", center_price=100, fee_rate=0)
    )
    portfolio = Portfolio(quote=1_000, base=1)

    harvester.record_fill(
        Fill("1", "BTC-USD", OrderSide.SELL, 101, 1.0, 0.0, "t1", "sell-1"),
        portfolio,
    )
    assert harvester._unmatched_sells["sell-1"].quantity == pytest.approx(1.0)
    assert portfolio.realized_harvest == 0

    harvester.record_fill(
        Fill("2", "BTC-USD", OrderSide.BUY, 99, 1.0, 0.0, "t2", "buy-1"),
        portfolio,
    )
    assert portfolio.realized_harvest == pytest.approx(2.0)
    assert "sell-1" not in harvester._unmatched_sells
