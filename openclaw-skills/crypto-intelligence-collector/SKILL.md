---
name: crypto-intelligence-collector
description: Collect read-only Monatise cryptocurrency intelligence from the live bearer-protected status path, treating Coinglass as primary and Hyperliquid as supplementary. Use for provider collection, provenance, availability, latency, or missing-data questions.
---
# Crypto Intelligence Collector
Use `~/.openclaw/workspace/tools/monatise-readonly-status SYMBOL [INTERVAL]` (interval defaults to 1h; any CoinGlass-supported interval works, e.g. 15m, 4h, 1d). Never read its token file or print credentials. Record the staging run ID and correlation ID. CoinGlass is the primary market-data provider. If the pipeline blocks or data is unavailable, report that outcome without inventing absent fields and without bypassing the blocking engine.
