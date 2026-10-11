# Phase 3 — Broker XAUUSD historical observation archive

Status: isolated engineering implementation; no deployment or broker connection.
Branch: `codex/broker-xauusd-phase3`. Starting baseline:
`0851fb7c7b5340e1e0f8d038e30215d6b15ed2ec`.
Canonical Gold source remains `0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`.
The separately isolated H1-Fib checkout remains at
`f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35`, unchanged.

## Audited existing infrastructure

| Existing source | Verified behavior and reuse |
|---|---|
| `mt5/Experts/MonatiseFTMOBridge.mq5`, candle response around lines 1220–1277 | Resolves broker symbol, uses `CopyRates(symbol, frame, 0, limit, rates)` for H4/H1/M15/M5/M1; emits original integer `t_broker`, a current-offset `t` assertion, OHLC, tick volume, account/server/symbol, capture UTC, units and session information. Recent-window transport only: 50–240 bars; no arbitrary-date pagination. Existing history-only mode is not activated by Phase 3. |
| `monatise/application/hierarchy/broker_candles.py`, `BrokerCandleService.fetch/accept` | Authenticated recent-window demand/response, bridge version and freshness checks, account/server/symbol binding, ordered finite OHLCV. Gold history version 3 can normalize historical wall epochs through an explicit reviewed calendar. Fetching requires an active bridge; none was called. The accepted response does not preserve every original wire assertion, so original response capture is preferable for this archive. |
| `monatise/application/gold_sessions.py`, `GoldSessionCalendar` | Authoritative account/server identity, reviewed historical offset eras, sessions, closures, breaks, fixed-duration regular-bar boundaries and latest expected closed bar. Ambiguous repeated wall hours fail closed. A manifest is not automatically proof of an authentic broker calendar. Reused unchanged. |
| `monatise/application/hierarchy/candles.py`, `CandleBoundaryNormalizer` | Candle identities/content hashes, fixed timeframe boundaries, default 10-second grace and second-observation finalization. Reused unchanged with conservative capture-based observations. |
| `monatise/application/hierarchy/policy.py` | Existing shared five-timeframe hierarchy reused, no duplicated durations. |
| `monatise/application/persistence.py`, `PostgresDocumentStore` | Existing psycopg/asyncpg document API and create-only optimistic concurrency. Reused against a new research-only table matching the document contract. Existing production documents/streams are unchanged. |
| `monatise/application/gold_analysis.py`, `GoldPolicy/GoldLayerEvaluator` | Technical-first Gold requires broker candles; optional GC/options/basis do not manufacture missing evidence. H4 advisory, H1 authority, M15 setup/stop, M5 trigger, M1 refinement remain unchanged. |
| Isolated `monatise/research/gold_fib/replay.py`, `OfflineReplay` | Consumes local `gold-h1-fib-observation-archive-v1`; accepts only explicitly synthetic or PIT evidence and the canonical source commit. Retrospective downloads cannot satisfy its PIT contract. Read-only compatibility smoke used this existing runner; no selector files were copied or modified. |

No dedicated Exness acquisition adapter was found in the audited `monatise`,
`mt5`, README or documentation. The archive can validate an explicitly mapped
Exness-style `XAUUSDm` export using its own broker identity/calendar. This is
offline format support, not an implemented/authenticated Exness connection.

## Files added

No existing file was modified.

* `monatise/research/broker_xauusd/__init__.py`: archive/baseline version constants;
  no runtime registration.
* `monatise/research/broker_xauusd/models.py`: explicit broker identity/namespace,
  calendar-derived expected bars and bounded manual historical acquisition plans.
* `monatise/research/broker_xauusd/archive.py`: one-shot parsed-response import,
  validation, immutable batch storage, post-write admission receipts, integrity
  verification and cutoff-aware reads.
* `monatise/research/broker_xauusd/replay.py`: deterministic version/finalization
  preparation, gap reports, evidence-class separation and synthetic F0 export.
* `monatise/research/broker_xauusd/schema.sql`: opt-in research table, version=1
  constraint and database guards against UPDATE, DELETE and TRUNCATE.
* `tests/research/test_broker_xauusd_archive.py`: offline synthetic tests.
* `tests/research/test_broker_xauusd_postgres.py`: three tests using a private,
  temporary PostgreSQL cluster and restart/reopen verification.
