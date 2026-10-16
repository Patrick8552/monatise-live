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

The numerical plausibility policies remain unchanged and are not newly certified.
A legitimate large move can require review; a successful short trial cannot prove
full-session continuity, independent exchange truth or institutional reliability.
Never relabel rejected history as validated H1/H4 warm-up. Never automatically
reanchor, clear a fault, fill a gap, refit a holdout or promote to trading.

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

Before broader use: complete historical range and session/holiday review, resolve
price-policy failures with separate admissible evidence, validate quote/depth
coverage under load, classify network/provider silence with retained diagnostics,
and implement reviewed recovery. Production deployment and trading require a
separate explicit decision.
