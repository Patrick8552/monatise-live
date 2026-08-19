---
name: crypto-asset-router
description: Route `/analyze BTC`, `/analyze WOOD`, `/btc`, API-style, or natural-language Monatise analysis requests for any cryptocurrency ticker. BTC, ETH, and SOL get full directional analysis; any other crypto ticker (e.g. WOOD, PEPE) gets verified read-only dynamic analysis against live CoinGlass data. Reject non-crypto instruments (forex, commodities, indices) and never execute trades.
---
# Crypto Asset Router
Normalize the requested symbol (strip `/analyze`, quote-currency suffixes like `-USDT`/`/USDT`, etc.).

- If it is BTC, ETH, or SOL: run `python3 {baseDir}/scripts/analyze_crypto.py ASSET --format telegram`.
- For any other crypto ticker: run `python3 {baseDir}/scripts/analyze_crypto_dynamic.py ASSET --format telegram`. This script independently re-verifies the asset against live CoinGlass instruments and fails closed to NO_TRADE if it isn't a real, liquid, tradeable market — do not second-guess or override its result.
- Both scripts accept an optional `--interval` (default `1h`; any CoinGlass-supported interval works, e.g. `--interval 15m`, `--interval 4h`) when the user asks for a specific timeframe.
- If the requested symbol is forex, a commodity, an index, or otherwise not a crypto ticker, reject the request without calling either script.

Return the script's completed result verbatim. Do not call order, configuration-write, or deployment tools.
