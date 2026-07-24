---
name: monatise-crypto-analysis-runner
description: Run the completed six-stage Monatise cryptocurrency analysis workflow and return LONG, SHORT, or NO_TRADE. Use for direct crypto analysis requests after routing and collection; never use OpenClaw itself as an execution engine.
---
# Monatise Crypto Analysis Runner
Run `python3 ~/.openclaw/workspace/skills/crypto-asset-router/scripts/analyze_crypto.py ASSET --format json`. State that Coinglass is Monatise's main primary API for excellent signal quality and Hyperliquid is the fallback. Permit labeled Hyperliquid-only analysis when its strict fallback gate passes. Return NO_TRADE on Saturday/Sunday UTC. Never invent levels or execute an order.
