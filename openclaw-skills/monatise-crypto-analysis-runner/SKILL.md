---
name: monatise-crypto-analysis-runner
description: Run the production Monatise cryptocurrency analysis workflow and return TREND or NO_TRADE. Use for direct crypto analysis requests after routing and collection; never use OpenClaw itself as an execution engine.
---
# Monatise Crypto Analysis Runner
Run `~/.openclaw/workspace/tools/monatise-readonly-status ASSET [INTERVAL]` (interval defaults to 1h; any CoinGlass-supported interval works, e.g. 15m, 4h, 1d). This calls the protected, read-only Monatise production pipeline, where CoinGlass is the primary market-data provider and Backpack public data is the fallback. Accept BTC, ETH, or SOL only. Report the returned status, classification, blocking engine, completed-stage count out of 19, run ID, and correlation ID. A decision-stage `NO_TRADE` is a valid completed analysis outcome, not a degraded market-data failure. The production pipeline has no macro engine, so never report macro availability or macro degradation. Never invent unavailable fields, levels, or decisions. Never place, modify, or cancel an order; `execution_enabled` and `openclaw_execution_enabled` must both remain false.
