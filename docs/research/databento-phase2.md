# Databento Phase 2 — isolated historical acquisition and replay

## Status and boundary

Phase 2's engineering implementation is local and opt-in. It is not deployed,
connected to production, or certified against acquired GC/OG market records.
No market-data download, credit consumption, subscription, live feed, trading,
Telegram, approval binding, pending order or execution action occurred.

The user authorized Phase 2 after the Phase 1 report. The implementation plan
presented before edits was guarded historical acquisition, immutable native DBN,
existing PostgreSQL metadata, and bounded deterministic replay. Billable requests
remain separately gated on exact scope and explicit human approval.

GitHub main was rechecked at the start and end of implementation and remained
`0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`. This branch builds on the local Phase 1
commit `6c05d6bd5f202be16ed0fe39729201055b7547fb`. The separate H1-Fib checkout remains
clean at `f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35`; it was not merged or changed.

## Reuse, modification and new components

| Component | Status | Responsibility |
| --- | --- | --- |
| `adapters/databento_gold.py::GCReplay`, `definition`, `price`, `ns_time` | Reused, unchanged this phase | Base quarantine mechanism, GC units/tick/scale/contract rules; datetime bridge is presentation only |
| `adapters/databento_identity.py::DatabentoPublisherPolicy` | Modified | Extract economic identity checks for retrospective reference reconstruction; normal `validate()` retains catalog/cutoff/expiry gates |
| `application/persistence.py::PostgresDocumentStore` | Reused unchanged | Existing JSONB document table and compare-and-swap versions for metadata |
| `deploy/migrations/001_application_orchestration.sql` | Reused unchanged | Existing composite primary key; no new database or migration |
| `research/databento/acquisition.py` | New | Explicit request/preflight/approval interfaces, bounded SDK transport, one-use receipt, reservation, manifests, recovery and reviewed retry |
| `research/databento/archive.py` | New | Native DBN preservation, SHA-256, fsync/no-overwrite publication, quarantine, streaming native-version decoder |
| `research/databento/replay.py` | New | `HistoricalGCReplay(GCReplay)`, typed normalization, incremental aggregates, coverage assertions, prefix-verifying restart |
| `research/databento/benchmark.py` | New | Offline synthetic DBN throughput, traced allocation and process-RSS measurement |
| `tests/research/test_databento_history.py` | New | Offline engineering fixtures and failure/causality/isolation tests |
| `tests/research/test_databento_history_postgres.py` | New | Actual temporary PostgreSQL tests without any production DSN |

No production imports the research package. The original GCReplay methods,
existing adapter, Gold source policy, legacy providers, SDK pin, strategy,
Fibonacci policy, risk limits and execution/approval contracts are unchanged.

## Acquisition contract

`HistoricalRequest` requires GLBX.MDP3, one reviewed schema, an immutable list of
at most eight exact `(publisher_id, instrument_id, raw_contract)` identities,
integer-nanosecond start/end and a window of at most seven days. Parent/continuous
symbols, ALL_SYMBOLS, MBO/depth schemas and ambiguous selections are rejected.
Limits are at most 1,000,000 records and 256 MiB of compressed wire bytes.

`SDKHistoricalSource.preflight()` reuses the pinned SDK's free metadata methods:
schema-specific availability, publisher metadata, raw-symbol mappings across the
whole requested date range, and `get_cost` using the exact bounded request.
Metadata/API authentication does not establish market-data entitlement; preflight
returns `UNKNOWN` until separately reviewed licensing evidence is supplied.

`ApprovedDownload` binds the request hash and the complete preflight hash to an
opaque human review reference, a five-minute-or-shorter validity interval, an
estimated-USD limit and verified entitlement reference. Credit-only mode requires
a recent balance reference, sufficient balance and an unexpired credit record.
No implementation code constructs approvals automatically.

These interfaces are **trusted operator assertion boundaries**. A Python receipt
does not authenticate a human, query a credit balance, or activate a license.
The caller must verify those records; current production approval systems are
not connected to this research interface.

Databento cost estimates are not hard charge caps. Billing is based on delivered
uncompressed data, not local compressed file size. A stream can incur usage before
an error or local cap is reached. The explicit receipt acknowledges this limitation;
external account budgets/billing controls and final usage reconciliation remain
operator responsibilities. A successful request leaves actual cost `UNKNOWN`.

The SDK's normal downloader lacks a wire-size cap and leaves its writer open on
some failures. The opt-in subclass replaces only its streaming transport, keeping
SDK parameter validation: official endpoint, no redirects/retries, request timeouts,
wire-byte cap, duration guard and closed writers. Errors exposed by this wrapper
do not include credentials or raw provider exceptions.
The low-level billable download method revalidates the exact approval immediately
before transport, including worker-queue delay; a direct unapproved call is rejected.

