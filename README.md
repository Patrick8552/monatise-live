# Monatise

Monatise is a liquidity harvesting framework and protocol for grid-based trading strategies.

It is built around repeated liquidity placement, spread capture, volatility harvesting, and inventory-aware rebalancing. It is not a trend-style one-shot entry system.

## What Works Now

- Define a grid around a market price.
- Generate buy/sell liquidity orders from grid levels.
- Simulate fills against candle data.
- Track quote/base inventory, realized harvest PnL, fees, and equity.
- Run a local example without exchange APIs.
- Use a local visual dashboard for simulation controls, grid state, fills, inventory, and equity.

## Visual Dashboard

Start the local web app:

```bash
python3 -m http.server 4173 --directory app
```

Then open:

```text
http://localhost:4173
```

The dashboard runs entirely in the browser using sample candle data. Change the grid spacing, levels, portfolio balances, fee rate, and candle CSV, then use `Run` or `Step` to inspect the liquidity harvesting cycle.

## Paper And Live Backend

Start the backend-powered dashboard:

```bash
MONATISE_MODE=paper python3 scripts/serve_live.py
```

Then open:

```text
http://127.0.0.1:4174
```

Use the `Backend` Start/Stop controls for the running paper/live loop. Real Hyperliquid trading requires the live dependency and environment variables in `.env.example`.

Install live dependencies:

```bash
pip install -r requirements-live.txt
```

Live mode stays disabled unless all real-order gates are present:

```bash
MONATISE_MODE=live
MONATISE_NETWORK=testnet
MONATISE_ALLOW_LIVE_ORDERS=true
MONATISE_LIVE_CONFIRMATION=I_UNDERSTAND_REAL_MONEY
HYPERLIQUID_ACCOUNT_ADDRESS=0x...
HYPERLIQUID_SECRET_KEY=...
```

Optional CoinGlass read-only data feeds can be enabled for crypto futures candles and context metrics:

```bash
MONATISE_DATA_FEED=coinglass
COINGLASS_API_KEY=...
COINGLASS_EXCHANGE=Binance
COINGLASS_EXCHANGE_LIST=Binance,OKX,Bybit
```

CoinGlass is used only for market data. Hyperliquid remains the execution and private sync adapter.

See [deploy/live-runbook.md](deploy/live-runbook.md) for the full runbook.

## Render Hosting

Render is the active hosting target for Monatise. The included `render.yaml`
deploys the Docker web service in `live` + `mainnet` mode with small risk caps.
Users log in and save their own Hyperliquid API wallet credentials in the
dashboard before starting the trading loop.

See [deploy/render-hosting.md](deploy/render-hosting.md) for details.

## Quick Start

```bash
python3 examples/run_simulation.py
```

Or through the CLI:

```bash
python3 -m monatise.cli examples/sample_prices.csv
```

## Tests

GitHub runs the pytest suite on pushes and pull requests to `main`.

```bash
python3 -m pytest
```

The legacy runner delegates to pytest:

```bash
python3 tests/run_tests.py
```

## Architecture

The current framework is deliberately local-first:

- `monatise.core`: domain models, orders, portfolio accounting, protocol ports.
- `monatise.strategy`: grid and liquidity harvesting logic.
- `monatise.sim`: offline candle simulator.
- `monatise.adapters`: future home for exchange, data, and execution adapters.
- `app`: local browser dashboard for visual simulation.

Exchange APIs can be added later by implementing the `MarketDataPort` and `ExecutionPort` interfaces in `monatise.core.ports`.

## Positioning

Monatise harvests liquidity through grid-based market participation, not one-shot trend entries.
