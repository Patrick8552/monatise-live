# Stock and futures market-intelligence providers

This is the production capability boundary for FTMO Telegram analysis. It is
deliberately narrower than the list of credentials present in Render: a key is
not evidence that a provider supports an instrument or data type.

| Provider | Verified stock capability | Verified futures capability | Monatise role | Production credential | Failure behavior |
|---|---|---|---|---|---|
| Alpaca | US-equity 15-minute, hourly, and daily OHLC; snapshots; IEX/SIP feed determined by account | No futures market-data API in the current integration | Supporting stock candle, trend, volatility, liquidity, and snapshot confirmation | `ALPACA_API_KEY` + `ALPACA_API_SECRET` present | Reject invalid candles and degrade support; never make a valid FlashAlpha thesis insufficient. |
| Quiver | Company/ticker alternative data: Congress, insiders, contracts, lobbying, off-exchange activity, and news | Not applicable | Supporting stock institutional and alternative-data evidence | `QUIVER_API_KEY` present | Degrade independently when FlashAlpha primary evidence remains valid. |
| Finnhub | Company quote, news, recommendations, and earnings calendar in the current adapter | No verified futures path in the current adapter | Supplemental stock context; never executable pricing | `FINNHUB_API_KEY` present | Degrade independently; plan/rate-limit failures are recorded. |
| FlashAlpha | US equity/ETF options positioning, gamma exposure, flip, and walls, subject to account tier | Options-on-futures analytics for provider-supported and entitled symbols; official documentation explicitly supports ES/NQ and documents broader CME coverage by tier | Primary stock and futures analysis authority | `FLASHALPHA_API_KEY` present | Validate exact symbol, provider timestamp, freshness, GEX, price, flip, and walls; fail closed per instrument. |
| FTMO/MT5 | Native broker quote and symbol specification only after a setup qualifies | Same | Sole executable Bid/Ask, spread, broker specification, sizing inputs, and order authority | Signed bridge secret; separate from analysis providers | `WAITING_FOR_FTMO_QUOTE` or blocked. Analytical prices never substitute. |

Yahoo is not part of this architecture. Forex is out of scope until a verified,
configured non-Yahoo analytical provider is deliberately added and tested.
Non-US FTMO stock CFDs that do not have a verified current provider also fail
closed instead of being routed to an inferred ticker service.

## Routing

Stock on-demand analysis:

```text
FlashAlpha validated GEX + flip + call/put walls + positioning direction
  + Alpaca validated 1H + 15M OHLC and snapshot confirmation
  + Finnhub supplemental company context
  + Quiver institutional/alternative-data context
  -> Monatise score/setup
  -> native FTMO quote only if qualified
```

Futures-linked analysis:

```text
FlashAlpha validated options-on-futures snapshot for the exact futures root
  -> Monatise positioning setup
  -> native FTMO quote only if qualified
```

There is no verified general futures OHLC provider in the current adapter set.
FlashAlpha levels are analytical evidence, not an FTMO quote and not a general
historical candle feed.

## Rate limits and operational suitability

- Alpaca plans document feed entitlements and request limits; the deployed
  adapter batches universe snapshots and bounds bar requests. The Basic market
  data plan documents a 200-requests-per-minute historical limit.
- FlashAlpha exposes account plan/quota information and rate-limit headers.
  Documented daily tiers are Free 5, Basic 250, Growth 2,500, and Alpha
  unlimited. CME futures functionality is tier-gated.
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
