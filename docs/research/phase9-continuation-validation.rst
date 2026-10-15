Phase 9 continuation: genuine live verification
===============================================

Code: f890669a99e74a8bf4c73eee03a4d947fdf41e23.
Branch: codex/monatise-phase9-live-data-pipeline; draft PR #126.
Date: 2026-10-15. No production deployment or main merge.

Implemented and connected
-------------------------

* ``phase9.calibration.fit`` and ``Calibration.validate`` separate chronological
  training from untouched later event-time holdout, per contract/schema. Candle
  OHLC ranges and execution increments use separate policies.
* ``phase9.publication.CandlePublisher.advance`` produces a durable local research
  outbox after definition/replay verification, native END_OF_INTERVAL markers,
  calendar/lineage checks and the unchanged ten-second finalization grace. Missing
  children are not filled. Late faults retract affected outputs.
* ``phase9.rotation`` rotates native DBN journals and SQLite raw segments by
  records, bytes or time, without reconnecting SDK clients or resetting global
  source positions. Sealed segments are retained and hash verified.
* ``databento.live_feed`` renews bounded independent clock reviews and retains
  contemporaneous evidence for records already queued. Original clocks are not
  rewritten. These are research UTC bounds, not authenticated time certification.
* ``phase9.pipeline`` retains bounded rolling trade/bar windows, preserves native
  bar lineage independently of high-rate execution retention, and excludes a new
  unfinalized bar from analysis without erasing earlier finalized context.
* ``phase9.service`` keeps equivalent native definition snapshots in the verified
  metadata/raw path. Their different raw hashes do not force redundant market
  observation normalization; changed identity/economics still fail validation.

Genuine final-revision run
--------------------------

The existing subscribed live service supplied exact GCZ6, ESZ6 and NQZ6 native
instrument IDs. Schemas: definition, trades, OHLCV-1s and OHLCV-1m. Duration:
363.522 seconds including controlled shutdown/sealing. All four replay markers
completed; all three definitions verified. Final health: CAPTURED_CONTEXT_FRESH.

* 2,739 native records verified across 49 native journal segments.
* 14 sealed SQLite spool segments, with 2,739 durable source records.
* 2,184 accepted market observations: 1,579 trades, 587 second bars, 18 minute bars.
  Definition/control records remain raw and do not become market volume.
* 610 automatic local candle publications: 573 one-second, 19 five-second and
  18 one-minute bars. Missing/no-trade second intervals remain unknown.
* One successful automatic clock renewal, with no timestamp rewriting.
* Zero transport/component/pipeline quarantines or faults in the final run.
* Trade features and finalized native minute price analysis available for every
  contract. Optional book/OI inputs were unsubscribed. Short/incomplete second
  histories remained unavailable where continuity requirements were not met.
* Every result remained NO_TRADE / NOT_EVALUATED, with execution, publication
  authorization, production registration and GIL compatibility disabled.

Read-only offline replay verified every sealed spool segment, rebuilt all 2,184
market observations without rejection, and reproduced the original analytical
hashes for all three contracts. Every published candle's body hash, native price/
volume lineage, finalization delay and interval bound was rechecked (610/610).
The source databases were opened read-only; no new network request was made.

This is a genuine bounded live run, not a genuine 23-hour soak. The generic
service envelope retains its conservative fresh_live_operation_verified=False
no-certification default; the separate verification receipt records these actual
capture/publication results. No exchange-event completeness is certified.

Calibration and regression evidence
------------------------------------

A separate included 20-minute live replay provided the initial research fit:
3,512 chronological training samples and 3,514 untouched later holdout samples,
across all nine GCZ6/ESZ6/NQZ6 x trades/OHLCV-1s/OHLCV-1m scopes. All passed with
zero holdout rejection; separately labeled synthetic extreme spikes were rejected.
Both halves came from one acquisition window. This does not establish independent
cross-session or all-regime calibration. Eight forming bars and 25 structurally
unusable clock observations were excluded without applying later time evidence
retroactively. Trade-volume multiplicity was preserved.

* Full repository: 2,512 passed, zero failures/errors/skips, with disposable local
  PostgreSQL/Redis and no production DSNs/live keys in the test environment.
* Phase 9: 77 passed, included in the full total; 17 continuation cases are in
  ``tests/research/phase9/test_continuation.py``.
* Frozen H1: 53 passed separately in the clean pinned checkout at
  f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35. Source, directional-parent selection,
  two-hour lifetime and qualification behavior are unchanged.
* Accelerated 23-hour engineering session: 1,380 native minute bars, 23 hourly
  outputs, five 4h outputs and 23 SQLite rotations with bounded memory. It is not
  a genuine complete-session network/market trial or CME holiday-transition test.

The first genuine integration attempt quarantined on previously unsupported
END_OF_INTERVAL code 4. The intermediate six-minute attempt exposed duplicate
metadata hash checks and latest-unfinalized-bar suppression. Those causes were
fixed and covered by regressions before final-revision verification. Original
failed/intermediate captures remain private and retain their original outcomes.

Cost, shutdown and remaining evidence gaps
------------------------------------------

Fresh account entitlement evidence confirmed the existing live plan; exact-scope
live metadata estimates were zero. Only included live sessions/intraday replay
were used. No purchase, upgrade, paid historical acquisition or billing change
was made. The post-run portal displayed zero total live connections and recent
usage USD 0.00; reporting may lag, so this is not a settled invoice certificate.
Credentials and licensed native records remain private and are excluded from Git.

Overall production readiness remains PARTIALLY. Next evidence work is independent
open/news/roll calibration, a genuine full-session soak/outage-recovery exercise,
authenticated time discipline and realistic physical SQLite/index/WAL disk budget
review. Interrupted raw/cursor mismatches still stop for review. New sessions and
contract rolls need explicit reviewed scopes/current permits; storage rotation
never silently renews entitlements or selects another contract. No strategy gate
or GIL provider/certification rule changed; existing options numerical/OI gaps
remain outside the validated four-schema futures capture.