* This implementation report and schema/usage specification.

## Implemented acquisition boundary

`historical_plan(identity, calendar, start, end, page_bars=240)` is a pure plan.
It covers all five native timeframes, pages at most 240 expected bars and bounds
each planning window to seven days. Its UTC ranges are half-open; expected grids
come from broker historical offsets and sessions. It does not connect, load
credentials, initiate CopyRates, download history, schedule collection or poll.

`BrokerObservationArchive.append(payload, evidence_kind=..., source_reference=...)`
accepts a local parsed MT5-style response plus a separately recorded `received_at`.
It retains original parsed fields, including `t_broker` and the provider's `t`
assertion, while normalizing UTC from the reviewed historical era. It does not
trust a current UTC offset for old rows. Native broker timeframe candles are
required; no resampling, interpolation, synthetic gap fill or GC substitution.
Partial/empty timeframe series can be archived truthfully; coverage then blocks
qualified replay rather than fabricating candles.

Historical candle calendars need not cover today's acquisition date. For an old
download outside that calendar's validity, supply a separate broker-reviewed
`capture_calendar_manifest` covering the actual capture date. Both calendars and
fingerprints are retained: row clocks use the historical calendar; the response
offset uses the capture calendar. Identity mismatch or absent current coverage
fails closed. This avoids extending/guessing old offset eras into the present.

Three immutable evidence classes exist:

* `ENGINEERING_SYNTHETIC`: artificial test material only.
* `RETROSPECTIVE_HISTORICAL_DOWNLOAD`: downloaded/exported history with real
  capture/receive/admission times. Historical event times are not availability.
* `POINT_IN_TIME_OBSERVATION`: an imported captured response requiring an external
  capture-proof reference. The archive explicitly records
  `capture_proof_verified_by_archive=false`. Phase 3 never authenticates or
  approves such a reference; independent Phase 4 review remains mandatory.

Real acquisition is not implemented as an automatically callable transport.
The existing FTMO transport could supply authorized recent captures later;
arbitrary historical terminal/export acquisition and Exness transport require
separate approval and broker-specific verification. A manual request plan does
not prove historical coverage or that any data was acquired.

## Durable schema and append-only guarantees

Explicitly apply `schema.sql` only to a separately selected research database.
It is not in `deploy/migrations`, is not auto-applied and cannot change existing
application tables. Construct `PostgresDocumentStore(connection,
table='monatise_research_broker_documents')`; the archive refuses the default
production table. No environment DSN or secret is read by the archive.

The table retains the existing document-store columns: `namespace`,
`document_key`, immutable JSONB `value`, `version=1`, `created_at`, `updated_at`.
The primary key is `(namespace, document_key)`. Ordinary database UPDATE, DELETE
and TRUNCATE are rejected by triggers, including for the table owner in the tests.
Create-only CAS is the sole application write mode. No replace/delete methods
are exposed by the archive.

This is application/database append-only storage, not external WORM storage:
a privileged administrator can disable triggers/drop tables or alter backups.
SHA-256 detects accidental content changes; it is not a cryptographic signature
from the broker, an independent custody witness or a guarantee against an
administrator rewriting every hash. Independent backups/retention/capture proof
must be reviewed before real-market research custody is claimed.

Namespace:
`BROKER:XAUUSD:<hash of complete broker identity>:<calendar fingerprint>`.
Different accounts, servers, brokers, symbol mappings or calendar versions cannot
silently mix. Databento namespaces, SDK and GC data are not imported by this code.
Calendar upgrades produce separate archive namespaces; cross-calendar stitching
requires an explicit later review.

Batch document key: `batch:<batch_id>` where batch identity binds the namespace
and original request ID. The batch body contains:

