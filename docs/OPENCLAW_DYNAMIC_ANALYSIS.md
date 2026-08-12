# OpenClaw dynamic CoinGlass analysis

`GET /api/openclaw/status?symbol=WOOD&interval=1h` is bearer-authenticated,
rate-limited, cached for five minutes, and coalesces identical concurrent
requests. Use `tools/monatise-readonly-analyze WOOD 1h` locally.

The resolver rejects malformed values and forex, verifies CoinGlass
`supported-coins`, verifies the instrument through `supported-exchange-pairs`,
then selects a liquid USD/USDT/USDC market from `pairs-markets`. It neither
assumes Binance nor synthesizes `BASEUSDT`.

Analysis returns `grid`, `trend`, or `no_trade`, plus direction, planned entry
zone/trigger, invalidation, targets, reward/risk, expiry, evidence, quality
warnings, source timestamps, and provenance. `entry` stays null so a pumped
price is never an automatic market entry. Optional derivatives are explicitly
unavailable, not zero. Insufficient/stale history, invalid price, low exposed
volume, malformed data, price disagreement, or absent confirmation fails closed.

The scanner stays BTC/ETH/SOL-only. This route cannot schedule, notify Telegram,
place/cancel orders, write configuration/environment, or deploy/restart. Its
capabilities keep live orders, configuration writes, and deployment writes false.

## Exact OpenClaw skill follow-up

Do not edit a skill until this backend is available.

1. Router: URL-encode non-core crypto tickers and supported intervals into this
   GET route; reject forex and order verbs.
2. Validator: require `execution_enabled=false`, read-only capabilities, verified
   provenance, source timestamps, quality status, and a known classification.
   Reject a setup missing zone, trigger, invalidation, targets, R:R, or expiry.
3. Formatter: show unavailable evidence, warnings, and expiry; label `NO_TRADE`;
   never infer neutral/zero evidence, market entry, size, or leverage.
4. Errors: preserve 400 ambiguity/unsupported details, distinguish 401/429/503,
   never retry 400/401, and use bounded backoff for 429/503.

See `docs/examples/wood-1h.mock.json` for a sanitized mocked response.
