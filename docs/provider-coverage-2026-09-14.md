# Stock provider coverage and evidence quality — 14 September 2026

The registry contains 59 FTMO stock CFDs. This revision adds the verified SPCX analysis route, bringing configured US-equity routes to 46. The 13 European primary listings below remain unavailable for actionable analysis. Every supported route must still pass current evidence, shared candle hierarchy, session, risk, executable-quote and human-approval checks.

## Confirmed provider behavior

SNOW returned HTTP 200 from both FlashAlpha GEX and levels endpoints, but `gamma_flip=null` and `gamma_flip_status=no_boundary`. Its call/put walls and net GEX were present. Response and underlying equity/options-feed timestamps were current. Alpaca supplied all five required candle series, and Finnhub and Quiver returned supplemental context. No transport retry or substitute data can create the missing certified gamma boundary. MSFT also returned `no_boundary` on a later sample, explaining at least one repeatable source of intermittent primary-evidence rejection.

FlashAlpha's [September 2026 changelog](https://flashalpha.com/docs/changelog) documents both withheld flips and numeric but uncertified indicative levels. The adapter now preserves explicit nulls and certification status instead of selecting a different endpoint's value. Unavailable or unrecognized certification remains fail-closed. Both response identities and timestamps are checked, together with relevant source-feed timestamps when supplied. Scoring, confirmation thresholds and the shared timeframe policy are unchanged.

Durable diagnostics retain the rejected provider, endpoint, field, quality reason, HTTP status, bounded request-attempt count, response/source timestamps and rate-limit metadata. Arbitrary exception bodies, credentials and provider-node identifiers are excluded.

## Previously unsupported symbols

These are checks against the configured providers, not a claim that no vendor anywhere can supply the instrument. A Finnhub 403 means this credential could not obtain the requested data; it does not prove that the provider never supports the listing. Broker symbol resolution was verified separately and does not establish permission to execute a particular order.

| FTMO symbol | Underlying listing | FlashAlpha | Alpaca | Finnhub | Quiver | Broker mapping | Analysis route / remediation |
|---|---|---|---|---|---|---|---|
| ADSGn | ADS / Xetra (`ADS.DE`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Blocked; needs verified candles/calendar and certified positioning |
| AIRF | AF / Euronext Paris (`AF.PA`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Corrected underlying identity; remains blocked |
| ALVG | ALV / Xetra (`ALV.DE`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Blocked; needs verified candles/calendar and certified positioning |
| BAYGn | BAYN / Xetra (`BAYN.DE`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Blocked; needs verified candles/calendar and certified positioning |
| DBKGn | DBK / Xetra (`DBK.DE`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Blocked; needs verified candles/calendar and certified positioning |
| IBE | IBE / BME (`IBE.MC`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Blocked; needs verified candles/calendar and certified positioning |
| LVMH | MC / Euronext Paris (`MC.PA`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Blocked; needs verified candles/calendar and certified positioning |
| SAN | SAN / BME (`SAN.MC`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Blocked; needs verified candles/calendar and certified positioning |
| SIEGn | SIE / Xetra (`SIE.DE`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Blocked; needs verified candles/calendar and certified positioning |
| VOWG_p | VOW3 preferred / Xetra (`VOW3.DE`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Blocked; preserve preferred-share identity |
| TTE | TTE / Euronext Paris (`TTE.PA`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Blocked; do not substitute the USD ADR for the EUR listing |
| BMW | BMW / Xetra (`BMW.DE`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Blocked; needs verified candles/calendar and certified positioning |
| MBG | MBG / Xetra (`MBG.DE`) | 404 | No matching US asset | 403 | No verified primary-listing route | Resolved | Blocked; needs verified candles/calendar and certified positioning |
| SPCX | SPCX / Nasdaq, Space Exploration Technologies Class A | 200; certified gamma, walls and net GEX | Active Nasdaq asset; all five candle series returned | 200; quote/news/recommendations | Available; fresh congressional records | Resolved; broker Bid/Ask returned | Supported route added; ordinary qualification and execution safeguards still apply |

The previous `AIR.PA` identity for AIRF was incorrect. [Euronext identifies Air France–KLM as AF](https://live.euronext.com/en/product/equities/fr001400j770-xpar); the [issuer identifies the same share and ISIN](https://www.airfranceklm.com/en/share-price). The `.PA` mapping uses the registry's primary-listing convention and does not imply Finnhub entitlement.

SPCX is no longer a private-market-only instrument: [Nasdaq's listing notice](https://m.nasdaqtrader.com/TraderNews.aspx?id=DTN2026-8) and the [issuer's IPO release](https://ir.spacex.com/updates/releases-details/2026/Space-Exploration-Technologies-Corp--Announces-Pricing-of-Initial-Public-Offering/default.aspx) identify its public Class A ticker. The configured Alpaca asset directory returned the matching corporate name, Nasdaq exchange and active status. The 4h series contained 71 bars; 1h, 15m, 5m and 1m each supplied 200 in the verification sample. FlashAlpha returned `gamma_flip_status=available` from both endpoints. This establishes an analysis route, not a guaranteed qualifying signal.

[Alpaca's documented equity feeds](https://docs.alpaca.markets/us/docs/about-market-data-api) cover US exchanges. [Quiver's disclosed data sources](https://www.quiverquant.com/datasources/) provide supplemental alternative data; they cannot replace missing primary-listing candles or fabricate institutional positioning. No paid feed, subscription upgrade, ADR conversion or synthetic institutional-data fallback was enabled.
