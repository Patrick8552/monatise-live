Phase 11: versioned native futures interpretation
================================================

Scope and state
---------------
Research implementation on top of 0c1f1bc, isolated from the immutable collector
379c1fc and reader 0c1f1bc. GitHub PR130's head was freshly verified as 0c1f1bc.
The user cancelled the old finite calibration campaign; its heartbeat is paused
and its owned finite awake assertion has exited. No capture is active. There is
no frozen broad candidate, no completed full-session soak, and no live recovery
claim. Old failures, source admission bits, native bytes and checkpoints remain.

Databento performs exchange-to-DBN normalization. Monatise maps those records,
validates individual capabilities, and builds analytical features. These are
separate layers. Fixed-point prices stay exact integers/Decimal at 1e-9 scaling;
display_factor never rescales market prices. Raw bytes, flags, timestamps,
sequence, instrument definition hashes, source ordinals and multiplicity remain.

Measurement contract
--------------------
The new mapping version is native-futures-normalization-v2. The guard measurement
is max-inspected-price-distance-from-previous-reference-v2. For OHLC this means
max(abs(O-last_close), abs(H-last_close), abs(L-last_close), abs(C-last_close)).
For trades it is the execution-price increment. Each exact contract/schema has
its own guard and reviewed anchor. Calibration, screening and accepted rolling
updates use this same excursion. Rejected records never update the sample.
Tick bounds, robust median/MAD scale, source quality checks and explicit recovery
reviews are retained. No thresholds were increased to rescue ES/NQ.

The 128-candle flat-close reproduction now stores alternating 8/12-tick ranges,
rather than zeros; a 13-tick continuation is represented by the learned envelope.
Large discontinuities, malformed OHLC, off-tick prices and changed contracts
still reject. WARMUP remains explicit. A legitimate exceptional move can still
require review: price screening is not proof that an exchange record is corrupt.

Clock and replay contract
-------------------------
ts_event and ts_recv remain independent original nanosecond UTC fields.
ts_in_delta is retained; publisher-send time is derived only for a nonclamped,
valid delta/receive clock. Source order uses ts_recv where the schema has it,
otherwise ts_event. No receive regression is accepted. Equal timestamps at new
native positions still count. A repeated source position remains idempotent.

An unflagged exchange timestamp need not increase or precede the provider clock.
Both clocks still require valid contract bounds and contemporaneous capture
bounds. F_BAD_TS_RECV is never forgiven for ordinary trades. Receive-time trade
features and provider bars remain separate from event-time-derived candles.
The latter sort bounded source sets, and retract a finalized bucket when a late
execution affects it. Raw ingestion order is never sorted or rewritten.

Live replay starts remain based on the documented exchange-time cursor. Cursor
checkpoints also retain provider-index order and whether exchange time regressed.
Recovery from a nonmonotonic exchange-time cursor refuses an unsafe last-event
seek and requires a separate overlap review. This is an intentional remaining
recovery restriction, not automatic reconnection. Existing exact tied prefixes
and the separately reviewed INITIAL-only capture-clock translation are unchanged.

Capability-specific quality
---------------------------
semantics.assess_native_record reports contract/schema identity, numerical price
and quantity validity, event/receive/capture validity and per-feature restrictions.
An unrecoverable channel-gap flag is not described as a malformed price. A
canonical mapping or screening rejection cannot advertise eligible capabilities.

Ordinary trade receive-quality failures still withhold all trade flow, VWAP and
profiles. The existing source-verified typed GC review can retain independently
validated native candle context. Global transport/clock/storage uncertainty stays
global. Unknown faults are not narrowed by a generic healthy flag.

The offline MBO adapter has an explicit snapshot context for documented
F_SNAPSHOT|F_BAD_TS_RECV Add/cleaR seeds, including an empty snapshot's undefined
receive timestamp. It preserves that timestamp and never supplies an ordinary
receive index, publisher-send time or temporal-liquidity eligibility from it.
No MBO subscription or order-book reconstruction was enabled. These snapshot
exceptions do not apply to ordinary trades.

