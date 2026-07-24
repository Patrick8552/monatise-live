---
name: crypto-asset-router
description: Route `/analyze BTC`, `/btc`, API-style, or natural-language Monatise analysis requests for supported cryptocurrency assets. Use only for BTC, ETH, SOL, HYPE, XRP, BNB, DOGE, ADA, LINK, AVAX, or SUI; reject non-crypto instruments and never execute trades.
---
# Crypto Asset Router
Normalize the symbol, reject unsupported assets, and run `python3 {baseDir}/scripts/analyze_crypto.py ASSET --format telegram`. Return its completed result verbatim. Do not call order, configuration-write, or deployment tools.

