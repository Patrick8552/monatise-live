from monatise.core.models import OrderSide
from monatise.strategy.grid import Grid, GridConfig


def test_grid_builds_buy_and_sell_levels_around_center() -> None:
    levels = Grid(GridConfig(center_price=100, spacing_pct=0.01, levels_each_side=2)).levels()

    assert [level.price for level in levels] == [98, 99, 101, 102]
    assert [level.side for level in levels] == [
        OrderSide.BUY,
        OrderSide.BUY,
        OrderSide.SELL,
        OrderSide.SELL,
    ]


def test_grid_rejects_invalid_spacing() -> None:
    try:
        GridConfig(center_price=100, spacing_pct=0, levels_each_side=2).validate()
    except ValueError as error:
        assert "spacing_pct" in str(error)
    else:
        raise AssertionError("expected invalid spacing to fail")
