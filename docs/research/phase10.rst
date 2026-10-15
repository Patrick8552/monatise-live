Phase 10: live validation and read-only native analysis
=====================================================

Phase 10 adds an opt-in local request boundary around the existing Phase 9 pure
engines. It does not register a production route, start an application, subscribe
to market data, send a message, qualify a trade or execute an order. Frozen H1
selection and its two-hour lifetime, trade/GIL provider and approval rules remain
unchanged. American gamma convergence and GC/XAUUSD basis mapping are separate
research work and never prerequisites for ordinary native futures context.

Request native analysis
-----------------------

From the Phase 10 checkout using the existing Python environment with the
gold-data dependencies, run::

  python -m monatise.research.phase10.cli --capture /private/path/to/reviewed-capture \
    --symbols GCZ6 ESZ6 NQZ6 --timeframes 1m 5m 15m 1h 4h --format text

Installing the package also provides the ``monatise-analyse`` entry point.
Default output is JSON; text output summarizes existing engine results and missing
evidence. ``--as-of`` accepts an explicit timezone-aware timestamp. Cutoffs in the
future, invalid frames and requests outside the bounded record budget fail closed.
Exact contract names are required; there is no implicit continuous-contract roll.
``--list-instruments`` reports supported research products and disabled candidates.

Collector/operator setup calls ``phase10.source.prepare_inputs`` once with the
already reviewed policies, verified native anchor directory and dated session.
Its exclusive private manifest binds the capture authorization and existing policy
hashes. Analysis requests then need only the capture directory. A supplied policy
cannot silently replace the one that authorized collection. Native anchor prices
are decoded from their sealed source records, not entered by hand.

``phase10.source.load_capture`` opens existing SQLite databases read-only and
observes a hash-verified feed cursor/segment index in one state transaction. It
replays only that committed native prefix, checking byte and metadata hashes,
source positions, native decoding and sealed segment hashes. Active segments use
read transactions; closed WAL stores are read without creating journal sidecars.
A sealed segment with a nonempty unreviewed WAL is rejected. Missing/corrupt data
is never repaired or filled by this interface. The source's full framed-journal
reconciliation and exchange-completeness review remain separate checks. The v1
capture reader supports the current definition/trades/OHLCV-1s/OHLCV-1m campaign;
a live in-process ``AnalysisService`` can expose other already validated components.

The default mandatory context is minute price data. Missing trades, quotes, OI,
options or longer frames have independent availability. The existing coordinator
returns structure, liquidity, sweep, zones, reclaim, Fibonacci and regime results
where their actual data requirements are met. Short histories explicitly retain
messages such as ``insufficient candles: required ..., received ...``. Executed
VWAP, exact-price profile/POC and known-side CVD describe the retained captured
window, not a certified full exchange session. Rolling replay retains at most
50,000 canonical market records per instrument; retention scope is reported.
The default replay ceiling is two million native records, explicitly bounded up
to ten million. Budget exhaustion does not return a truncated replay as complete.

``AnalysisRequest`` and ``AnalysisService`` isolate instruments and return native
price namespaces, requested missing frames, source health, calculation and access
hashes. Overall availability is UNAVAILABLE when the source is quarantined or its
active progress checkpoint is stale, even if older component calculations exist.
Those calculations remain inspectable as historical context. Every result retains
NO_TRADE, NOT_EVALUATED, false execution/approval/GIL flags and zero orders.

Calibration protocol
--------------------

``phase10.calibration`` and ``phase10.campaign`` enforce predetermined disjoint
training and holdout windows. Native same-time executions retain their original
multiplicity and event/receive timestamps; ordering uses event time, receive time
and original global ordinal. The Phase 9 fit default still requires distinct event
timestamps; explicit tie-preserving calibration is opt-in. No sparse resampling or
synthetic timestamp perturbation is used to inflate adjacent price increments.

``train_candidate`` cannot run before the training availability window ends, excludes
quarantined attempts and records quality exclusions, partial spans and source
hashes. It freezes policies once with exclusive creation and reports scope failures.
No suspicious-price auto-anchor or production policy promotion is introduced.
``evaluate_candidate`` uses the frozen policies without refitting, preserves later
rejections and reports missing/invalid evidence. Next-session evaluation requires
reviewed actual pre-session canonical anchors: an old training-end price cannot
stand in for the next session's initial state. Anchor updates retain the unchanged
policy and must be causal and source-bound; the first suspicious opening price
cannot become its own justification. Synthetic fixtures are engineering evidence.

