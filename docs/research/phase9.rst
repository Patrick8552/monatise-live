Phase 9: native analytical research pipeline
============================================

Status: implemented research interfaces, with offline regression and archival
native-record validation. This is not a deployment or sustained-live certificate.
The final operational verdict remains PARTIALLY.

Baseline and isolation
----------------------

Branch: codex/monatise-phase9-live-data-pipeline.
Baseline: dba0d56fbb9a752c525532ffc13e48772ded875c, including Phase 8
(d6be0b1ff69bd88ee88fcd76c9020602dc686171). Main remains
0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18. Frozen H1 remains
f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35 in its separate checkout.
No startup registration, deployment, execution, GIL provider registration,
Telegram publishing or governance configuration is added.

Usage and boundaries
--------------------

``monatise.research.phase9.pipeline.ResearchPipeline`` accepts existing canonical
Contract/MarketObservation/HistoricalBar structures through the native normalizer.
Supply reviewed contract definitions, an explicit calendar, enabled schemas,
per-instrument PlausibilityPolicy and provenance-bound initial anchors. No
production threshold is inferred from a short sample or a synthetic fixture.
``ingest`` returns acceptance/rejection reasons; ``analyse`` returns the common
availability envelope and existing pure analytical-engine outputs. Missing
quotes, options, positioning, M1 or M5 are separate components. Native GC/ES/NQ
prices retain their exact contract namespace; basis is NOT_APPLICABLE for native
analysis. Reference prices never become executable bid/ask quotations.

``availability`` supplies feature-specific policies and configurable contextual
tolerance, with inherited limits of 10 seconds for trade/book context, 30 seconds
and one-second pairing for options, four days for OI reference age and two bar
intervals for candles. Wider contextual tolerance needs explicit review/evidence.
Source clocks remain raw. An existing ClockReview can qualify the UTC interval;
it is bounded, expires, and is not an authenticated clock certificate. Provider
clocks outside the interval reject. Mandatory execution/quote pairing is not
relaxed. Candle finalization retains the existing ten-second grace.

``quality`` performs source-position idempotence, tick/quantity/native structural
validation, per-schema event/receive ordering, spread screening and rolling
median/MAD price screening. Legitimately identical native events at different
positions retain multiplicity. Filtered packet sequence gaps are not treated as
missing exchange events. Suspicious observations never train the guard. A
reviewed discontinuity recovery replaces the anchor only for subsequent data;
it does not rewrite rejected observations. Faults are contract/schema scoped.
Previously complete bars ending before a dated fault remain independently
calculable; affected/newer data stays unavailable until reviewed recovery.

``candles`` supports 1s, 5s, 1m, 5m, 15m, 1h and 4h using canonical bars.
Trade-derived event-time buckets are distinct from provider OHLCV, whose clock
convention is not assumed equivalent. CoverageReview is required to finalize a
captured trade window. A heartbeat/last trade alone does not prove completeness.
Missing/no-trade periods stay unknown; no flat fill is generated. Smaller-bar
aggregation requires every child. Late observations retract affected buckets on
subsequent views. Re-query after ingestion; existing snapshots are historical.
No exchange-continuity certificate is issued.

``coordinator`` invokes the existing regime, liquidity, sweep, supply/demand,
reclaim, market-structure and Fibonacci engines, preserving independent engine
results and explicit failures. It also exposes native VWAP, executed-price volume
profile/POC, known-side CVD, volatility, captured-window statistics, book metrics
and OI changes. Unknown aggressors remain unknown. Visible book quantity is not
executed volume or evidence of institutional intent. Generic Fibonacci context is
not the frozen H1 selector. All research decisions remain NO_TRADE with
qualification NOT_EVALUATED; availability is not trade qualification.

``options.option_inputs`` independently validates exact GC option/underlying
quotes, the original 30-second/one-second gates, model assumptions and dated rate.
It reuses Phase 7 numerical convergence validation and Phase 8 OI eligibility.
Missing/stale OI never enters the IV solve. OI-weighted unsigned sensitivity needs
qualifying OI and validated Greeks. American lattice gamma instability remains a
rejection even when an IV was solved. Signed dealer GEX, gamma flips, inferred
walls and production GIL compatibility remain unavailable. Provider hierarchy is
unchanged. Existing Phase 8 family/catalog/surface tooling remains separate.

