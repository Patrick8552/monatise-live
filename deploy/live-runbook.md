# Monatise Live production runbook

Monatise Live is an analysis-only Render service. `render.yaml` is the canonical
deployment definition.

## Safety invariants

- `MONATISE_EXECUTION_MODE=disabled`
- `MONATISE_ALLOW_LIVE_ORDERS=false`
- The application-level `RuntimeConfig.live_enabled` property always returns false.
- Starting the trading service returns an analysis-only warning and never starts
  an order loop.
- CoinGlass is the preferred primary source; Hyperliquid public data is fallback.
- No trade signals are generated on weekends.

## Verification

Run before deployment:

```bash
python3 -m pytest -q
node --check app/app.js
```

Then verify `/api/health`, `/api/assets`, and a candle/analysis request on the
Render URL. Confirm the operator status reports `executionMode: disabled`,
`allowLiveOrders: false`, and no Stripe/billing integration.
