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
