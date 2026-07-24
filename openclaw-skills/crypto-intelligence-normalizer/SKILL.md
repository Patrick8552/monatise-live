---
name: crypto-intelligence-normalizer
description: Normalize live Monatise crypto prices, candles, structure, FVG, funding, open interest, liquidations, and provenance into a consistent snapshot. Use when preparing provider data for the analysis runner.
---
# Crypto Intelligence Normalizer
Preserve missing fields as `null`, never zero. Retain source labels and UTC timestamps. Reject malformed prices and stale candles. Compare sources only when both exist. Attach plan-limit, missing-data, and divergence warnings.

