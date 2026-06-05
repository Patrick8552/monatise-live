# Monatise Software Architecture

This workspace now contains a local-first implementation of the Monatise liquidity harvesting framework.

## Design Principle

The harvesting engine is independent from exchange APIs. APIs can be added later as adapters that implement the market data and execution ports.

## Main Components

- `monatise.core.models`: candles, orders, fills, portfolio accounting, and inventory metrics.
- `monatise.core.ports`: future adapter interfaces for market data and execution.
- `monatise.strategy.grid`: grid level generation around a center price.
- `monatise.strategy.harvester`: inventory-aware order planning and paired harvest accounting.
- `monatise.sim.engine`: offline candle backtesting engine.
- `monatise.cli`: command line simulation runner.
- `app`: visual local dashboard for grid controls, liquidity map, fill tape, portfolio metrics, and equity curve.
- `monatise.live`: backend service for paper/live trading loops.
- `monatise.adapters.hyperliquid`: Hyperliquid adapter using the official Python SDK.
- `examples/sample_prices.csv`: sample candle data.
- `examples/run_simulation.py`: runnable example.

## Current Flow

1. Load candles from CSV.
2. Initialize a portfolio with quote and base inventory.
3. Build a `LiquidityHarvesterConfig`.
4. Generate grid orders around the latest mark price.
5. Simulate candle fills when high/low crosses grid prices.
6. Apply fills to the portfolio.
7. Track realized harvest, fees, inventory, and final equity.

## Future API Integration

Add exchange integrations by implementing:

- `MarketDataPort.latest_price`
- `MarketDataPort.candles`
- `ExecutionPort.place_orders`
- `ExecutionPort.cancel_orders`
- `ExecutionPort.fills`

The strategy should continue to call the same core methods:

- `LiquidityHarvester.plan_orders`
- `LiquidityHarvester.record_fill`

That keeps the protocol logic stable while allowing multiple exchange backends.

## Local Dashboard

Run:

```bash
python3 -m http.server 4173 --directory app
```

Open:

```text
http://localhost:4173
```

The dashboard is static and local-first. It does not require exchange APIs, package installation, or a backend service.

## Backend-Powered Dashboard

Run:

```bash
MONATISE_MODE=paper python3 scripts/serve_live.py
```

Open:

```text
http://127.0.0.1:4174
```

This serves the same dashboard with `/api/status`, `/api/start`, and `/api/stop`.