Sparse bars and lineage
-----------------------
NativeBarCoverage binds an exact contract/schema, start/end, native interval
marker hash, captured-prefix hash, availability and clock review. Coverage starts
after any skipped bootstrap/recovery anchor bucket. It requires acknowledged,
replay-complete transport, verified identities, actual native END_OF_INTERVAL
and no dependent quality fault. Heartbeats and absent bars alone are insufficient.

Intervals report OBSERVED_VALID, VERIFIED_NO_TRADE, UNKNOWN_COVERAGE or
MISSING_OR_REJECTED. DISPLAY_INTERPOLATED is reserved; this implementation creates
no interpolated bars. VERIFIED_NO_TRADE is conditional on complete captured
provider-stream evidence and documented provider OHLCV semantics; it is not an
independent exchange-completeness certificate.

A parent may use observed native children plus source-verified provider-empty
children. Its open/close come from the first/last actual child, highs/lows from
actual children, and volume is the sum of actual volume. Empty parents are not
invented. Unknown gaps and session edges still block construction. Event-time
trade candles cannot borrow provider receive-time empty-interval proofs. Lineage
checks the exact accepted native hashes, multiplicity and registered coverage
proof, and fails on any dependent source fault. Quiet parents use the coverage
review's contemporaneous clock, not an expired child's clock review.

Publication and the native futures request path use these proofs. Native swings,
Fibonacci and price-based liquidity proxies remain causal and descriptive. Missing
pivots/history/timeframes remain unavailable. Crypto engines, frozen H1 selection
and expiry, GIL, synthetic spot mapping, broker synchronization and execution
are excluded. Ordinary H1 is allowed as data. Predictive validity, entry signals,
dealer positioning and execution qualification are not certified by this change.

Delivery and durability
-----------------------
The collector uses Databento's documented ``Live.__aiter__`` method. Iteration
starts streaming; it is never preceded by ``Live.start``. Subscription calls run
off the owned networking loop. SDK buffering and backpressure are managed by the
SDK, with reconnect disabled and slow-reader behavior ``warn`` (never skip).
No SDK private session/protocol/queue/socket attributes or buffer methods are
inspected or changed. Public ``terminate`` closes the finite attempt.

An application consumer runs outside the networking loop and hands each yielded
record to a bounded queue. Waiting for queue space happens on that worker, with
at most one in-flight application record per connection. The SDK networking loop
can still process incoming data. Shutdown drains in-flight application records
before sealing. Nonblocking callback-only engineering adapters retain explicit
overload count/hash-chain quarantine. No reconnect or retry is introduced.

V2 framed journals preserve the original local UTC application-receive timestamp
plus a separate monotonic arrival timestamp. Native DBN timestamps/bytes remain
unchanged. Journal/spool rotation and delivery-stall elapsed time use monotonic
time; wall-clock regression is a recorded diagnostic rather than fabricated or
clamped UTC. The spool hash binds both clocks. Readers require a source-bound V2
clock declaration, verify monotonic arrival across segments, and preserve legacy
V1 wall-order verification. Independent UTC uncertainty/expiry and provider field,
flag, contract, sequence and as-of validation are unchanged. A genuinely invalid
clock review still withholds dependent information.

Fixed-memory latency histograms measure handoff, queue residence, consumer work,
journal writes, fsync, spool transactions and checkpoints. Public-iterator delivery
counts, loop responsiveness and bounded error-stack locations replace private SDK
wire/socket probes. Wire-level silence is not diagnosed by these application
counters. Error reports retain bounded local validation codes and stack locations,
while omitting arbitrary exception text that may contain secrets or licensed data.

Per-record journal fsync and SQLite FULL/WAL commits remain. The local controlled
burst demonstrated adequate bounded handling; unsafe asynchronous buffering or
unverified batching was not introduced. These measurements are not a production
capacity certificate. Batched durability remains a later optimization only if
measured workloads require it, with atomic raw/cursor recovery tests first.

The old stall remains UNRESOLVED_DELIVERY_SILENCE: at failure all four network
loops were responsive, queue depth was zero, callback/processed clocks matched,
and no typed transport exception was retained. Nonblocking callbacks remove a
verified local risk but do not prove that they fix that distinct silence. New
instrumentation is designed to narrow it during a separately authorized trial.

