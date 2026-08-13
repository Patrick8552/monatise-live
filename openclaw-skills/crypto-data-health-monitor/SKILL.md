---
name: crypto-data-health-monitor
description: Monitor Coinglass, Hyperliquid, Monatise Live, database, and Telegram health for cryptocurrency analysis. Use for `/health`, provider degradation, freshness, latency, or divergence checks.
---
# Crypto Data Health Monitor
Use `~/.openclaw/workspace/tools/monatise-readonly-status ASSET [INTERVAL]` (interval defaults to 1h; any CoinGlass-supported interval works, e.g. 15m, 4h, 1d) and the OpenClaw channel health commands. Trust the returned production analysis fields rather than old session summaries. Market data is degraded only when the current result is blocked by `market_data` or the production readiness endpoint reports `market_data` as non-OK. A decision-stage `NO_TRADE` is a valid analysis result, not degradation. Monatise production has no macro engine; never include macro availability or macro degradation in health reports. Never turn degradation into a signal.
