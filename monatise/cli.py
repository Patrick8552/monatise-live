from __future__ import annotations

import argparse

from monatise.core.models import Portfolio
from monatise.sim.csv_data import load_candles
from monatise.sim.engine import BacktestEngine
from monatise.strategy.harvester import LiquidityHarvester, LiquidityHarvesterConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local Monatise liquidity harvesting simulation.")
    parser.add_argument("csv", help="CSV with timestamp,open,high,low,close[,volume] columns")
    parser.add_argument("--symbol", default="BTC-USD")
    parser.add_argument("--quote", type=float, default=10_000)
    parser.add_argument("--base", type=float, default=0.05)
    parser.add_argument("--spacing-pct", type=float, default=0.005)
    parser.add_argument("--levels", type=int, default=5)
    parser.add_argument("--order-quote-size", type=float, default=250)
    parser.add_argument("--fee-rate", type=float, default=0.0004)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    candles = load_candles(args.csv)
    if not candles:
        raise SystemExit("no candles found")

    config = LiquidityHarvesterConfig(
        symbol=args.symbol,
        center_price=candles[0].open,
        spacing_pct=args.spacing_pct,
        levels_each_side=args.levels,
        order_quote_size=args.order_quote_size,
        fee_rate=args.fee_rate,
    )
    portfolio = Portfolio(quote=args.quote, base=args.base)
    engine = BacktestEngine(LiquidityHarvester(config), portfolio)
    result = engine.run(candles)

    first_equity = args.quote + (args.base * candles[0].open)
    print("Monatise liquidity harvesting simulation")
    print(f"symbol={args.symbol}")
    print(f"candles={len(candles)} fills={len(result.fills)}")
    print(f"initial_equity={first_equity:.2f}")
    print(f"final_equity={result.final_equity:.2f}")
    print(f"realized_harvest={portfolio.realized_harvest:.2f}")
    print(f"fees_paid={portfolio.fee_paid:.2f}")
    print(f"quote={portfolio.quote:.2f} base={portfolio.base:.10f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
