# Native futures chart information (research)

This path returns facts for exact GC, ES and NQ futures contracts. It excludes
crypto analytical engines, frozen H1 selection/expiry, GIL and the Monatise XAUUSD
signal router. Hourly candles remain ordinary data. It has no order execution or
production registration. TradingView's existing Pine indicators continue using
the chart's selected provider; this service does not replace that feed.

## Read a reviewed capture

Use the Python environment with the project's pinned Databento dependencies:

```sh
python -m monatise.research.phase10.cli \
  --capture-pointer /absolute/private/current-capture.txt \
  --request 'Analyse GC, ES and NQ using Databento'
```

The CLI verifies the source-bound authorization, exact instrument definitions,
normalization mode, original raw bytes and committed spool prefix. Legacy
statistical captures also require their original policies and anchors. Native
information captures use exact contract definitions and documented native
semantics without a statistical price anchor. Stopped captures retain dated
historical context. The reader never opens provider connections or repairs data.

## Meaning of outputs

* Structure/Fibonacci/price-based liquidity proxies use confirmed native swings;
  they do not replicate proprietary LuxAlgo scripts or establish resting orders.
* Plain EMA20, Wilder RSI14, its SMA14 and descriptive recent crosses use only
  validated closes, with explicit seeds and minimum history. They do not claim
  equivalence to proprietary chart indicators or longer-history seeds.
* UTC multi-timeframe structures may cross explicitly reviewed exchange closures.
  Missing buckets during fully open intervals still withhold structure. Partial
  session buckets are reported explicitly. No synthetic candles are inserted.
* VWAP, executed delta and volume-at-price describe the retained accepted trade
  window, not the entire session. MBP trade events do not contribute extra volume.
* Bid/ask is admitted displayed top-of-book information, with its timestamp,
  source hash and freshness gate. It is not a broker's executable quote. Stale,
  crossed, one-sided or rejected books remain unavailable.
* OI is published statistics, not signed dealer inventory. Changes compare two
  distinct reference periods, retaining the latest admitted revision per period.
  Truncated archives cannot certify current OI or complete chain coverage.
* GC is a futures contract. FXCM XAUUSD prices on a separate chart require an
  independently synchronized basis and broker quote before manual spot decisions.

The active `DATABENTO_NATIVE_INFORMATION_V1` mode, explicitly requested by the
user, does not use custom statistical price anomalies, MAD thresholds, spread
caps or price anchors. Documented DBN schema, native identity/tick/flag semantics,
source positions, clocks, data freshness and source-continuity evidence remain.
A large native move is not declared corrupt because it exceeds a local model.
These are implementation checks, not a claim of Databento certification.

Fresh continuous subscriptions start directly, without disconnecting a quote
bootstrap and requiring another connection to reproduce its capture-clock bytes.
Each schema's explicit replay start is bound to the source authorization. Books
can start recently while trades/candles replay from the reviewed history boundary.
No record from the earlier failed quote attempt is re-admitted. Older statistical
captures retain their original mode, faults and reader requirements.

History is a separately hashed provider archive interpreted under the new mode,
not a repair of old captures or evidence of elapsed live continuity. Only complete
native child buckets form parents; unknown missing intervals remain missing.
Published OI is retained independently of high-rate book eviction. Displayed book
states unsuitable for quote calculations remain labelled unavailable.

## Databento guidance followed

