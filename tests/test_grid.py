from monatise.core.models import OrderSide
from monatise.strategy.grid import Grid, GridConfig


def test_grid_builds_buy_and_sell_levels_around_center() -> None:
    levels = Grid(GridConfig(center_price=100, spacing_pct=0.01, levels_each_side=2)).levels()

    assert [level.price for level in levels] == [99, 98, 101, 102]
    assert [level.side for level in levels] == [
        OrderSide.BUY,
        OrderSide.BUY,
        OrderSide.SELL,
        OrderSide.SELL,
    ]


def test_grid_levels_are_ordered_nearest_to_market_first_on_both_sides() -> None:
    # plan_orders() reserves capital in this order -- nearest (most likely
    # to fill) levels must be funded before farther ones.
    levels = Grid(GridConfig(center_price=100, spacing_pct=0.01, levels_each_side=5)).levels()

    buy_ids = [level.level_id for level in levels if level.side is OrderSide.BUY]
    sell_ids = [level.level_id for level in levels if level.side is OrderSide.SELL]
    assert buy_ids == ["buy-1", "buy-2", "buy-3", "buy-4", "buy-5"]
    assert sell_ids == ["sell-1", "sell-2", "sell-3", "sell-4", "sell-5"]


def test_grid_rejects_invalid_spacing() -> None:
    try:
        GridConfig(center_price=100, spacing_pct=0, levels_each_side=2).validate()
    except ValueError as error:
        assert "spacing_pct" in str(error)
    else:
        raise AssertionError("expected invalid spacing to fail")