Versions and historical evidence
--------------------------------
Startup anchors and live replay seek clocks are separate. A trade price guard
binds to the sealed native anchor's ts_recv (provider index), while the INITIAL
replay cursor and source reference retain its original ts_event. Native OHLCV
uses ts_event as its index. The bootstrap re-reads the anchor bytes to verify
both domains and the exact price/hash; a caller-supplied event timestamp cannot
substitute for a receive-time anchor. The v2 reader derives the same index from
raw bytes and rejects any conflicting anchor_index_ns receipt. Neither timestamp
is rewritten and no threshold, initial identity tolerance or recovery rule is
widened. Regression tests include unflagged event>receive clocks followed by
valid receive-ordered trades that still precede the old event-time anchor.

New source readers require normalization-v2 in BOTH immutable authorization and
analysis-input receipts. Old captures require their original immutable reader;
editing a policy or switching a pointer does not migrate them. Frozen candidate
receipts also bind measurement version and PROVIDER_INDEX window/order semantics.
No old candidate was fitted again and no old capture was relabelled clean.

Existing authentic evidence was replayed diagnostically with baseline and new
implementations. All 207424 native/spool positions and hashes were checked. Four
second-bar screening decisions changed (two ES, two NQ). Trade decisions and all
six source-rejected GC receive-quality records remained unchanged. Repetition
produced identical decision and analytical hashes. These hypothetical decisions
are saved separately; original admission, quarantine and first faults remain.
Separate per-product machine-readable reports accompany the implementation.

Prospective stage C (not scheduled or launched)
----------------------------------------------
Only after review of correctness and independent evidence should an operator
request another limited live validation. A new zero-incremental-cost entitlement,
resource, session, immutable-source and contemporaneous-clock review is required.
Predeclare exact PROVIDER_INDEX training/holdout windows before capture; retain
arrival order and multiplicity, include explicit coverage exclusions, freeze one
candidate before inspecting holdout, and report insufficient scopes. Never reuse
the quarantined October15 attempts or diagnostic A/B results as clean training
or untouched holdout. Independent labelled checks are needed to estimate false
rejections/missed invalid records; same-provider corroboration is insufficient.
A new full-session trial must preserve any real sleep/network gap. No automatic
schedule, connection, threshold promotion, production deployment or trade follows.

References
----------
* https://databento.com/docs/knowledge-base/new-users/normalization
* https://databento.com/docs/standards-and-conventions/common-fields-enums-types
* https://databento.com/docs/api-reference-live/basics/recovering-after-a-disconnection
* https://databento.com/docs/schemas-and-data-formats/ohlcv
* https://databento.com/docs/standards-and-conventions/mbo-snapshot
* https://databento.com/docs/api-reference-live/client/live
* https://databento.com/docs/schemas-and-data-formats/instrument-definitions
* https://databento.com/docs/examples/instrument-definitions/contract-notional
* https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html
* https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.contractSpecs.html
* https://www.cmegroup.com/markets/equities/nasdaq/e-mini-nasdaq-100.contractSpecs.html

Provider semantics in the active native-information path
------------------------------------------------------
Databento's live API guide documents hung-connection detection as one configured
heartbeat interval plus ten seconds without any messages (five plus ten is15s).
It also notes that unstable internet may need a larger margin. A Wi-Fi event is
not an input to record validation. Delivery interruption is distinguished from
component record rejection, and retained native evidence remains preserved;
interrupted continuity is never presented as an uninterrupted completed test.
The current finite research attempt policy does not perform an automatic restart.

The native-information path reports actual observation ages without the inherited
local ten-second/relative-bar-age qualification cutoffs. It does not declare old
observations fresh or executable. Locked/missing quote diagnostics are retained
without importing an execution qualification rule into ordinary market context.
Databento SLOW_READER_WARNING under warn behavior is nonfatal and retained with
its source hash; the SDK does not skip records in that mode. Lag, native provider
errors, replay state, exact source identity and data-quality flags remain visible.
These native-path changes do not invoke or alter the excluded legacy engine graph.

Reference: https://databento.com/docs/api-reference-live (System messages,
Hung connection and Slow reader behavior).
