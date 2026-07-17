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

CoinGlass can provide crypto futures candles and derivatives context when a subscription is active:

```bash
COINGLASS_API_KEY=...
COINGLASS_EXCHANGE=Binance
COINGLASS_EXCHANGE_LIST=Binance,OKX,Bybit
```

When CoinGlass is unavailable, select Hyperliquid's public candle snapshot feed:

```bash
MONATISE_DATA_FEED=hyperliquid
```

Hyperliquid then supplies crypto prices and candles as well as remaining the execution/private-sync adapter. CoinGlass-only funding, open-interest, liquidation, and fear/greed fields remain unavailable; they are never interpreted as zero or neutral.

Dashboard and market-analysis GET routes are temporarily open without login. OpenClaw still uses the separate bearer-protected `GET /api/openclaw/status` route, which is structurally read-only and cannot place orders, change configuration, or deploy. Configure its secret only in Render and OpenClaw:

```bash
MONATISE_OPENCLAW_TOKEN=use-a-long-random-secret
```

USDC billing can gate paid product access later, but login and payment gates are
currently disabled. The app creates an isolated guest session automatically so
the dashboard and its actions work without registration. Do not treat that guest
session as an authorization boundary.
Configure the Stripe price as the USDC private plan, add real Stripe values only
in Render or a local `.env`, then point the Stripe webhook at `/api/stripe/webhook`:

USDC payments are routed on Solana only. The live payment destination is
`69aNnKVjSin6x2HYqMgu9FsWawWDiRxohGfZw8efGjue`, configurable with
`MONATISE_USDC_SOLANA_ADDRESS`.