Campaign on 2026-10-15/16
-------------------------

The original training window remains 03:45--12:00 UTC Oct 15; same-day holdout is
12:00--20:45 UTC. Independent next-session holdout is Oct 15 22:00 through Oct 16
21:00 UTC. These windows are not shifted after observing failures. The genuine
complete-session target is the latter 23-hour span, with bounded closing-candle
drain and fresh pre-open entitlement/cost/definition/clock evidence. No paid
historical acquisition, subscription change, deployment or trading is authorized.

The first longer attempt stopped after 1449 seconds at approximately 04:04 UTC
with ``provider_disconnect_or_error_ohlcv-1m``. Its capture is quarantined and all
8490 native records/1860 local publications remain preserved privately. The old
work runner's final progress string said completed partial capture, but its
quarantined health correctly invalidates live reliability. That string is not a
pass. A separately reviewed continuation opened after 04:32 UTC with fresh zero
incremental live estimates, existing active Standard CME entitlement, bounded
clock review, genuine anchors and a new one-use permit. The interruption remains
a calibration/coverage gap. It was not silently backfilled or called recovery.

The old watcher retained no underlying exception class. Future captures now retain
bounded schema/stage/class/errno diagnostics without exception messages or raw
payloads. Automatic retries remain zero. Controlled synthetic recovery tests and
a separately reviewed genuine restart do not certify gap-free live outage recovery.
The full-session verdict and broader calibration remain pending real elapsed data.

Additional-product audit
-------------------------

The catalog lists YM, RTY, CL and SI as disabled candidates. Public specification
references and exact included instrument-definition audits establish an initial
review; they do not enable analysis. The bounded definition-only HTTP requests
had individual zero cost estimates under the existing Standard CME plan and
opened no extra live connections. Native DBN files remain private.

YM uses a 1-point tick and USD 5/index-point multiplier; RTY 0.1 and USD 50;
CL USD 0.01/barrel and 1000 barrels; SI USD 0.005/troy-ounce and 5000 ounces.
Venue display factors are preserved, never reapplied to normalized market prices.
SI's venue minimum-increment-amount/display relationship does not reconcile with
the reviewed notional tick value using the same identity as the other three.
It remains an explicit venue-field review item; no native field is rewritten.
Dated calendars/holidays, delivery/expiry handling, schema quality calibration and
genuine live analysis are still required for all four products. Existing normalizer
and LiveScope allowlists remain GC/ES/NQ; all candidate enable flags remain false.

Primary references:

* https://databento.com/docs/schemas-and-data-formats/instrument-definitions
* https://databento.com/blog/tick-sizes-and-values
* https://www.cmegroup.com/markets/equities/dow-jones/e-mini-dow.contractSpecs.html
* https://www.cmegroup.com/markets/equities/russell/e-mini-russell-2000.contractSpecs.html
* https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.contractSpecs.html
* https://www.cmegroup.com/markets/metals/precious/silver.contractSpecs.html
* https://www.cmegroup.com/trading-hours.html

Validation boundaries
----------------------

``tests/research/phase10`` covers missing optional evidence, unavailable stopped/
stale sources, source/cursor integrity, policy binding, actual read-only file
behavior, native multiplicity, future cutoffs, immutable candidates, heldout
spikes, causal independent-session anchors, disabled candidate descriptors and
sanitized disconnect diagnostics. Phase 9/live-preparation regression tests and
the full suite use disposable local PostgreSQL/Redis without live credentials.
The unchanged frozen H1 checkout is tested independently. Successful offline tests
or a short genuine request are not a sustained-live or deployment certificate.

Validation recorded on 2026-10-15
---------------------------------

The final full suite passed 2544 tests with zero failures/errors/skips using
disposable local PostgreSQL/Redis. The 29 Phase 10 cases and 80 Phase 9 cases are
included. The unchanged frozen H1 checkout separately passed 53 tests. A real
active-capture request verified a committed prefix for all three instruments
without provider requests or source database mutation; its availability remained
partial/contextual and missing engine/history evidence was explicit. The same
interface returned overall UNAVAILABLE on the preserved quarantined capture.
These observations do not close the pending complete-session or calibration
holdout requirements. No source market-price archive or credential is committed.
