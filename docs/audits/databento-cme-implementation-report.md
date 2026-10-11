# CME implementation report — 2026-10-11

Local implementation and offline validation are complete. No production activation,
deployment, orders, strategy-policy changes, signals or new Databento usage occurred.
Repository baseline: `0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`.

## Audit, architecture and reuse

The [pre-implementation audit](databento-cme-implementation-audit.md) inventories
reuse, missing functionality, technical debt, compatibility risks, indicator
status, proposed changes, tests and costs. The [architecture/runbook](../databento-cme-research.md)
documents interfaces, dataset/schema matrix, provenance, storage, budgets and
reproduction commands. [Saved authenticated metadata](databento-observed-capabilities.json)
establishes GLBX.MDP3 and schema availability as observed on October 11, not a new
licensing/entitlement assertion.

Existing local research components were found, audited and reused rather than
reimplemented: identity policy, GC/OG definition registry, guarded SDK acquisition,
immutable DBN/ZSTD archive, PostgreSQL CAS manifests, bounded historical replay,
native GCZ6 normalization, UTC candle aggregation and the isolated diagnostic
subprocess. [Original source hashes](databento-reused-sources.json) bind those
components to the prior `a144db7` source. Additional modules provide observed
dataset/contract discovery, SQLite local manifests, atomic budget reservations,
overlap/partition cache planning, generic CME candles and reviewed rolls, immutable
derived layers, disabled native depth/MBO adapters and isolated options input joins.

Production reuse is limited to the existing normalizers' explicit optional
identity policy and namespace. Existing legacy defaults remain unchanged. The
GC/XAUUSD basis service, canonical analytical engines, GIL provider hierarchy,
FTMO, MT5, Telegram, risk controls and deployment configurations remain unchanged.
QuestDB/Grafana/Kafka/Redis infrastructure was not introduced for research storage;
temporary test-only Redis and PostgreSQL instances were stopped after verification.

## Data verification and historical GC replay

[Machine-readable acceptance evidence](databento-cme-validation.json) records
source/request/archive/input/replay hashes and the test summary. The existing raw
archives remain outside this Git repository. Hash/metadata validation covered
**24 complete native archives and 6,563,434 records**:

| Native schema | Records verified |
|---|---:|
| definition | 23 |
| ohlcv-1m | 34,209 |
| trades | 428,821 |
| mbp-1 | 6,100,133 |
| status | 248 |

The expanded diagnostic input's **34,207 minute bars** were individually matched
to native record hashes, contract IDs, timestamps, prices, volumes and original
acquisition/admission clocks. All **9,768 derived bars** were checked against their
minute children, OHLC/volume formulas and source-hash lineage. The difference
between acquired and diagnostic minute counts remains in the preserved quality
records; no new bar was manufactured to fill it.

The frozen selector checkout remained clean at
`f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35`. Two fresh subprocess replay outputs
equaled each other and the saved report exactly:

* 557 H1 assessments.
* 69 valid constrained Fibonacci assessments across 12 distinct valid H1 episodes.
* 1.272, 1.414 and 1.618 formulas and causal confirmation times verified.
* The earlier reported evaluation-only subset remains 22 valid of 112; the 69
  include warmup/exploratory observations and are not independent trades.
* 12 saved raw-level records were audited; no reported first-touch window needed
  validation because all their first-touch fields were null.
* Qualified entries/stops/RR, trades, profitability and trade win rate remain null.
* GIL, production integration, publication, approval and execution remain false.
* Historical local availability is explicitly retrospective; point-in-time
  certification and exchange continuity remain false.

Input SHA-256:
`c572e5f52f96cbc2e50df838368df6f2632dd04ae3f2def73a465fd4e565252b`.
Fresh replay SHA-256:
`7d333eaa6929aaa9f9593c1d69d076ed4313f004297c323ae014a568502bf78d`.

## Costs, cache and quarantine

Incremental Databento usage and credit consumption for this implementation:
**$0**. Default new-acquisition budget is $0. Cache tests verify exact requests,
supersets, complete unions of partitions, partial overlaps and true uncovered
ranges. The existing authorized GC manifests were indexed locally without a
provider request. Raw bytes and complete request coverage are verified before
cache admission. The saved five-day minute scope was reusable.

Successful historical manifest estimates sum to **$1.488967996091**; this is the
sum of old saved request estimates, not actual billing or a new quote. Actual
billed amounts for those 24 saved successful requests remain unknown. Two prior
failed attempts remain quarantined and were neither retried nor promoted:
`acquisition-result-13.json` and `warmup-result-06.json`.

New spending requires a fresh reliable exact-scope estimate, licensing review,
explicit receipt and configured shared budget. Signup credit never bypasses these
checks. Persistent one-use reservations prevent duplicate/overlapping network
attempts across processes. Unknown billing holds the reservation. Reviewed
settlement reports API usage, credit used and cash separately. Provider estimates
cannot guarantee a final charge cap; account-side controls and billing review
remain necessary for separately approved downloads.

## Adapter, options and test results

