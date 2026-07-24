---
name: crypto-intelligence-collector
description: Collect read-only Monatise cryptocurrency intelligence from the live bearer-protected status path, treating Coinglass as primary and Hyperliquid as supplementary. Use for provider collection, provenance, availability, latency, or missing-data questions.
---
# Crypto Intelligence Collector
Use `~/.openclaw/workspace/tools/monatise-readonly-status SYMBOL INTERVAL`. Never read its token file or print credentials. Record source and timestamps. Prefer Coinglass. When it is unavailable, permit a clearly labeled Hyperliquid-only fallback snapshot; do not invent absent fields.
