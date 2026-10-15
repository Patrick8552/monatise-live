Native futures: startup continuity and multi-timeframe information
================================================================

Scope
-----
Research only for exact GC/ES/NQ futures contracts. No crypto engine, frozen
H1 selector, GIL, execution integration, purchases or new data schemas. Ordinary
H1 candles remain supported. Historical and live source lineage, price guards,
clock checks, transport liveness and zero automatic retries remain enforced.

Startup correction
------------------
The earlier collector aligned its start after every bootstrap anchor. ES's first
trade was six ticks from a 53.714-second-old anchor against a three-tick bound.
The native_futures.bootstrap.review_bootstrap helper verifies sealed native
journal hashes, exact per-schema/instrument anchors, native price/tick identity,
unchanged policy hashes and the complete ordered equal-timestamp prefix.
The approved LiveScope must start at or before every anchor. A BootstrapReview
can be supplied to PersistentResearchService only for a fresh INITIAL attempt
with pristine gates. Its existing FeedState cursor replay skips the proven
anchor prefix once and consumes every subsequent bridge observation. Missing
ties or changed sources fail closed; no jump threshold, anchor or clock is reset.
The raw skipped prefix stays journalled and is excluded from executed volume.
No earlier capture is repaired or relabelled continuous by this correction.

Validation evidence
-------------------
QualityGate now records first rejection evidence per schema, the actual
schema-policy hash, bound/excursion in ticks, anchor/event times and initial
rolling-sample count. A threshold exceedance does not establish corrupted
exchange data. Subsequent accepted observations do not clear the fault. Explicit
reviewed recovery archives the prior detail. Old rejection decisions and the
PriceGuard threshold calculation are unchanged. The earlier ES/NQ rejected
one-second candles reconciled with captured native trade OHLC and volume;
same-provider corroboration is not independent exchange completeness.

Analysis
--------
The default native request computes independent features from validated,
contiguous, closed native bars, limited to 512 recent bars per timeframe:

* Strict pivots require two closed bars on either side; confirmation time is
  the rightmost confirming bar's close. Ambiguous outside bars and flat extrema
  do not invent intrabar pivot order.
* Two confirmed highs and two lows describe higher/lower/mixed structure.
  Latest-close comparisons are observations, not execution or signal rules.
* Fibonacci retracements use the latest confirmed alternating swing leg. The
  mathematical levels are unrounded, descriptive and not executable prices.
* Repeated confirmed extrema within one contract tick form explicitly labelled
  price-based liquidity proxies. No resting order or participant is inferred.
* Multi-timeframe alignment requires at least two available structure states.
  Missing history, gaps and insufficient pivots remain explicit per component.

VWAP, exact-price volume profile and known-aggressor delta continue to use
independently validated captured trades. They describe the retained capture,
not an entire session unless separately verified. Unknown aggressors are never
assigned. No bid/ask, depth, OI, options, absorption or iceberg claim is added.

Verification and operation
--------------------------
Offline synthetic tests cover source/policy mismatch, omitted replay ties,
bridge continuity versus genuine jump rejection, persistent-service handoff,
future-bar leakage, exact contract ticks, gaps, mixed contracts, flat prices,
confirmed-swing arithmetic and historical/live lineage without legacy engines.
These tests do not establish genuine live operation or calibrated accuracy.
Every live attempt needs separate fresh entitlement, zero incremental cost,
clock, source/worker and native anchor review. Never hot-reload a running
collector or clear old faults. Failed original training and holdouts remain
unchanged; post-cutoff diagnostics are not training or an untouched holdout.

Genuine replay identity correction
----------------------------------
The first native startup trial stopped quarantined after7.851seconds because
the trade prefix native hashes differed across the bootstrap and replay.
Forensic byte comparison found only ts_recv/ts_in_delta differences of
-30/-31/-41ns; event, instrument/publisher, price, quantity, action/side, flags,
depth, venue sequence and derived publisher-send timestamp were identical.
The original byte-exact replay rejected these prefixes; preserve that attempt.
An explicitly reviewed INITIAL bootstrap may now opt into a maximum1000ns
receive-clock translation, requiring every exchange field and publisher-send
time to match exactly and both receive times to remain in the same second.
This1000ns bound is a conservative research engineering limit, not a vendor
guarantee or a change to market price/time-admission checks. Clamped deltas,
missing prefixes, changed economic/sequence fields or larger clock variation
remain failures. Both original hashes and the measured time difference are
recorded. Only the proven duplicate anchor prefix is skipped; bytes and all
new market observations remain unchanged. Default/general recovery remains
byte-exact. This does not waive or reset any price guard. Timestamp field
semantics: https://databento.com/docs/standards-and-conventions/common-fields-enums-types
Architecture context: https://databento.com/docs/architecture
