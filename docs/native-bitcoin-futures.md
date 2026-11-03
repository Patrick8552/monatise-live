# Native CME Bitcoin futures reference analysis

BTC now uses the dedicated native-futures research path alongside GC, ES and NQ.
The base is `codex/native-futures-chart-access` at
`135a1150bded1841722a2799b67b4b20de0288fe`; main is an older production branch.
No production route, broker bridge or trading policy is enabled by this change.

## Exact product and definition

Only standard CME `BTC` outright futures are added. Require a genuine native
definition with an exact raw symbol/ID, XCME exchange, USD currency, FUT class,
zero legs, dated unexpired maturity and the reviewed economic terms. In observed
Databento definitions BTC's unit is `IPNT`, quantity is 5, tick is USD 5 per bitcoin,
and tick value is USD 25 per contract after interpreting the display convention.
DBN market prices already express USD per bitcoin and are never display-rescaled.
Micro Bitcoin (`MBT`), ETH and other contracts remain outside this extension.

An explicit futures identity (`BTCX6`, `BTC.FUT`, `BTC.v.0`, `CME:BTC`) is refused
by canonical crypto engines. Bare `BTC` remains an ambiguous spot/perpetual asset
name inside those engines; request routing must select the native futures path
when the user's temporary futures default applies. `BTCUSDT` and spot/perpetual
symbols retain their existing routes. Do not infer a CFD conversion or broker lot
size from a futures price or the five-bitcoin contract multiplier.

## Dated calendar inputs

`BitcoinScheduleReview` and `bitcoin_calendar` require a bounded, dated source
review. They encode CME's post-May-29-2026 BTC schedule in America/Chicago: weekday
16:00–16:02 maintenance and Saturday 02:00–04:00 maintenance, with trading during
the rest of the weekend. DST conversions use the timezone database. Exceptional
closures must be supplied explicitly, and dates outside the review are refused.
This calendar must not be reused as an ES/NQ calendar just because both are XCME.
It does not determine a trade-date/session-CVD anchor or prove capture continuity.
The exchange trading-date convention and full retained execution coverage require
their own explicit review before a result is labelled session VWAP or session CVD.

## Analysis and access

The existing native definition, capture scope, provenance gate, candle lineage,
confirmed-swing/Fibonacci analysis, liquidity-price proxies, executed VWAP/profile
and aggressor-flow modules now accept BTC. Replay readiness checks the candle
schemas actually subscribed; a one-minute-only capture need not invent a one-second
subscription. Missing subscribed candle replay still withholds current analysis.
The reader never creates a provider connection:

```sh
python -m monatise.research.phase10.cli --capture-pointer /private/current-btc.txt \
  --request 'Analyse BTC using Databento'
```

This command requires the existing source-verified capture and reviewed inputs;
adding BTC to the registry alone does not produce them. Fresh provider access,
exact selected expiry, replay controls, clock/record quality, retained coverage,
and any historical dataset-condition warnings must be reported independently.
Free metadata does not establish account entitlement. Historical requests still
require the existing acquisition authorization/cost checks. No paid request,
subscription change, automatic live connection, deployment or order is enabled.

Outputs remain descriptive. Native structure/Fibonacci is not an engine-qualified
entry signal. An interpreted reference setup requires sufficient higher-timeframe
and intraday evidence, structural invalidation and realistic reward/risk; otherwise
return No trade. Report all levels as CME FUTURES REFERENCE PRICES with actual
timestamps and material data gaps.

Primary references reviewed 2026-11-03:

- https://www.cmegroup.com/markets/cryptocurrencies/bitcoin/bitcoin/specs
- https://www.cmegroup.com/markets/trade-24-7
- https://databento.com/docs/examples/instrument-definitions/contract-notional
- https://databento.com/docs/api-live/basics/intraday-replay
