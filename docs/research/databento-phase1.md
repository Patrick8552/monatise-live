# Databento Phase 1: isolated compatibility foundations

## Scope and implementation plan

Verified upstream main on 2026-10-11:
`0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`. GitHub main had no changes
since the supplied audit baseline. The untouched local H1-Fib checkout is
`f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35`; it is not on main.

The implementation plan presented before edits was:

1. Create an isolated branch from verified main.
2. Add an explicit identity policy separating dataset, feed publisher/venue and
   economic exchange; retain every existing caller's default behavior.
3. Reuse GC/OG normalizers in a bounded point-in-time research registry retaining
   native definition bytes, nanoseconds, local availability and contract identity.
4. Test pinned SDK schemas, authentic saved metadata, rejection/lifecycle cases,
   namespace separation and isolation; run existing compatibility tests.
5. Commit locally, report certification limits, and stop before Phase 2.

Databento is the primary exchange-market-data source in this proposed research
architecture. No FlashAlpha dependency is introduced into these components.
Existing production integrations, including legacy providers, are unchanged.

## Existing boundaries verified

- `pyproject.toml` retains optional `gold-data = ["databento==0.87.0"]`.
- `adapters/databento_gold.py` already normalizes GC definitions, maintains bounded
  replay and supports explicit bounded streaming; constructors open no connection.
- `application/gold_options.py` already validates standard OG conventions and the
  option's exact underlying. American Greeks/dealer gamma remain uncertified.
- `application/gold_basis.py` maps contract-specific GC levels contextually, with
  uncertainty, and is not execution-price authority.
- `application/deployment.py::_gold_coordinator` does not inject GC/options/basis
  providers. `GoldPolicy` defaults to broker-candle technical sources.
- Gold hierarchy and FTMO proposal guards retain the separate-release prohibition
  on these Gold publication/approval/execution routes.
- Existing PostgreSQL document/stream stores and Redis coordination are suitable
  control-plane seams. Neither new raw-data persistence nor a database migration
  is implemented in Phase 1.
- The H1-Fib research runner is target-independent, offline and GIL-disabled;
  its current engineering fixtures are not authentic market-performance evidence.

## Opt-in compatibility contract

`DatabentoPublisherPolicy.from_metadata` consumes a bounded, immutable publisher
catalog with observation time and source hash. Its hash records provenance; it is
not a cryptographic assertion that a caller-supplied catalog is authentic.

The policy requires a record's publisher to resolve exactly to
`GLBX.MDP3/GLBX`. Separately, its definition must identify `exchange="XCEC"`.
It rejects unknown publishers, contradictory mapping, future catalog availability,
invalid native timestamps, unsupported contract classes and inconsistent GC
symbol/maturity fields. Standard OG requires asset OG and security type OOF.
Existing normalizer checks still enforce outrights, currency, scale, GC units and
ticks, option strike currency, conventions and underlying/expiry relationships.

The optional `identity_policy=None` default retains the previous publisher policy.
The normalizers and `GCReplay` have no new environment activation or runtime
registration. `cutoff_ns` is optional and only valid with the explicit policy;
it must match the supplied datetime presentation clock to microsecond resolution.
The precise integer cutoff determines research availability, not datetime rounding.

The research GC snapshot uses `COMEX:GC:<raw_contract>` and identifies its XAUUSD
context relationship separately. It explicitly has no execution-price authority.
`broker_xauusd_namespace` constructs `BROKER:XAUUSD:<opaque_broker_id>`; no actual
broker/account credentials are stored. Existing default snapshot behavior remains
unchanged. The research snapshot is intentionally not accepted as an XAUUSD
provider result by the current Gold coordinator without a later approved adapter.

## Registry and provenance

`research/databento/registry.py::GoldInstrumentRegistry` is opt-in and in-memory,
bounded by definition revisions. It is not an acquisition, archive, stream,
database, order-book or execution service.

Each immutable observation retains:

- Exact native DBN definition bytes and their SHA-256; header/attribute consistency.
- Exchange `event_ns`, provider `receive_ns`, local `ingestion_ns`, optional
  historical retrieval time, and local observation availability, separately.
- Dataset/schema, publisher/instrument identifiers, explicit source ordinal,
  metadata policy hash, source evidence classification and exact expiry nanos.
- Canonical GC/OG values and contract namespace; the option's underlying record hash.
- Add/modify/delete/quarantined status. Definitions have no sequence/flags supplied
  by this schema, so those provenance fields remain explicitly unavailable.

Native integer nanoseconds and raw bytes are authoritative. The existing canonical
datetime fields are compatibility presentations. Missing required definition
timestamps reject identity admission rather than being invented.

