# Monatise Live Trading Runbook

## Required Accounts And Keys

1. Create or use a Hyperliquid account.
2. Create an API wallet at `https://app.hyperliquid.xyz/API`.
3. Keep the main wallet address as `HYPERLIQUID_ACCOUNT_ADDRESS`.
4. Keep the API wallet private key as `HYPERLIQUID_SECRET_KEY`.
5. Fund the correct environment: testnet first, then mainnet only after verification.

## Install Live Dependency

```bash
pip install -r requirements-live.txt
```

## Start Paper Backend

```bash
MONATISE_MODE=paper python3 scripts/serve_live.py
```

Open:

```text
http://127.0.0.1:4174
```

## Start Live Dry Run

Live dry run reads market prices and plans orders, but does not place orders:

```bash
MONATISE_MODE=live \
MONATISE_NETWORK=testnet \
HYPERLIQUID_ACCOUNT_ADDRESS=0x... \
HYPERLIQUID_SECRET_KEY=... \
python3 scripts/serve_live.py
```

## Enable Real Orders

Real orders require all gates:

```bash
MONATISE_MODE=live \
MONATISE_NETWORK=testnet \
MONATISE_ALLOW_LIVE_ORDERS=true \
MONATISE_LIVE_CONFIRMATION=I_UNDERSTAND_REAL_MONEY \
HYPERLIQUID_ACCOUNT_ADDRESS=0x... \
HYPERLIQUID_SECRET_KEY=... \
python3 scripts/serve_live.py
```

Move to `MONATISE_NETWORK=mainnet` only after testnet order placement, cancellation, and reconciliation are verified.

## Hosting

For cloud hosting, use the included Dockerfile:

```bash
docker build -f deploy/Dockerfile -t monatise-live .
docker run --env-file .env -p 4174:4174 monatise-live
```

Render is the active cloud target. Deploy with `render.yaml`, then register or
log in through the dashboard and save the user's Hyperliquid testnet credentials
there. Do not move to mainnet until testnet order placement, cancellation, and
fill reconciliation are verified.
