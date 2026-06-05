# Live Trading Readiness

Monatise now has a live-trading path, but it requires user-owned credentials and funded accounts before real order placement can happen.

## Built

- Backend runtime server.
- Paper trading loop.
- Dashboard Start/Stop controls.
- Hyperliquid adapter using the official Python SDK.
- Real-order environment gates.
- Risk limits for order notional, total batch notional, inventory cap, daily loss, and kill switch.
- Docker deployment scaffold.
- AWS App Runner and ECR deployment scaffold.

## Required From Operator

- Hyperliquid account.
- API wallet created at `https://app.hyperliquid.xyz/API`.
- Testnet or mainnet funds.
- Environment variables from `.env.example`.
- Live dependency installation from `requirements-live.txt`.

## Safety Gates

Real orders are blocked unless all are set:

- `MONATISE_MODE=live`
- `MONATISE_ALLOW_LIVE_ORDERS=true`
- `MONATISE_LIVE_CONFIRMATION=I_UNDERSTAND_REAL_MONEY`
- `HYPERLIQUID_ACCOUNT_ADDRESS`
- `HYPERLIQUID_SECRET_KEY`

Use testnet first.

## AWS Hosting

AWS hosting artifacts are available under `deploy/`.

The intended hosting path is:

1. Build the Docker image.
2. Push it to Amazon ECR.
3. Deploy it to AWS App Runner.

Run after AWS CLI and Docker are installed:

```bash
AWS_REGION=us-east-1 ./deploy/aws-deploy.sh
```
