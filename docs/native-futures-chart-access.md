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
policies, anchors, original raw bytes and committed spool prefix. A stopped or
stale capture is historical context, not current live analysis. The quote reader
accepts `mbp-1` captures only with a sealed, byte-exact native bootstrap prefix,
ask-price anchor and native receive timestamp. The existing narrowly reviewed
trade clock equivalence does not apply to books. No reconnect, subscription,
charge or first-price fallback is performed by the reader.

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
and implement reviewed recovery. Production deployment and trading require a
separate explicit decision.
