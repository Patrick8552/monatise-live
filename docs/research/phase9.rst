Phase 9: native analytical research pipeline
============================================

Status: implemented research interfaces, chronological native-data calibration,
automatic local candle publication and bounded full-session storage rotation.
Genuine bounded live validation is documented below. This is not a deployment
or sustained-live certificate.
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
No exchange-continuity certificate is issued. Native interval markers attest to
provider publication, not complete exchange-event capture.

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
FULL/WAL storage. Native framed journals are still written/fsynced first. Definition snapshots are
validated independently by FeedState against native identity and economics, kept
raw, and do not enter market-volume/candle observations. Replay
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
there is no automatic entitlement renewal. At clock-review/resource/session boundaries,
the service stops safely; a permit authorizes opening its bounded attempt, while
optional independent clock renewal maintains research UTC bounds during it. Preload explicitly reviewed new contracts for a roll;
there is no automatic continuous-symbol roll or back-adjustment.

Live defaults remain definition/trades/MBP-1. Additional MBP-10, native OHLCV-1s,
OHLCV-1m, OHLCV-1h, statistics (published OI) and status schemas are opt-in and
still require matching entitlements. Non-OI statistics stay raw without being
misrepresented as OI. MBO reconstruction is not implemented in Phase 9.
Automatic local candle publication and full-session storage rotation are opt-in.
``publication.CandlePublisher`` writes a durable SQLite analytical outbox after
native schema replay completion, monotonic END_OF_INTERVAL watermarks,
definition verification, the existing ten-second
finalization grace, calendar checks and native price/volume lineage verification.
It derives 5s/1m/5m/15m/1h/4h only when every smaller child is represented, prefers
native minute children for longer histories, and never fills missing seconds.
OHLCV buckets retain provider receive-time semantics. A later dated quality fault
retracts affected outputs. Publication checkpoints survive restart and failed
transactions do not advance the in-memory high watermark. This outbox does not
send Telegram, register production output, qualify frozen H1 or invoke trades.

``rotation.RotatingNativeJournal`` seals hash-linked framed DBN segments on byte,
record or elapsed-time limits without reconnecting SDK clients or resetting global
source ordinals. ``RotatingSpool`` applies the same limits to private SQLite raw
segments and retains a global delivery index across rotations. Sealed native/spool
segments are hash verified on replay. Resource/segment ceilings stop acquisition;
archives are retained. An accelerated 23-hour session exercises bounded rolling
memory and 1m/1h/4h candle publication across rotations. This is an engineering
test, not evidence of a 23-hour genuine feed session.

``calibration.fit`` fits one contract/schema using chronological training only;
``Calibration.validate`` uses later untouched records without refitting. Native
bar policies learn OHLC excursions, separately from tick-to-tick trade changes.
All nine GCZ6/ESZ6/NQZ6 x trades/OHLCV-1s/OHLCV-1m scopes passed the initial
20-minute native live-replay split with zero holdout rejections. This short Asian
session does not establish open/news/roll regime coverage. Independent held-out
sessions remain necessary before production policy approval. Fresh genuine raw
anchors are source-bound; no manual price entry or suspicious-price auto-reanchor
is used by the bounded live check.

Optional ``clock_refresh`` obtains overlapping bounded ClockReview evidence before
expiry without changing the OS clock. Queued records retain the contemporaneous
review; future reviews cannot qualify earlier captures. Every original local and
provider timestamp is retained. These are two-source unauthenticated SNTP research
bounds, not authenticated production time certification.

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
without changing original clocks. Four NQ minute bars were quarantined under an
initial descriptive price policy; the continuation adds a separate native
timeframe calibration and untouched chronological holdout, with broader
cross-session validation still required. One genuine OG pricing pair solves IV but rejects American gamma
for fine_bump_lattice_gamma_instability; neither missing OI nor gamma exposure is
fabricated. These are archival replay results, not a new live run.

Continuation verification (2026-10-15)
--------------------------------------

The authenticated Databento account portal showed the existing Standard CME
Futures/Options subscription active at USD 199/month, with the Standard CME live
license active and renewal shown as 2026-11-01. Fresh read-only metadata estimates
for the exact three raw symbols and definition/trades/OHLCV-1s/OHLCV-1m scopes
were zero. The fixed Standard plan includes live access; no plan, license, budget
or billing setting was changed. Estimates are not a settled invoice. Only live
sessions and included intraday replay were used; no historical timeseries
acquisition or additional market-data purchase was made.

A definition bootstrap and bounded 20-minute native live replay succeeded and
were sealed privately. The replay contained 12 definition, 5,867 trade, 3,229
second-bar and 87 minute-bar/control records. Calibration excludes structurally
unusable/forming observations and uses disjoint chronological event-time train
and holdout sets; both halves were acquired in that single replay, not separate
independent trading sessions. Counterfactual spikes are explicitly synthetic and
never fitted. The prior four NQ bar rejections were descriptive initial-policy
results and are not evidence that the newly calibrated policy fails.

The bounded persistent-service live run and final regression counts are recorded
in the linked PR and private evidence summary. All connection attempts are bounded
and explicitly authorized; no service is left running after verification. No
production startup, frozen H1, trade/GIL qualification, provider hierarchy or
execution setting is changed. Remaining production work includes independent
cross-session calibration, a genuine full-session soak/recovery exercise,
authenticated time discipline, exchange continuity proof where required and
numerically stable American option gamma validation. Current derivative/GIL
limitations remain as described above.