| Field | Meaning |
|---|---|
| `schema`, `baseline`, `batch_id`, `namespace` | Versioned archive and source baseline identity. |
| `broker_identity` | Broker, opaque account reference, server, executable broker symbol and canonical `XAU/USD`. Never a GC contract. |
| `calendar`, `calendar_fingerprint` | Frozen reviewed schedule/source/version and offset eras. |
| `capture_calendar`, `capture_calendar_fingerprint` | Separate reviewed capture-date coverage for old retrospective downloads, or the same reviewed calendar for contemporary captures. |
| `raw_payload`, `raw_sha256` | Original parsed response and canonical JSON hash. Not a claim to retain exact HTTP wire whitespace/decimal lexical spelling. |
| `evidence_kind`, `source_reference`, `capture_proof_reference` | Explicit provenance; proof reference does not itself certify authenticity. |
| `window` | Optional requested historical interval, with returned rows required inside it. |
| `rows[].original` | Original broker candle row, integer wall epoch, provider timestamp assertion and OHLCV. |
| `rows[].opened_at`, `scheduled_close_at` | UTC boundaries normalized using the historical broker era. |
| `rows[].candle`, `content_hash`, `value_sha256` | Canonical candle values, unchanged normalizer hash, and exact serialized value hash. |
| `rows[].clock_closed_at_capture`, `is_final=false` | A close-clock diagnostic; ingestion alone does not finalize a candle. |
| `body_sha256`, `volume_kind`, `execution_enabled=false` | Content integrity, truthful tick volume and isolation. |

Admission document key: `admission:<batch_id>`. Contains receipt schema, batch
identity/body hash, `ingested_and_available_at`, and receipt hash. Admission time
is sampled only **after** the durable batch write completes. A failed admission
leaves an immutable orphan that readers exclude. An explicit idempotent re-import
can append its first receipt at the later actual admission time; it cannot
retroactively make the batch available. Original capture and receive timestamps
remain separate; clock ordering must be capture ≤ receive ≤ import/admission.

Identical request replay is idempotent. Changed content or evidence metadata
under the same request identity is rejected. A new broker observation/revision
requires a distinct request identity and becomes a new immutable batch.

## Replay, revisions and look-ahead prevention

`prepare_replay(archive, cutoff, start, end, evidence_kind)` reads admitted batches
whose durable availability is at/before cutoff and selects exactly one evidence
class. Retrospective observations never provide PIT warmup or silently become
synthetic material. The reviewed coverage window is bounded to seven days.

For each broker/timeframe/open boundary:

1. Preserve every archived version; use increasing captures in availability order.
2. Reject same-capture duplicates and older out-of-order captures as confirmation.
3. Count a closed observation only if captured at/after close + canonical grace.
   A forming row delivered late is not converted into a closed observation.
4. Require two distinct increasing captures of identical values before deriving
   finalization. Record the actual first finalized availability time.
5. Any exact OHLCV revision revokes finalization until a new matching closed
   capture arrives. Earlier cutoff results remain unchanged.
6. If exact values revise while the existing 12-significant-digit normalizer hash
   stays equal, report `NORMALIZER_HASH_COLLISION` and block export. The canonical
   normalizer is not altered.
7. Report missing expected bars and unfinalized bars for each timeframe, and
   require the actual latest session-expected bar to be finalized.

Replay preparation includes per-version batch/hash/capture/availability,
confirmation count, revision status, first-finalized timestamp, coverage,
rejections and a deterministic artifact hash. No engine/selector is invoked by
preparation. Same-time admissions are flagged rather than inventing their order.
The unchanged offline F0 runner requires strictly increasing observation times.

The minimum-history precheck reuses the current Regime slow-window and Liquidity
range-window defaults (50) rather than inventing a strategy threshold. Counts
below that minimum block F0 input export. Default coordinator history remains
200 and is separately reported as complete/incomplete. Coverage is for the
declared window, not a certification of every older retained historical interval;
Phase 4 must review full warmup coverage and the desired replay period.

`f0_input()` emits the existing F0 schema for **synthetic engineering material
only**, after integrity and preparation checks. It preserves actual admission
times, broker identity, calendar, units and input hashes. Phase 3 rejects real
market export and historical-as-PIT export. The H1-Fib selector's active-episode,
first confirmed endpoint, anchor, geometry, age, ATR, expiry and target rules are
not touched. `f0_input_ready` means offline input preconditions, not an eligible
trade; `phase4_ready` remains false throughout this isolated milestone.

## Tests and engineering results

