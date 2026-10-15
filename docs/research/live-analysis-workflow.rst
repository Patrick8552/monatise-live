Native live-analysis request workflow
=====================================

This extends the Phase 10 read-only interface, independently of American gamma
research. It does not register a production service, deploy, place orders, alter
the frozen H1/two-hour lifetime, change trade/GIL rules or open a data connection.
Collector and analysis source versions must be recorded separately for each run.

Request an analysis
--------------------

From an installed research package or the reviewed source checkout::

    python -m monatise.research.phase10.cli \
      --capture-pointer /private/reviewed/latest-current.txt \
      --request "Analyse GC, ES and NQ using Databento" --format text

``--capture <exact capture directory> --symbols GCZ6 ESZ6 NQZ6`` still works.
Unique loaded product aliases GC/ES/NQ are resolved from the actual verified
contract metadata. Ambiguous aliases, duplicate resolved contracts, unsupported
products, other providers and execution phrases are rejected. This is a bounded
local phrase parser, not a remote model, provider subscription or automatic roll.
The pointer is an explicitly supplied regular local file containing one absolute
capture directory. Analysis never discovers or starts an alternative capture.

Results identify the exact contracts, evaluation time, captured trade window,
source health, validated candle count and independent engine readiness. They
include available structure/liquidity/Fibonacci context, VWAP, executed-price
volume profile and known-aggressor buy/sell volume/CVD. Missing evidence remains
visible. No qualifying current Fibonacci anchor is a legitimate engine result.
An engine returning context does not establish a frozen H1 trade qualification.

Quarantined or stale source checkpoints force overall UNAVAILABLE while retaining
historical calculations. In particular, an old final report with an empty reasons
list and nonempty stalled_connections still reports the stall. No source error
is cleared and no source SQLite file is modified by a request.

Optional native historical warm-up
-----------------------------------

``--history-manifest /private/reviewed-history.json`` enables explicit separately
reviewed native minute history. No CLI path downloads data, changes a policy or
chooses a replacement anchor. The versioned manifest binds the exact capture's
authorization hash, original minute-policy hashes, native DBN file hash/count,
actual download/review availability times, exact calendar intervals and a second
native DBN file supplying source-reviewed opening anchors. Each first minute's
open must equal its native second-bar anchor; no manually entered price is used.

Every native message is normalized and screened through the unchanged price
guard. File integrity alone does not make prices trustworthy. A retained history
fault withholds warm-up for that instrument, and valid live components continue
independently. Corrupt, changed or unavailable history cannot silently enter the
engines. Earlier as-of requests cannot use a later historical download.

When all sources qualify, native minutes join by exact contract and UTC bucket.
Overlapping revisions are rejected. Complete parents keep their actual immutable
minute children and source hashes; a history/live parent is explicitly labelled
MIXED_AUTHENTIC_HISTORY_AND_LIVE rather than relabeling the original observations.
Synthetic and genuine sources cannot mix. No empty candle or missing child is
invented. Complete multi-session buckets may skip only explicitly reviewed closed
or partial-session buckets, with omissions recorded. Missing bars within reviewed
trading hours remain errors. A scheduled break is not padded with a flat candle.

The history does not repair a live-soak gap or become calibration training input.
Engine lookbacks and the frozen H1 selector remain unchanged. A 50-candle engine
still needs 50 actual validated bars of that timeframe; collecting 50 minute bars
does not supply 50 hourly/four-hour bars. Statistics identify the actual history
window, and trade VWAP/profile/CVD retain their separate captured-execution scope.

Observed warm-up limitation
----------------------------

A reviewed exact-zero-estimate acquisition under the existing active Standard CME
plan obtained 13,596 native minute bars: 4,532 per GCZ6/ESZ6/NQZ6. A separate155
native second bars supplied anchor evidence. The native hashes and point-in-time
identities verify, but the original price guards reject parts of this history:
ES's first opening minute and GC/NQ moves at October14 12:30UTC. The history is
withheld. No threshold is widened, source is automatically reanchored, calibration
window is changed or retrospective acceptance passed off as an untouched holdout.
Source consistency/regime review and frozen candidate validation remain necessary.

Seconds-bar interpretation
---------------------------

Databento documents that OHLCV records are omitted for intervals without trades,
and buckets its native OHLCV by trade provider receive time. ``second_intervals``
compares only the overlapping retained, finalized captured window on that clock.
It reports missing seconds with and without captured executions and bar/trade
volume differences. No captured execution is not proof of no exchange execution.
Quarantined streams and relevant quality faults disable the comparison. Native
trade conditions, retroactive breaks and different stream prefixes may require
further review; the comparison cannot certify exchange completeness or clear a
fault. Sparse bars remain unavailable to engines requiring dense time buckets.

Operational failure evidence
------------------------------

The 04:32UTC current continuation stopped at05:51UTC after about78minutes with
36,931 raw records and7,770 analytical candles. Its sealed source is quarantined
for a delivery stall. No exception class was retained because this stop was a
health condition, not a thrown transport exception. No host sleep was found in
the relevant power log. This does not establish a provider outage or local cause.

The capture boundary now permanently records connection_stalled_<schema> before
final drain, so queued fresh heartbeats cannot erase an observed stop. Bounded
callback counts/last receipts, queue depth, processing lag and publication timing
help distinguish future local delivery pressure from missing callbacks. Existing
15-second liveness allowance and all freshness/quality controls remain unchanged.
No reconnect is automatic. An instrumented new run needs a fresh explicit reviewed
permit/source/cost/clock receipt; a stopped attempt is never resumed invisibly.

Order-flow next stage
----------------------

Current genuine trades support aggressor pressure and captured volume metrics.
No participant identity is disclosed by anonymous exchange orders. A large print
is not proof of a particular institution, dealer inventory, motive or future move.

After the finite soak campaign, a separately reviewed bounded depth trial should
verify exact existing-plan entitlement/$0 estimates, connection and disk budgets,
then capture MBP-1/MBP-10 for exact contracts. Temporal trade/book matching,
replenishment and possible absorption require new feature-specific validation.
Order-level MBO reconstruction and iceberg hypotheses need additional lifecycle,
snapshot, cancellation and recovery tests. They are not implemented live detectors
in this change. No extra subscription or fifth live connection is opened here,
and no additional market session is automatically scheduled.

Primary sources
-----------------

* https://databento.com/docs/schemas-and-data-formats/ohlcv
* https://databento.com/docs/schemas-and-data-formats/trades
* https://databento.com/pricing/
* https://www.cmegroup.com/articles/faqs/market-by-order-mbo.html
* https://www.cmegroup.com/trading-hours.html