* [OHLCV conventions](https://databento.com/docs/schemas-and-data-formats/ohlcv):
  interval-start UTC timestamps, receive-time buckets, no print when no trades;
  resample finer bars or construct one's own consistent trade bars.
* [Live API change](https://databento.com/blog/live-api-changes-2026-04): explicitly
  request `slow_reader_behavior="warn"` so eligible book schemas do not silently
  skip to catch up. Warning, increasing lag or dropped data must still invalidate
  the dependent output. This does not fix a network outage.
* [OI and settlements](https://databento.com/docs/examples/futures/retrieving-oi-and-settlement-prices):
  select the appropriate native statistics type and preserve publication/reference
  time. OI does not identify buyer/seller or imply dealer gamma.

Before broader use: complete historical range and session/holiday review, review native
field/coverage failures against source evidence, validate quote/depth
coverage under load, classify network/provider silence with retained diagnostics,
and verify bounded recovery with real interruptions. Production deployment and trading require a
separate explicit decision.


## Bounded reconnect with intraday replay

The opt-in `DATABENTO_EVENT_TIME_COUNT_V1` orchestration follows
[Databento recovery guidance](https://databento.com/docs/api-reference-live/basics/recovering-after-a-disconnection):

* Track the last event timestamp and record count at that timestamp for each
  schema/instrument. Subscribe before streaming, starting at the lowest stored
  timestamp for that schema. An instrument without a cursor uses the original
  authorized start. BBO/CBBO require receive-time cursors and are not enabled here.
* Discard the older overlap and exactly the first N tied-timestamp records per
  instrument, retaining every original and replayed byte in the journals/spool.
  Replayed capture timestamps need not be byte-identical. Identical legitimate
  executions after the counted prefix remain separate observations.
* Require fresh definitions, acknowledgements and REPLAY_COMPLETED for every
  schema before publication/current analysis. Missing tied-prefix records stop
  recovery. Regressed event-time cursors require a separate overlap review; this
  implementation does not pretend the simple seek recipe proves that case.
* After a hung connection or disconnect without a provider ErrorMsg, close all
  owned clients, wait at least one second, genuinely refresh metadata/clock
  receipts, and resubscribe within the same finite authorization. Provider errors,
  record rejections, storage/clock faults and exhausted attempt/time budgets
  stop for review. There are at most three attempts in a 15-minute trial.
* Keep `slow_reader_behavior="warn"`. The SDK's automatic reconnect in pinned
  Python 0.87.0 uses `start=None`, so it is not used as a substitute for replay.
  Only documented Live public methods are called by the transport.

A hash-bound attempt ledger and independent read-only native reconstruction
recompute the counted overlap and check every admission bit. Original failed
attempt reports stay unchanged. A Wi-Fi link event is transport evidence, not a
malformed-price finding. Analysis is RECOVERING until replay completes; aged-out
or unreconciled data remains unavailable. This proves only retained provider
replay consistency, not independent exchange completeness or execution readiness.

Synthetic tests cover disconnect/replay, tied multiplicity, missing prefixes,
provider errors, bounded exhaustion, cleanup and falsified overlap admission.
Live results must be reported separately; an uninterrupted trial does not verify
recovery from a real Wi-Fi outage. No data purchases or historical downloads are
performed by the recovery service.

## Permanent futures scope and chart workflow

GC/ES/NQ use the dedicated native information path permanently. The frozen H1
selector execution bridges and research GIL qualifier have been deleted. Canonical
crypto candle engines reject their raw, parent and continuous futures identifiers;
the older Phase9 price path also uses native swings/technicals. Old broker-preview
entrypoints return an explicit retired-route receipt without evaluating candles.
Ordinary H1/H4 bars remain ordinary data. Immutable prior capture sources and Git
history remain evidence, not approved algorithms for new requests. Root AGENTS.md
records the user's permanent scope; do not restore a retired route as a fallback.

Databento documents data acquisition, schemas and calculations. The following is
Monatise's proposed use of those observations, not a vendor-endorsed strategy:

1. Resolve the exact tradable contract and instrument ID. Align chart contract,
   session, timezone, rollover/back-adjustment settings and timeframe grid with
   the native source before comparing any prices or indicators. Continuous
   Databento symbols map to actual unadjusted contracts; chart vendors can use
   different rollover and adjustment conventions.
2. Use native OHLCV for chart bars and close-based indicators. Databento marks the
   beginning of the receive-time aggregation interval; no trades means no bar.
   A verified no-print interval is different from an unknown capture gap. Do not
   fill missing periods with invented candles or compare differently anchored H4.
3. Use one declared VWAP definition and reset anchor. A trade VWAP uses
   sum(price * size) / sum(size); a candle-close or typical-price VWAP can differ.
   A retained execution window is not a full-session VWAP. EMA/RSI initialization,
   swing confirmation and volume-profile range/bin settings must also match.
4. Use trades for aggressor-side volume and delta. Trade B is buyer-aggressed,
   A seller-aggressed, N unknown. Preserve unknown volume separately. An MBP
   order Add/Modify/Cancel side describes the resting book, not a trade aggressor.
   L1 displayed bid/ask is not full depth, institutional identity or broker fill
   assurance. Every analysis reports source age, replay state and missing inputs.
5. Keep the trading framework explicit: H4/H1 context and levels, M15 setup,
   M5 trigger, structural invalidation, objective and user-defined risk. This is
   an optional research convention to test; the data provider does not select
   entries or certify profitability. Current software provides observations;
   a validated dedicated futures setup/entry policy has not been delivered here.
6. Execute manually on the actual broker instrument. Recheck the broker bid/ask,
   contract expiry, point/tick value and costs. GC is not XAUUSD; ES/NQ futures
   are not cash-index CFDs. Cross-instrument use needs a synchronized measured
   basis and broker specifications, never a copied futures price or router.

The immediate integration can be a separate Monatise evidence panel alongside a
matching TradingView futures chart. TradingView/Pine uses its own supplied chart
contexts; a Databento API subscription does not inject a feed into Pine. A custom
Databento-fed chart needs a real backend datafeed integration and applicable
chart/data licenses. TradingView Advanced Charts documents its Datafeed API for
separate embedded applications; it is not the user's tradingview.com chart and
its access/license availability has not been assumed. No chart connection has
been built or enabled by the retirement change.

Next engineering deliverable: a read-only native chart/evidence panel fed from
the same normalized series, followed by exact indicator/session parity checks
and a longer real-network recovery test. Then separately define and replay-test
the user's native-futures entry/stop/target rules with realistic costs. No signal,
execution integration, purchase or deployment is authorized by this document.

Primary references:
- https://databento.com/docs/standards-and-conventions/symbology
- https://databento.com/docs/schemas-and-data-formats/ohlcv
- https://databento.com/blog/vwap-python
- https://databento.com/docs/standards-and-conventions/common-fields-enums-types
- https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/
- https://www.tradingview.com/charting-library-docs/latest/connecting_data/datafeed-api/

## Databento-fed local chart

The local native chart replaces a separate chart feed **inside Monatise**.
It does not alter the feed of a tradingview.com chart or execute Pine scripts.
It uses a repository-owned Canvas renderer with no external scripts, chart
licences, broker endpoints or API credentials in the browser. The HTTP service
binds to 127.0.0.1 only and exposes fixed read-only routes.

`python -m monatise.research.native_futures.chart export --capture CAPTURE
--snapshot PRIVATE/chart.json --reader-commit COMMIT` performs source-verified
reconstruction outside the collector. `serve --snapshot PRIVATE/chart.json
--source-snapshot CAPTURE/source-snapshot.json --duration 3600` starts the chart
at http://127.0.0.1:8766 for one hour. A separately launched `refresh` worker can
publish snapshots from an authorized running collector; neither the reader nor
the chart creates a Databento client or starts capture. On refresh failure the
last successful snapshot remains explicitly historical. This is local research
access, not a production deployment.

The chart exports exactly the last 512 validated bars used by each native
analysis frame and checks their digest against that frame. It preserves bar
hashes, native identity, evidence category, UTC bucket starts and missing
intervals; it creates no empty candles. Global/instrument source quarantine or
failed candle lineage prevents chart publication for the affected scope.
Dependent indicators remain unavailable where native gap checks fail. The
chart contains closed 1m/5m/15m/H1/H4 candles, volume, EMA20, Wilder RSI14 and
its SMA14, confirmed swings and Fibonacci, retained-window trade VWAP, known-side
delta, explicit unknown-side volume, displayed bid/ask and executed-volume
profile prices. The constant VWAP overlay is the declared retained-trade-window
value, **not a reconstructed historical or daily VWAP series**. Indicators use
the same native implementation/seed as the report. Data received after a candle
closes remains subject to source reconstruction and quality checks before the
next refresh. The current UI is snapshot-based (10-second polling; full verified
reconstruction runs separately); it is not a tick-latency or execution terminal.

The chart discloses analysis/source observation times and sealed/recovering
states. A source heartbeat or polling response is not a fresh-exchange-delivery
certificate. Current live operation requires an actually running authorized
collector and refresh worker. A completed trial supplies historical context
only. No new live connections are opened as part of building the chart.

The one-hour value in example commands is an operator default, not a Databento
limit or an original user request. The user subsequently explicitly selected
today's GC/ES/NQ futures market close. Collector/server/reader durations must
follow that dated endpoint (plus bounded finalization), without silently
changing a running immutable scope. A reviewed handover may perform fresh
same-scope intraday replay; old errors and the source transition remain visible.
Operational duration can be set up to the existing LiveScope one-day maximum;
that changes no record-admission, timestamp, lineage or replay-prefix checks.

For a running collector, `native_futures.live_view.freeze_service` detaches its
native gates and candle collections on the owning event loop; `publish_view`
computes the existing native frame/features in a worker thread. Both chart and
text cache share that exact analysis result. No journal-wide reconstruction runs
inside the collector or chart refresh. Immutable observation/bar/contract objects
retain their source hashes, flags, timestamps, causal cutoff and coverage reviews;
all mutable containers are copied. A failed view stops further view publication
and exposes REFRESH_FAILED, without silently retrying or changing source faults.
This live view explicitly identifies its verification scope as collector-admitted
data. It does **not** claim an independent raw-journal forensic replay occurred
for every refresh; that remains a separate retained-evidence check.

For a longer session the live coverage index compacts equivalent native proofs
only after 4,096 entries: it retains the newest scope-compatible proof, every
proof referenced by retained bars, all historical response proofs and distinct
source/attempt references. Raw interval controls, sealed journals and published
outbox evidence remain untouched. This bounds the live lookup cost without
inventing empty intervals, erasing faults or changing proof eligibility.