PostgreSQL CAS reserves a globally one-use approval receipt and the exact request
before any network action. A duplicate completed request returns the verified
archive; pending/failed requests cannot silently redownload. Failure retains a
hashed, read-only partial file and a quarantined manifest with unknown billing.

Local reconciliation can recover a known sealed orphan after database failure,
only with explicit confirmation of completed transport. An uncertain staged file
is quarantined. Original retrieval time remains unavailable after recovery rather
than being reconstructed. Explicit retries need a new approval, new preflight,
final prior-usage review, confirmation the prior process stopped, an expired old
attempt and settlement interval. Prior manifest revisions/files are preserved;
attempt count is bounded at three. There is no automatic paid retry.

## Native archive and provenance

The archive root is operator-selected durable storage. Native DBN/ZSTD bytes are
never rewritten. Staged files are fsynced, hashed, made read-only and published
through same-filesystem hard links that cannot replace existing objects. Archive
and staging directories are fsynced. Every read/replay verifies the file hash.
This is application-level immutability, not hardware WORM or backup configuration;
an owner/administrator can alter files, but later integrity verification rejects it.

The decoder preserves native DBN versions (`AS_IS`), streams bounded chunks,
limits decoded bytes/records, and rejects truncated records or compressed frames.
Archive admission verifies dataset/schema/rtype, exact selected identities,
requested boundaries, native ordering, symbols and partial/not-found metadata.
Reaching the record cap is conservatively partial even if the file itself decodes.
Native V1/V2 archives remain preserved; unsupported old normalization schemas fail
closed rather than being silently upgraded and hashed as if they were original.

Records retain original integer event/receive clocks, local bulk-admission time,
historical retrieval time, local availability, source ordinal, native sequence,
flags/update action, dataset/schema/namespace, raw-record hash and typed payload.
Missing receive clocks on OHLCV and unavailable reference/status fields stay null.
Statistics enum values remain their native integers. DBN raw bytes remain the
authoritative source for fields outside the normalized payload.

Historical retrieval is the completed-download observation. Bulk ingestion and
availability occur after integrity admission. They may differ. Historical receive
time does not become Monatise's first-observed time. Recovered archives use current
admission availability and explicitly missing retrieval time.

Expired GC definitions can support retrospective reference reconstruction using
the existing GC economic checks and exact lifetime. Catalog observation/retrieval
times remain current; the reference is labelled `RETROSPECTIVE_REFERENCE_RECONSTRUCTION`.
This does not weaken the point-in-time registry or claim old local availability.

## Replay and coverage semantics

Replay is one explicit contract, request and reviewed session window. No automatic
roll, cross-contract aggregation or multi-file schema merge is performed. Original
provider receive order (event order when receive is absent), then native file ordinal,
is preserved; arbitrary sorting does not manufacture a causal order.

Trade-only integer sums produce volume, VWAP, POC/profile and known-side CVD.
Databento B is buy aggressor, A sell aggressor; unknown-side volume is separate.
MBP-1 supplies top-of-book only and never adds traded volume, even on trade actions.
Native OHLCV/statistics/status remain separate typed evidence. OI is not signed
dealer inventory. Definition changes, unsupported corrections, bad receive flags,
invalid quotes/prices, ordering failures and bounded-state overflow quarantine
derived evidence. No speculative trade-bust/statistics-delete repair is attempted.

Recent dedup hashes and distinct price buckets are bounded. An old duplicate outside
the dedup cache arrives out of order and is rejected/quarantined without adding
volume. Filtered CME packet sequences are not assumed contiguous. Missing sequence
numbers alone do not prove gaps. Transport/exchange gaps need independent reviewed
diagnostics; those are not currently supplied automatically by this historical API.

Coverage states are distinct:

- `PARTIAL`: replay not finished, incomplete transport, or record-limit truncation.
- `GAPPED`: a normalization, ordering, correction, capacity or reviewed gap failure.
- `UNCERTIFIED`: transport complete but independent continuity evidence absent or mismatched.
- `STALE`: reviewed full coverage is outside the assessment freshness window.
- `COMPLETE`: reviewed coverage boundaries/count/hash match and no known quality gap exists.

`CoverageAttestation` is another trusted reviewed-source boundary, not automatic
certification. A request EOF/file hash/last recent tick is insufficient. The
completion watermark describes request transport, not independently proven exchange
continuity. Historical aggregates can be inspected while quarantined, with
`aggregates_usable=false`. Every result remains `trading_eligible=false` and has
no execution-price authority, including synthetic or reviewed COMPLETE results.

Checkpoint metadata binds archive/config/definition/catalog hashes, integer record
ordinal, rolling observation hash and state hash. Restart rebuilds/verifies the
prefix with bounded state before continuing; it costs O(prefix) reads but cannot
count records twice. Checkpoint persistence uses existing PostgreSQL CAS. Source
evidence and local clocks are frozen, so repeat/restart outputs are deterministic.

