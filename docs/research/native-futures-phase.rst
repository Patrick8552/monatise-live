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