The final full Python suite passed **1,948 tests, zero skipped, zero failed**, using
the locked optional SDK and disposable UTF-8 PostgreSQL/Redis services. The frozen
selector's separate unmodified suite passed **53 tests, zero skipped/failed**.
No test incurred market-data charges or used production credentials. The initial
sandboxed suite was blocked by native compilation/local-server restrictions;
the authorized isolated rerun passed. A temporary SQL_ASCII cluster was corrected
to UTF-8 in the test harness without any production code change.

Coverage includes dataset/schema and symbol distinctions, exact identities and
maturity, request construction, native DBN/schema normalization, nanosecond clocks,
bar geometry/ticks/finalization, reviewed sessions/closures, missing minutes,
duplicates/revisions, explicit rolls, deterministic aggregation/replay, immutable
archive recovery, persistent CAS, cache reuse/partitions, concurrent budgets,
approval/credit gates, one-attempt transport, quarantine/retry safeguards, options
definitions/OI clocks and default-disabled advanced modules. Existing Gold,
crypto/index, risk, native execution guards and approval regressions passed.

Trades retain unknown aggressor sides. MBP-1/10 tests distinguish visible size
from traded volume, check ordering/sentinels and expose formula-bound metrics.
MBO preserves order events and informational fills but has no certified book or
queue reconstruction. Neither MBO nor MBP-10 historical acquisition is enabled.
GC options inputs reuse standard OG normalization and exact GC joins; missing OI
stays null, stale/future/mismatched evidence rejects, and no GIL/GEX output activates.

A 10,000-record synthetic replay probe completed in 0.556 seconds, approximately
18,001 records/second with tracemalloc enabled, 609,407 peak traced bytes, bounded
1,024-entry dedup and 128-level profile. This is an engineering observation on
this host, not a live throughput certification or trading-performance result.

## Limitations and approvals for the next phase

1. Preserve and make the frozen selector's pinned source checkout available to
   future research machines. It is intentionally not rewritten or bundled with
   unreviewed shared-engine changes. Actual raw archives also remain local/licensed.
2. Reconcile actual provider billing for existing successful and quarantined
   requests before authorizing any retry or additional acquisition.
3. Review GLBX.MDP3 commercial/non-display/redistribution/derived-output entitlement
   and supply a fresh exact-scope metadata estimate, human receipt and budget for
   any new historical data. No signup-credit assumption authorizes spending.
4. Acquire/review real ES/NQ/CL definitions and conventions before economic analytics;
   their current general discovery/request tests are engineering fixtures.
   Actual native GC research validation is narrowly reviewed for GCZ6.
5. Supply independently reviewed CME session/holiday/status/continuity evidence,
   causal local observation archives, and broker-side synchronized quotes for a
   separately validated GC/XAUUSD basis. UTC H4 session truncation/staleness remains
   visible and does not qualify a trade.
6. Review actual OG/weekly definitions, chains and OI publication semantics, rates,
   American Greek stability and signed-positioning assumptions before GC gamma
   analytics. ThetaData/Unusual Whales GC options coverage needs verification.
7. State a bounded depth/MBO research question and receive separate cost approval
   before enabling acquisition. Snapshot/lifecycle/recovery certification is
   required for queue/microstructure claims.
8. Separately authorize live subscription, replay-watermark/reconnect ownership,
   runtime integration and deployment. Policy activation and any trading remain
   separate approvals; current production operations were not touched.

The implementation commit hash is supplied with the final response and can be
read from the local Git HEAD. No push, pull request, merge or deployment was made.

## File inventory

Shared modified files: `.gitignore`, `README.md`,
`monatise/adapters/databento_gold.py`, `monatise/application/gold_options.py`.
New identity adapter: `monatise/adapters/databento_identity.py`.

New/reused isolated research files:

* `monatise/research/__init__.py`.
* `monatise/research/databento/`: `__init__.py`, `acquisition.py`, `archive.py`,
  `registry.py`, `replay.py`, `benchmark.py`, `datasets.py`, `controls.py`,
  `candles.py`, `advanced.py`, `options.py`, `verify_existing.py`.
* `monatise/research/gc_fib/`: `__init__.py`, `bootstrap.py`, `candles.py`,
  `native_contract.py`, `preflight.py`, `runner.py`, `worker.py`.
* `monatise/research/gold_retrospective/`: `__init__.py`, `runner.py`.
* `monatise/research/broker_xauusd/`: `__init__.py`, `models.py` (provenance helpers).
* `scripts/test_cme_offline.py`.

Tests: `tests/research/__init__.py`, `test_databento_foundations.py`,
`test_databento_history.py`, `test_databento_history_postgres.py`, `test_gc_fib.py`,
`test_gc_native_contract.py`, `test_cme_infrastructure.py`; sanitized metadata
fixture `tests/fixtures/databento/glbx_metadata_2026-10-11.json`.

Documentation: this report, `docs/databento-cme-research.md`, the initial audit,
reused-source hashes, observed-capability metadata and acceptance JSON under
`docs/audits/`. Licensed/raw diagnostic outputs, test logs and local ledger stay
in ignored `private-reports/`; no credentials or raw records enter the commit.
