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

Instrument quarantine scope
---------------------------
The second reviewed native run completed all replay handshakes and initially
restored trade features for all three contracts. Later, six GC trades carried
F_BAD_TS_RECV and inconsistent receive/event clocks; they remain rejected.
The old read-only report treated this typed GC component quarantine as global
and hid ES/NQ as well. Native request availability now withholds the affected
instrument while preserving independently validated instruments. Original
overall quarantine and component evidence stay visible. Transport, storage,
clock, cursor, cancellation or unknown/global quarantine still withhold every
instrument. ES/NQ second-bar price-policy faults remain separately withheld.
No native timestamp, source flag, rejection, price bound or active collector
code is changed by this reader correction.


Native rejection attribution and dependency correction
-----------------------------------------------------
The subsequent read-only quality review found six original GC trade records
with F_BAD_TS_RECV and receive-minus-event times from -14.407229 to -7.854282ms.
The vendor flag denotes receive-clock issues or packet reordering; the local
reader cannot establish which upstream mechanism occurred. UTC conversion is
not the observed cause. Native bytes, flags, timestamps and rejected admission
bits stay unchanged. The old generic transport_gap:ValueError is retained as
original evidence, with a separate precise source-record explanation.

NativeQualityReview classifies a trade-only timestamp dependency only after
verifying every rejected record in the committed prefix, its identity, economic
fields, other flags, session/capture bounds and original rejection type. A newer
unaccounted health prefix, an unknown or additional defect, missing evidence or
a global clock/storage/transport failure cannot receive this narrower scope.
The reader snapshots source health before its cursor to avoid mixing a newer
failure summary with older replay evidence. Original overall/component capture
quarantine remains visible. Validated native OHLCV can supply descriptive candle
context independently; all trade flow, VWAP and volume-profile outputs remain
withheld. No candles are reconstructed from the rejected GC executions.

The same reader aggregates bounded structurally valid raw prints for diagnostic
cross-stream comparison only, including structurally valid prints rejected by
the price guard. It uses ts_recv for native provider OHLCV buckets. These
aggregates NEVER enter analytical candles, indicators, policy fitting or source
admission. Exact native second-bar OHLC AND volume agreement is recorded with
source hash chains and counts; duplicate bars, out-of-order receive times,
missing evidence, mismatches and budget exhaustion cannot claim corroboration.
All four first ES/NQ price rejections in the reviewed run matched their captured
native second bars. This supports a plausibility/regime limitation, not proof
of exchange correctness, independent completeness or permission to bypass a
price fault. The original ES trade 12-tick/3-tick and NQ trade 60-tick/39-tick
rejections remain; original one-second 14/12.8608 and 86/81.1648 rejections also
remain. No source or policy reanchoring/refitting occurred. The original broader
calibration failed without an eligible training scope or frozen candidate.

Nine new regression cases cover actual receive-flag semantics, additional
malformed/flagged inputs, incomplete evidence, dependency isolation, preserved
global failures, exact/mismatched cross-stream comparison and read-only hash
preservation. 2,622 full-suite tests and 187 focused native/Phase9/Phase10 tests
passed. This is a reader correction on an existing capture, not a new live
collector deployment or a completed full-session reliability certificate.
Reference: https://databento.com/docs/standards-and-conventions/common-fields-enums-types