## Evidence, tests, costs and remaining gates

New fixtures use actual pinned SDK record schemas with synthetic market values.
They are classified `ENGINEERING_SYNTHETIC`, including generated native archives.
The saved authenticated Phase 1 metadata is real provider metadata; it contains no
actual market definitions, trade records or verified account credit balance.
All Phase 2 SDK transport/metadata tests are offline mocked requests.
A separate read-only Safari check verified the account's remaining signup credit
and displayed expiry. That is balance evidence, not an entitlement certification,
download authorization or acquired market dataset; private payment/account details
are not retained in this repository.

No source is newly certified and no market-performance conclusion is supported.
Current authentic-data compatibility remains gated on separately approved GC/OG
definition and market-record acquisition. The earlier five-schema October 5–10
GC quote was about USD 1.97; it is not a fresh Phase 2 approval or a hard charge cap.
This phase consumed USD 0 / zero credits and added no recurring infrastructure.
Future costs comprise approved Databento usage, operator-selected disk/backups and
existing PostgreSQL storage; QuestDB/Grafana/Redis dependencies are not added.

Acceptance commands:

```sh
.venv/bin/python -m pytest -q --tb=short \
  tests/research/test_databento_history.py \
  tests/research/test_databento_history_postgres.py \
  tests/research/test_databento_foundations.py tests/test_databento_gold.py
env PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -q --tb=short
.venv/bin/python -m monatise.research.databento.benchmark --records 100000
.venv/bin/python -m monatise.research.databento.benchmark --records 250000
```

The PostgreSQL tests create an ephemeral cluster using already-installed binaries,
with only a private Unix socket. They read no production DSN and stop/remove the
cluster. They skip if those local binaries/dependencies are unavailable. Synthetic
benchmarks include archive hash verification, admission validation and replay with
tracemalloc enabled; process peak RSS also includes Python/SDK imports and fixture
generation. They do not establish production latency or all-schema workloads.

Final acceptance on Python 3.12.14 and the unchanged Databento 0.87.0 pin:

- Full suite: **1,863 passed, 14 skipped, zero failed** (32.05 seconds).
- **69 new cases**: 66 offline engineering cases and three real temporary-PostgreSQL
  cases, included in the full-suite result. Optional-SDK cases were not skipped.
- The 14 skips are existing integrations lacking configured test-service URLs:
  seven application persistence, one live-user database, one multi-TP database,
  and five TradingView webhook integrations. Their compatibility is not claimed
  service-tested by this run.
- Native definition/trade/MBP-1/OHLCV/statistics/status schemas, truncated DBN/ZSTD,
  record/byte bounds, required receive timestamps, precise/local clocks, approval
  and credit gates, concurrent CAS, paid-retry quarantine, reviewed retry, orphan
  recovery, deterministic checkpoint replay, coverage states and isolation pass.
- Initial tests found JSON tuple/list round-trip and native statistics enum
  mismatches; both were corrected and covered before the final passing run.
- No H1-Fib selector or production runtime file changed. Its independent checkout
  remains clean; its Phase 1 test result was not rerun or represented as a new
  real-market pilot in Phase 2.

Final synthetic benchmark (no other test suite running; local host not reserved):

| Records | Time | Records/sec | Traced Python peak | Total process peak RSS |
| --- | --- | --- | --- | --- |
| 100,000 | 6.789 s | 14,730.5 | 965,518 bytes | 38,256,640 bytes |
| 250,000 | 16.948 s | 14,750.7 | 965,518 bytes | 38,387,712 bytes |

Both retained 1,024 dedup entries and 128 price buckets, with UNCERTIFIED coverage.
The native files were 4,800,200 and 12,000,200 bytes. This demonstrates bounded
state for this synthetic workload, not completeness or market performance.

Still requiring later work: persistent broker XAUUSD observations (Phase 3), genuine
canonical-vs-H1-Fib validation (Phase 4), sustained live ownership/backfill/recovery,
automatic transport continuity evidence and roll orchestration (Phase 5), reviewed
GC options/GIL certification (Phase 6), and separately scoped MBO/depth processing.
Native GC OHLCV is not a broker candle archive or a finalized Gold source contract.
No GC candle/price substitutes for XAUUSD and no options evidence is invented.

Stop after this engineering milestone. Phase 3 requires separate authorization;
approved market-data acquisition also requires an exact fresh request, account
entitlement/credit verification and explicit usage approval.

Primary documentation reviewed:

- https://databento.com/docs/api-reference-historical/timeseries/timeseries-get-range
- https://databento.com/docs/standards-and-conventions/common-fields-enums-types
- https://databento.com/docs/faqs/usage-pricing-and-data-credits