Local observations must have increasing `(ingestion_ns, source_ordinal)` ordering.
Timestamp queries include all observed ordinals at that time by default; callers
can constrain `through_ordinal` for exact same-nanosecond replay cutoffs. Original
availability is not renewed on duplicate bytes. Historical records retrieved today
are not backdated to their provider event/receive times.

Rejected updates quarantine a known instrument while retaining earlier historical
states. A subsequent fully valid definition can recover identity; bad rejected
timestamps do not advance the valid event watermark. Deletion, expiry, identifier
remapping and underlying changes fail closed. Refreshed underlying records require
fresh dependent option evidence. Capacity overflow loses current registry coverage
at the first overflow cutoff and cannot silently recover or move that cutoff.

`ACTIVE` means admitted contract identity, not certified options analytics, complete
feed coverage, a qualified Gold setup or permission to trade.

## Evidence and certification boundary

`tests/fixtures/databento/glbx_metadata_2026-10-11.json` is a sanitized subset of
the authenticated metadata-only preflight. It preserves the original report hash,
publisher ID 1 / GLBX.MDP3 / GLBX, and the resolved 41271 -> GCZ6 date mapping.
It contains no market definition records or credentials.

Regression records are constructed with actual `databento-dbn==0.70.0` SDK
`InstrumentDefMsg`, `TradeMsg` and `MBP1Msg` schemas under `databento==0.87.0`.
Native definition encode/decode roundtrip is tested. Their prices, expiry dates
and market observations are synthetic; they are not acquired GC records.

Actual GC and OG definitions remain an external compatibility gate. No billable
request, data purchase, free-credit consumption, live connection or certification
was performed. Public schema documentation establishes field semantics but does
not prove the values of a particular GC/OG market definition.

Reference documentation:

- https://databento.com/docs/schemas-and-data-formats/instrument-definitions
- https://databento.com/docs/venues-and-datasets/glbx-mdp3

## Testing and next phase

Use the isolated checkout's Python 3.12 environment with the existing project
extras; no dependency pin or production environment was changed:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,gold-data]'
env PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -q --tb=short
```

Focused tests:

```sh
.venv/bin/python -m pytest -q --tb=short \
  tests/research/test_databento_foundations.py \
  tests/test_databento_gold.py tests/test_gold_options.py
```

The full-suite PATH prefix is necessary for the packaged CLI smoke test.
PostgreSQL/Redis integrations skip without isolated test-service URLs. Never point
those test variables at production. SDK schema tests explicitly skip if the optional
gold-data dependency is absent; the acceptance run used the installed pinned SDK.

Phase 1 acceptance results on Python 3.12.14:

- Final full suite: 1,794 passed, 14 skipped, zero failed (30.29 seconds).
- 52 new foundation cases are included in that full-suite result. Synthetic native
  definition/trade/MBP-1 schemas, DBN roundtrip and real metadata fixture are covered.
- Untouched isolated H1-Fib checkout: 53 passed, zero skipped/failed (45.06 seconds),
  using the new checkout's interpreter with the research checkout as working directory.
- An earlier full run failed its CLI smoke test because `.venv/bin` was absent from
  PATH. Correcting the command fixed that environment-only failure without changing
  CLI code. SDK quote fixture construction was corrected to the pinned constructor's
  single BidAskPair argument; its exposed `levels` remains a list for the adapter.
- The 14 full-suite skips comprise seven application persistence integrations,
  one live-user database integration, one multi-TP database integration and five
  TradingView webhook database integrations. No service-backed check is claimed
  passed. No deployment, live feed or actual market-record test was run.

No shared runtime wiring, SDK pin, strategy, risk, approval or execution file was
changed. Shared normalizer changes are explicit optional arguments with unchanged
defaults. The existing suites cover default GC/OG, Gold, crypto/index, approval and
governance behavior. The F0 policy/package and its source checkout remain untouched.

No replay throughput/memory benchmark was performed: Phase 1's bounded definition
registry is not the Phase 2 tick replay pipeline. Raw archive durability, PostgreSQL
registry persistence, sustained ingestion/recovery, reviewed roll policy and real
definition certification remain explicit gaps. No recurring infrastructure cost
was introduced and no market-data credit or money was consumed.

Phase 2 requires separate authorization. Its scope is acquisition/archive,
PostgreSQL metadata persistence and deterministic DBN replay. No download budget,
entitlement, recurring cost or production deployment is authorized by this phase.
Existing estimated five-schema GC acquisition smoke-test cost is approximately
$1.97; a newly scoped request needs a fresh estimate and explicit spending approval.
Authentic XAUUSD observation archives, live recovery and certified options/GIL
remain later work. No H1 selector policy, Gold strategy, risk limit, approval,
pending-order or execution contract was changed.
