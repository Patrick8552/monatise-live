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
