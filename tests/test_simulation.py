from monatise.core.models import Candle, Portfolio
from monatise.sim.engine import BacktestEngine
from monatise.strategy.harvester import LiquidityHarvester, LiquidityHarvesterConfig


def test_backtest_engine_runs_grid_harvest_cycle() -> None:
    harvester = LiquidityHarvester(
        LiquidityHarvesterConfig(
            symbol="BTC-USD",
            center_price=100,
            spacing_pct=0.01,
            levels_each_side=1,
            order_quote_size=99,
            fee_rate=0,
            max_inventory_skew=0.5,
        )
    )
    engine = BacktestEngine(harvester, Portfolio(quote=1_000, base=1))

    result = engine.run(
        [
            Candle("t1", open=100, high=100, low=98, close=99),
            Candle("t2", open=99, high=102, low=99, close=101),
        ]
    )

    assert len(result.fills) >= 2
    assert result.final_equity > 0
    assert result.final_portfolio is not None