``storage.DurableSpool`` stores original native BLOBs, source/capture clocks,
reviewed clock evidence, hashes and delivery identities in private SQLite
FULL/WAL storage. Native framed journals are still written/fsynced first. Replay
verifies bytes and metadata and reconstructs analytical state. Gateway prefix
replays are retained as raw evidence but not counted as executions. Rejections
remain scoped faults after restart. Limits cover native bytes/record count;
SQLite/index/WAL overhead requires additional local disk capacity.

``service.PersistentResearchService`` wraps the existing typed SDK transport,
LiveScope, one-use permits, cursor-prefix verification, bounded callback queue,
connection monitoring and native journals. Every possible connection attempt must
be included in an explicit CapturePlan with current entitlement/cost evidence,
verified no additional charges, distinct permits and reviewed recovery/session/
roll transitions. No provider error, malformed stream, storage failure or
backpressure fault triggers a blind retry. A disconnected connection can use the
next authorized attempt. A mismatched raw/cursor boundary after interruption
requires review; the service does not guess continuity. Restart does not reuse
an already reserved attempt. Permits intentionally expire after five minutes;
there is no automatic entitlement renewal. At expiry/resource/session boundaries,
the service stops safely. Preload explicitly reviewed new contracts for a roll;
there is no automatic continuous-symbol roll or back-adjustment.

Live defaults remain definition/trades/MBP-1. Additional MBP-10, native OHLCV-1s,
OHLCV-1m, OHLCV-1h, statistics (published OI) and status schemas are opt-in and
still require matching entitlements. Non-OI statistics stay raw without being
misrepresented as OI. MBO reconstruction is not implemented in Phase 9.
Continuous final candle publication from a transport watermark and unattended
full-session spool rotation remain unfinished; the analytical API is explicit.

Existing-engine fixes
---------------------

* MarketDataEngine isolates malformed optional derivatives mappings, bounds their
  field count and request time, preserves validated candles, reports component
  quality, and keeps a bounded private diagnostic representation. Legacy adapters
  expose objects rather than wire bytes; this is not a raw-feed archive. At most
  one timed-out worker may remain outstanding per engine; a stuck call cannot
  create a growing worker queue or block process exit.
* The futures scanner isolates Gold exceptions, invalidates failed state, records
  error type/stack context and marks programming errors explicitly. Cancellation
  propagates; independent ES/NQ results continue. No failed instrument qualifies.
* unadmitted_diagnostic computes independent price layers with missing quotes or
  lower frames, without invoking risk/selection/entry qualification.
* The legacy adapter's explicit identity-policy native GC path shares pure
  native_gc_economics validation with research; production adapters do not import
  research modules. The legacy default remains unchanged.
* broker_preview now reports missing verified broker candles as
  INSUFFICIENT_MARKET_DATA / mapping NOT_EVALUATED, preserving decision enums.

Evidence and unresolved work
----------------------------

Tests: ``tests/research/phase9`` plus the full repository suite, using disposable
localhost PostgreSQL/Redis; frozen H1 tests run against the unchanged pinned
checkout. No production DSNs, live credentials, broker actions or Telegram
transports are needed. Genuine validation replays pre-existing sealed licensed
native captures locally; no raw market archive belongs in Git.

Four archived GC/ES/NQ captures supply genuine definitions, trades, MBP-1 and NQ
minute bars. Reviewed local UTC bounds remove strict-clock false rejections
without changing original clocks. Four NQ minute bars are quarantined under an
initial descriptive price policy: independent held-out/timeframe calibration is
still required. One genuine OG pricing pair solves IV but rejects American gamma
for fine_bump_lattice_gamma_instability; neither missing OI nor gamma exposure is
fabricated. These are archival replay results, not a new live run.

No current account-specific schema entitlement plus exact no-incremental-charge
proof was established for a fresh capture. Old metadata offerings and zero live
estimates are not that proof. GC BBO is considered currently unavailable. No
new live connection, paid request, historical download or upgrade was initiated.

Next phase: independently calibrate/hold-out price and freshness policies on
licensed windows, establish authoritative session/roll evidence, complete
watermark-driven candle publication and safe full-session rotation, validate
extended schemas and sustained recovery under freshly verified existing-plan
entitlements, and resolve American gamma numerical failures. Preserve all
frozen-selector, risk, GIL and approval requirements throughout.
