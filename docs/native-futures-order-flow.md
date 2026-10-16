# Native descriptive trade flow

This read-only feature uses already admitted Databento `trades` records from the
dedicated native futures path. It opens no provider connection and uses no crypto
engine, frozen H1 selector, GIL qualification or XAUUSD router. It does not reject
valid observations or qualify orders.

## Clocks and windows

The 1m, 5m and 15m half-open windows end one nanosecond after the latest admitted
trade `ts_recv`. Their exact start/end and latest-trade age are reported. They are
not silently moved forward to an assumed current wall clock. Local clock
differences and available UTC offset bounds remain separate from native timestamps.
Future-admitted records are excluded. Source-position duplicates count once;
conflicting positions, mixed identities/evidence and receive-order regressions fail.
Native event time is retained independently.

Each window reports observed events/contracts, known buy/sell/unknown volume,
known-side delta, VWAP and first-to-last price movement in contract ticks. Unknown
sides are never inferred. Full signed flow is unavailable when unknown-side volume
exists. Empty retained windows do not establish no exchange activity. Earliest
retained observations and possible window/reference truncation are explicit. No
complete-session or exchange-wide completeness claim is made.

## Size reference and persistence

For each target window, the reference is the preceding nonoverlapping 30 minutes
of retained observations. P95 uses nearest rank. Events strictly larger than that
reference P95 are counted; all valid events still contribute to pressure and VWAP.
Flat one-contract samples do not flag every one-contract event. The reference
count, median, P95, bounds and position hashes are reported; a small or truncated
reference can be unrepresentative. Examples are display-limited while totals
include every event in the window. This is a descriptive definition chosen for
this research interface, not a Databento requirement or calibrated trade gate.

The latest minute is compared with the preceding five minutes using rates and
known-side buyer-share changes. Five nonoverlapping one-minute buckets show buy
dominance, sell dominance, balance and absence of known-side observations.

## Price response interpretation

A possible passive-sell absorption pattern means known buyer aggression without
upward net price progress, while observed total-volume and buyer-volume rates
exceed their preceding reference. The converse describes possible passive-buy
absorption. Two trade events are necessary to describe net price progress. Unknown
aggressor volume prevents this absorption label. The underlying observed contrast
still remains visible.

These patterns are unvalidated trade-only interpretations. They cannot establish
replenishment, iceberg orders, participant identity, new positions, institutional
accumulation, intent or future price direction. Hedging, covering and mixed activity
are alternative explanations. They are not buy/sell signals or vendor-prescribed
trading rules. No depth/OI/options subscription is added.

## Provenance and failure handling

Record-position and native record hashes bind each target/reference sample; the
original admitted observations remain unchanged. Global/instrument source failures
and unavailable trade inputs withhold this feature. Existing raw records, flags,
clock receipts, rejections, replay cursors and sealed archives remain authoritative.
The read-only reader can be updated independently of the immutable collector.

Official data semantics: https://databento.com/docs/schemas-and-data-formats/trades
CME anonymity: https://www.cmegroup.com/articles/faqs/market-by-order-mbo.html
