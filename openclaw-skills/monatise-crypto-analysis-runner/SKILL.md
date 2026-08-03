---
name: monatise-crypto-analysis-runner
description: Run the completed six-stage Monatise cryptocurrency analysis workflow and return LONG, SHORT, or NO_TRADE. Use for direct crypto analysis requests after routing and collection; never use OpenClaw itself as an execution engine.
---
# Monatise Crypto Analysis Runner
Run `python3 ~/.openclaw/workspace/skills/crypto-asset-router/scripts/analyze_crypto.py ASSET --format json`. CoinGlass is the only permitted market-data provider. Return provider unavailable when CoinGlass data is absent, and return NO_TRADE on Saturday/Sunday UTC. Never invent levels or execute an order.
