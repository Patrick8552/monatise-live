# Stock and futures market-intelligence providers

This is the production capability boundary for FTMO Telegram analysis. It is
deliberately narrower than the list of credentials present in Render: a key is
not evidence that a provider supports an instrument or data type.

| Provider | Verified stock capability | Verified futures capability | Monatise role | Production credential | Failure behavior |
|---|---|---|---|---|---|
| Alpaca | US-equity H4/H1/M15/M5/M1 OHLCV; snapshots; IEX/SIP feed determined by account | No futures market-data API in the current integration | Primary stock candles for the shared crypto hierarchy; exchange calendar | `ALPACA_API_KEY` + `ALPACA_API_SECRET` present | Missing, stale, or invalid required candles fail closed; no snapshot-only fallback. |
| Quiver | Company/ticker alternative data: Congress, insiders, contracts, lobbying, off-exchange activity, and news | Not applicable | Supporting stock institutional and alternative-data evidence | `QUIVER_API_KEY` present | Degrade independently when required candle and positioning evidence remains valid. |
| Finnhub | Company quote, news, recommendations, and earnings calendar in the current adapter | No verified futures path in the current adapter | Supplemental stock context; never executable pricing | `FINNHUB_API_KEY` present | Degrade independently; plan/rate-limit failures are recorded. |
| FlashAlpha | US equity/ETF options positioning, gamma exposure, flip, and walls, subject to account tier | Options-on-futures analytics for provider-supported and entitled symbols; official documentation explicitly supports ES/NQ and documents broader CME coverage by tier | Required positioning context for stocks/indices; primary analysis for other futures-linked CFDs | `FLASHALPHA_API_KEY` present | Validate exact symbol, provider timestamp, freshness, GEX, price, flip, and walls; fail closed per instrument. |
| FTMO/MT5 | Native execution quote and symbol specification after qualification | EA 1.19 also supplies authenticated read-only index candles and broker sessions | Sole executable Bid/Ask, spread, broker specification, sizing inputs, and order authority | Signed bridge secret; separate from analysis providers | `WAITING_FOR_FTMO_QUOTE` or blocked. Analytical prices never substitute. |

Yahoo is not part of this architecture. Forex is out of scope until a verified,
configured non-Yahoo analytical provider is deliberately added and tested.
Non-US FTMO stock CFDs that do not have a verified current provider also fail
closed instead of being routed to an inferred ticker service.

## Routing

Manual and scheduled stock/index analysis uses the [shared crypto timeframe policy](shared-timeframe-policy.md):

```text
Alpaca stock OHLCV / authenticated MT5 index OHLCV
  -> H4 advisory context -> H1 direction -> M15 setup and stop
  -> M5 confirmation -> M1 entry refinement
  + validated FlashAlpha positioning; optional stock Quiver/Finnhub context
  -> canonical hierarchy risk validation and Signal Core score
  -> native FTMO executable quote -> durable Telegram approval -> signed intent
```

The same hierarchy supplies liquidity, supply/demand, Fibonacci, setup scoring,
stop and target generation, expiry, and invalidation. Index tick volume is not
reported as exchange volume or CVD. Unsupported providers/closed sessions fail
closed. EA 1.19 history capability is required for indices.

Gold and other non-index futures-linked instruments retain their validated
FlashAlpha positioning path and bounded native FTMO quote acquisition. All
routes preserve exact broker mapping, account identity, five-second quote
freshness, sizing, and approval safeguards. TradingView remains optional
reference context and never supplies the executable price.

## Rate limits and operational suitability

- Alpaca plans document feed entitlements and request limits; the deployed
  adapter batches universe snapshots and bounds bar requests. The Basic market
  data plan documents a 200-requests-per-minute historical limit.
- FlashAlpha exposes account plan/quota information and rate-limit headers.
  Documented daily tiers are Free 5, Basic 250, Growth 2,500, and Alpha
  unlimited. CME futures functionality is tier-gated. Production performs one
  sanitized account check and one direct AAPL probe at startup, then exposes
  the cached result at `/api/providers/flashalpha/health`. API keys, email, and
  provider account identifiers are never returned.
- A FlashAlpha stock or futures context currently costs two authenticated
  requests (`gex` and `levels`). Scheduled stock and futures scanners read the
  cached plan/remaining quota, reserve an on-demand allowance, and calculate a
  per-cycle budget from the plan limit. The stock scanner receives 70% of the
  scheduled budget; the hourly futures scanner receives 30% and defaults to
  `ES,NQ,GC`. When either allowance is reached, background candidates are
  deferred instead of consuming the last usable analysis budget. On-demand
  requests can still use any verified registry symbol.
- Finnhub and Quiver limits are plan/endpoint dependent. Monatise treats HTTP
  429 as `provider_rate_limited`, caps scheduled enrichments, and does not make
  either provider a hidden required candle source.
- Every provider uses bounded HTTPS calls suitable for Render. A successful
  HTTP response is still rejected when its identity, timestamp, or payload
  quality does not meet the coordinator contract.

## Primary references

- [Alpaca Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api)
- [Finnhub API documentation](https://finnhub.io/docs/api)
- [FlashAlpha API reference](https://flashalpha.com/docs/api)
- [FlashAlpha futures quick start](https://flashalpha.com/docs/quick-start)
- [Quiver API](https://api.quiverquant.com/)