```bash
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PRIVATE_PRICE_ID=price_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

Paid users can then connect supported commercial APIs from inside the platform,
including a commercial CoinGlass key for market-data proxy routes and other
dashboard connectors. Unpaid users receive `402 Payment Required` for platform
APIs.

Backpack is present as an exchange-aware scaffold for market data and ED25519
private request signing:

```bash
MONATISE_EXCHANGE=hyperliquid
BACKPACK_REST_BASE=https://api.backpack.exchange
BACKPACK_API_KEY=...
BACKPACK_SECRET_KEY=...
BACKPACK_SYMBOL_MAP=BTC=BTC_USDC_PERP,ETH=ETH_USDC_PERP,SOL=SOL_USDC_PERP
```

Backpack live execution is intentionally disabled until account permissions,
symbol mapping, fills, cancellation behavior, and risk handling are reviewed.
Monatise will not route orders to Backpack from this scaffold.

Chainlink or another oracle can be added as a signal validation guard: read the BTC/USD or ETH/USD feed from a configured RPC, compare it with the CoinGlass mark, check the feed timestamp, and hold or reduce confidence when the spread or freshness check fails. The oracle should verify signals; it should not replace CoinGlass candles or Hyperliquid execution.

Quiver Quantitative can be enabled as an optional stock/ETF alternative-data
context layer. Set `QUIVER_API_KEY` in Render to let Monatise show Congress,
insider, government contract, lobbying, off-exchange, and Quiver news context
for watch assets such as `AAPL`, `TSLA`, `NVDA`, `QQQ`, and `SPY`. Quiver does
not place orders and does not override signal geometry, stops, or execution
gates.

See [deploy/live-runbook.md](deploy/live-runbook.md) for the full runbook.

## Render Hosting

Render is the active hosting target for Monatise. The included `render.yaml`
deploys the Docker web service in `live` + `mainnet` mode with small risk caps.
Users log in and save their own Hyperliquid API wallet credentials in the
dashboard before starting the trading loop.

Password recovery sends a six-digit email code, so Render also needs SMTP
configured. Monatise supports plain SMTP plus provider presets for Resend and
Postmark. Keep these values in Render secrets, not in the browser.

```text
MONATISE_SMTP_PROVIDER=resend
MONATISE_SMTP_FROM=Monatise <no-reply@yourdomain.com>
MONATISE_SMTP_PASSWORD=re_your_resend_api_key
MONATISE_ALERT_EMAILS=ops@yourdomain.com,trader@yourdomain.com
```

Resend SMTP defaults are applied automatically when
`MONATISE_SMTP_PROVIDER=resend`: host `smtp.resend.com`, port `587`, username
`resend`, password set to your Resend API key, and STARTTLS enabled.

For Postmark:

```text
MONATISE_SMTP_PROVIDER=postmark
MONATISE_SMTP_FROM=Monatise <no-reply@yourdomain.com>
MONATISE_SMTP_USERNAME=server-api-token-or-smtp-access-key
MONATISE_SMTP_PASSWORD=server-api-token-or-smtp-secret-key
MONATISE_SMTP_STREAM=outbound
MONATISE_ALERT_EMAILS=ops@yourdomain.com,trader@yourdomain.com
```

Postmark SMTP defaults are applied automatically when
`MONATISE_SMTP_PROVIDER=postmark`: host `smtp.postmarkapp.com`, port `587`, and
STARTTLS enabled. `MONATISE_SMTP_STREAM` is sent as the Postmark message stream
header.

Generic SMTP remains available:

```text
MONATISE_SMTP_HOST=smtp.example.com
MONATISE_SMTP_PORT=587
MONATISE_SMTP_FROM=Monatise <no-reply@example.com>
MONATISE_SMTP_USERNAME=apikey-or-mailbox
MONATISE_SMTP_PASSWORD=secret
MONATISE_SMTP_STARTTLS=true
MONATISE_SMTP_SSL=false
```

When `MONATISE_ALERT_EMAILS` is set, accepted TradingView webhooks also send
email notifications through the same SMTP provider.

TradingView indicator alerts can be added as a forex, metals, indices, stocks,
and crypto confluence feed. Do not enter TradingView login credentials into
Monatise; TradingView Premium connects through alert webhooks. Configure
Render with:

```text
MONATISE_TRADINGVIEW_WEBHOOK_TOKEN=use-a-long-random-secret
```

Then set the TradingView webhook URL to:

```text
https://monatise-live.onrender.com/api/tradingview/webhook?token=YOUR_SECRET
```

Accepted TradingView alerts are classified as the primary signal feed for
metals, forex, stocks, indices, and other watch assets. A fresh alert can drive
the displayed price, setup, grid levels, and hedge plan, but it still cannot
directly place live orders. TradingView uses a 5-minute freshness check and a
15-minute setup lock, while Monatise keeps execution behind risk limits,
invalidation rules, and the private execution gate.

Use a JSON alert message like:

```json
{
  "symbol": "{{ticker}}",
  "action": "BUY",
  "confidence": 78,
  "indicator": "My TradingView setup",
  "timeframe": "{{interval}}",
  "price": "{{close}}",
  "entry": "{{close}}",
  "stop": 4125,
  "target1": 4185,
  "target2": 4215,
  "grid": [
    { "side": "buy", "price": 4145, "label": "support" },
    { "side": "sell", "price": 4185, "label": "target" }
  ],
  "hedgeSide": "SHORT",
  "hedgeRatio": 35,
  "hedgeTrigger": 4138,
  "hedgeRelease": 4175
}
```

Recommended TradingView symbols include `OANDA:XAUUSD` for Gold, `OANDA:XAGUSD`
for Silver, `TVC:SPX`, `TVC:NDX`, `NASDAQ:AAPL`, `NASDAQ:TSLA`, and
`NASDAQ:NVDA`. Monatise normalizes exchange-prefixed alert symbols before
matching them to its watchlist.

For Gold, include the TradingView indicator stack in the alert body when your
Pine alert has those states available:

```json
{
  "symbol": "{{ticker}}",
  "action": "SELL",
  "confidence": 78,
  "indicator": "Gold TradingView stack",
  "timeframe": "{{interval}}",
  "price": "{{close}}",
  "indicators": {
    "luxalgo": "sell",
    "historical_color": "bearish",
    "liquidity_swings": "lower high",
    "wick_extremity": "bearish rejection",
    "equal_highs_lows": "equal highs swept",
    "liquidity_grabs": "bearish grab",
    "dynamic_trend_pivot": "below pivot",
    "auto_fib": "below 0.618",
    "daily_vwap": "below",
    "volume_profile": "below value area",
    "htf_levels": "below resistance",
    "rsi_sma_cross": "cross down"
  }
}
```

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