New tests cover all five timeframes, finite geometry/units/volume, missing bars,
duplicates, immutable identity conflicts, original clocks, historical offset
eras, ambiguous DST hours, broker grids, holidays/weekends/breaks, forming captures
delivered late, two closed captures, revisions, earlier-cutoff invariance, late
ingestion, orphan admission, out-of-order captures, integrity tampering, exact
hash collisions, ambiguous availability, provenance aliasing, historical/PIT
separation, GC rejection, request bounds and no live dependency/route registration.

Actual isolated PostgreSQL tests prove concurrent duplicate import, restart
round-trip equality, update/delete/truncate rejection, default-store overwrite
rejection, historical evidence separation, and continued ordinary mutability of
the existing application table. Temporary cluster uses a private Unix socket,
no production DSN, and is stopped/deleted afterwards. The existing local PG
fixture is reused from Phase 2; no market data or Databento request is involved.

Final checks: 48 new cases (45 offline synthetic + 3 actual temporary PostgreSQL).
Final full suite: **1,911 passed, 14 pre-existing integration skips, zero failures**
in 31.39 seconds. Results are also recorded in the accompanying Phase 3 artifact.
The 14 pre-existing integration skips require unconfigured DB/Redis test URLs;
the three new archive PG tests run against their own temporary cluster.
No dependencies were installed or changed. During development, real PG testing
found SQL_ASCII text keys returned as bytes; the isolated archive now decodes
keys explicitly without modifying the shared production adapter.

Engineering compatibility smoke artifacts are under
`outputs/monatise-broker-xauusd-phase3/final-engineering` (outside the repository):
two synthetic captures, 480 unique candles / 960 version events;
finalized H4/H1/M15/M5=60 each and M1=240; no declared-window gaps;
deterministic preparation hash
`0e1f62d391ba417bf41faa3d786fb277f5603c51d2048e72a329544bd652567f`.
The unchanged isolated F0 CLI consumes this artifact successfully and reports
zero qualified seeds for flat synthetic prices. First observation correctly
lacks closed snapshots; second runs the canonical evaluation but creates no
seed. This verifies input compatibility, not selector performance, historical
availability, reachability or profitability. An earlier short-history smoke
truthfully rejected insufficient candles; the final exporter precheck now blocks
that case before export. Earlier artifact directories remain intact.

## Limitations and Phase 4 readiness

Engineering readiness: archive, database protections, evidence separation and
offline preparation are implemented and tested. **Real-market readiness: blocked.**
No authentic broker candles have been acquired in this phase. No claims about
historical Gold seed availability or H1 extension reachability can be made.

Necessary later work/approval:

* Explicit authorization for a named broker/account read-only connection or
  operator-produced export, instrument mapping and bounded date/timeframe scope.
* Broker-reviewed historical offsets, sessions, breaks, holidays and manifest
  validity. An exchange calendar or the current offset alone is insufficient.
* Authentic capture evidence and original receive clocks. Local admission time
  cannot recreate pre-existing unknown historical availability.
* Verify terminal history limits, partial-history behavior and native candle
  conventions. Preserve partial session bars for investigation if encountered;
  they cannot enter this canonical regular-bar archive without separate design.
* An explicit reviewed method for retrospective reconstruction if original PIT
  observations do not exist. The current isolated runner intentionally rejects
  retrospective datasets. Do not relabel them or change its rules silently.
* Full warmup coverage plus enough causal observation history before H1 parent
  capture and lower-timeframe eligibility. Seeing old candles today does not
  make an old pivot historically available.
* The isolated runner currently labels provider provenance `ftmo_mt5_archive`.
  Before genuine Exness replay, review this provenance compatibility explicitly;
  Phase 3 keeps actual broker identity separately and does not claim an Exness
  connection or rewrite the selector.
* JSONB batch documents reuse existing infrastructure and avoid a new service.
  Reads currently scan the selected namespace; no benchmark establishes capacity
  for indefinite high-frequency collection. Retention, indexing/partitioning,
  backups, clock trust and storage growth need measurement before large archives
  or continuous collection. No QuestDB/Grafana/new subscription is introduced.

Phase 3 has no production integration, deployment, continuous polling, Telegram
publication, approval binding, pending-order path or execution path. GIL and
Databento GC remain entirely separate; no options evidence is required or invented.
Stop here. Phase 4 real-market H1-Fib validation and any broker access require
separate explicit user authorization.
