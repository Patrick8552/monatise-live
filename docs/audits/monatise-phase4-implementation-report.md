# Phase 4 implementation and acceptance

Implemented safely achievable isolated interfaces on the verified Phase 3B baseline.
The authentic GC example processes **1,014 native trades, 15 native OHLCV minutes,
one definition and one captured MBP-1 snapshot** in October 5, 2026 15:00–15:15 UTC.
Two runs produce identical bytes. **2,060 tests pass**, including 43 new Phase 4 cases.
New provider usage, credit consumption and cash expenditure are **$0**.

This is local research acceptance, not production or live-market certification.
There are no authentic qualified broker signals in the available evidence. A controlled
Gold fixture produces a canonical LONG preview and a separate regression verifies
SHORT; these are engineering outcomes, not authentic trades, returns or win rates.

## Delivered architecture and files

The [audit](monatise-phase4-integration-audit.md) records baseline identities,
interfaces, runtime wiring, dependencies, tests and the compatibility matrix.
The [architecture](../monatise-multiasset-institutional-data-architecture.md) records
units, formula/source contracts, asset routing, mapping, options and governance.
The [machine acceptance](monatise-phase4-validation.json) binds source, input, runtime,
native definition, manifest and repeated output hashes plus test and isolation results.
[Preview examples](../monatise-phase4-signal-preview-examples.md) distinguish authentic
missing-data results from engineering scenarios.

All source changes are **new files**, under `monatise/research/institutional/`:

| Files | Implemented behavior / reuse |
|---|---|
| `models.py`, `__init__.py` | Immutable exact contracts, native source positions/clocks, observation envelopes and complete typed non-executable SignalPreview |
| `normalize.py` | Reviewed economic terms; wraps existing dataset discovery, AdvancedAdapters, candle normalization and published OI normalization; optional schemas disabled unless explicit |
| `indicators.py` | Bounded executed VWAP, exact-tick profile/POC, known-side delta/CVD, visible book metrics, unannualized minute volatility, published OI changes; native ordinal dedup and coverage limitations |
| `mapping.py` | General economic relationships and explicit policies around unchanged GoldBasisService; synchronized quotes, expiry/session/currency/unit/roll checks, observed uncertainty and context-only estimates |
| `options.py` | Standard OG exact underlying/quote/OI/rate join around existing American futures CRR/IV; European unsigned gamma research primitive with no dealer sign or flip |
| `signals.py` | Offline broker transport to unchanged GoldAnalysisCoordinator/GoldHierarchyAnalysis and index AssetHierarchyAnalysis; existing FlashAlpha input boundary; unchanged crypto production stage-input builder and analytical engine registrations |
| `fixtures.py` | Explicit ENGINEERING_SYNTHETIC data and provider scenarios; reuses the prior controlled geometry builder |
| `native.py` | Existing-source manifest/archive/request verification; narrow native GCZ6 validator and bounded 15-minute processing; no acquisition |
| `isolation.py`, `bootstrap.py` | Python -I/allowlisted environment, guarded reads/writes, denied network/process/secret access and execution/publisher imports; existing base guard reused |
| `worker.py`, `runner.py` | Credential-free deterministic examples, source/runtime-bound input, two isolated runs, immutable normalized/indicator/replay/quality layers, quarantine on failure; disabled acquisition proposals |

Added `tests/research/test_institutional.py` and the five requested documentation
artifacts. No existing source, deployment configuration, registered engine, production
route, risk rule, FTMO/MT5/Telegram operation or frozen selector is modified.

## Dataset/schema and asset results

| Source/schema | Support in Phase 4 | Authentic acceptance |
|---|---|---|
| GLBX.MDP3 definition | Existing observed dataset registry/discovery; explicit currency/tick/multiplier convention, exact contract, raw definition/source hashes | GCZ6, publisher 1 / instrument 41271 / XCEC; reviewed native TRYOZ economics |
| GLBX.MDP3 trades | Executed fixed-point prices, quantities, published aggressor or unknown, native event/receive/admission/retrieval clocks | 1,014 scoped GC observations; captured VWAP/profile/POC and side coverage |
| GLBX.MDP3 OHLCV-1m/1h | Existing native candle normalization; null receive timestamp where absent; no display-factor rescaling or gap filling | 15 contiguous native GC minutes; minute log-return sample volatility |
| GLBX.MDP3 MBP-1 | Existing quote normalizer/visible book metrics with outer identity/flags/source quality | One last observed two-sided GC snapshot; spread/visible imbalance/concentration |
| GLBX.MDP3 status/statistics | Native status envelope; published OI reference/publication/admission, flags and update action retained | Prior authentic status/session lineage reused; OI/statistics fixtures only |
| MBP-10 / MBO | Existing advanced interfaces retained; no Phase 4 depth/MBO acquisition or activation | No new depth data; MBO remains explicitly disabled |
| ES / NQ futures | Normalization and contract handling tested with native-shaped fixtures; no guessed IDs accepted as real | **UNAVAILABLE**: no accepted exact native definitions or observations |
| OG options | Reviewed standard OG definitions and input/model interface | **UNAVAILABLE**: no authentic chain/quotes/OI/rates in accepted archives |
| ES / NQ options | Explicit model convention/unsigned European primitive; native index-option registry remains unreviewed | **UNAVAILABLE**; no raw symbol family, exercise style or chain guessed |
| CL/YM/RTY/CME BTC/ETH | Disabled architecture descriptors; CL has prior generic discovery support | Not acquired/activated |
| BTC/ETH/SOL native crypto | Existing canonical production request/engine compatibility; no Gold routing or CME replacement | Fixtures only; genuine authorized exchange/CoinGlass export absent |
| Other datasets | Existing extension placeholders retained | No unrelated feed implemented or enabled |

## Provenance, indicator and mapping controls

Every normalized observation retains exact identity/expiry, native price units, tick and
reviewed multiplier, definition/record/archive hashes, source ordinal, event/receive,
retrieval/admission, evidence kind and normalization version. Definition metadata
is also wrapped with its original source position. Undefined clocks/units, wrong
identities, off-tick/crossed prices, gaps/bad receive/snapshot flags and unsupported
schemas reject. Local historical admission is labelled retrospective, not claimed as
contemporaneous point-in-time availability.

Repeated ingestion of one archive position is idempotent; identical native bytes at
different positions preserve volume. Profiles use native price ticks and the lowest
price resolves POC ties. Unknown aggressors remain unknown, with separate known-side
delta. CVD is unavailable when direction is incomplete; when all captured sides are
known it remains a captured-window series, not complete exchange/session CVD.
Visible depth is not executed volume, inventory, intent or cancellation attribution.
No field is promoted to a complete exchange-continuity certificate.

The GC sample's indicators are **PARTIAL** because captured consistency does not
prove missing-activity absence. Complete recorded native minutes support the scoped
volatility calculation without synthetic prices; no annualization or regime claim
is made from a fifteen-minute window. Its raw prices and derived values remain in
private licensed outputs, not Git.

Genuine mappings for GC/XAU/USD, ES/US500.cash and NQ/US100.cash are
**MAPPING_UNAVAILABLE** because synchronized broker observations are absent. Five
engineering paired observations demonstrate existing median-basis math plus an
observed quote-spread bound. Mapping validates explicit quote age/skew, price units,
currency, fixed broker-provider identity, session, native contract expiry and sample order. A rejected/rolled observation
clears prior samples. Its uncertainty is an observed bound, not a statistical interval;
mapped levels never become entries/stops/targets automatically.

## Canonical decisions and options

Gold fixtures exercise the actual mandatory structural, causal sweep/reversal,
displacement/retest, M5/M1, structural stop, Fibonacci/targets/RR and expiry path.
Separate fixture confirmation hashes/clocks preserve the canonical repeated closed-bar
observation requirement. Without confirmation the adapter cannot manufacture finalized
evidence. No GC-to-XAUUSD price substitution or new context votes are introduced.

Index fixtures pass the unchanged FlashAlpha context validator and actual index/shared
HierarchyLayerEvaluator, producing NO_TRADE/awaiting confirmation. Required primary
positioning remains mandatory; no Gold evaluator or snapshot-only index strategy is
substituted. Provider/GIL calls are never run; supplied positioning is explicitly a fixture.

Crypto fixtures execute the unchanged production analytical stage builder through
market data, regime, liquidity, sweeps, zones, reclaim, structure, Fibonacci, order flow,
price action and DecisionEngine. CoinGlass-shaped derivatives remain separate from
CME evidence. This builder does not supply a full structural execution geometry;
the preview therefore remains NO_TRADE with that dependency explicit. It is an
analytical compatibility adapter, not a replacement for the existing live hierarchy,
dynamic crypto planner or account/risk engine. Recorded closes retain the existing
engine's reference-price label; they are not presented as current exchange quotes.

The standard OG American fixture recovers IV using the existing futures CRR model
and ACT/365F with an explicit dated rate assumption. American gamma remains null.
The European primitive tests unsigned gamma sensitivity per a 1% futures-price move;
it is a model benchmark requiring an independently reviewed European option convention
and native joins before authentic asset use. No signed dealer inventory, gamma flip,
complete-chain GEX or institutional positioning is produced. OI alone cannot establish
dealer direction. The FlashAlpha → ThetaData → Unusual Whales hierarchy and inactive
GC GIL remain unchanged; actual provider coverage limits are in the audit.

## Validation and preservation

Full credential-free repository regression: **2,060 passed**, zero failures/errors/skips,
including all 43 new Phase 4 cases and existing Phase 3A/3B, canonical assets/providers,
Gold policy, gamma, risk, FTMO and publication regression tests. Native/metadata mocks
test precision, identity, units, unknown sides, flags, multiplicity, order, capacity,
profile ties, OI clocks, mapping instability/freshness/rolls/session/skew and rejection.
Gold positive LONG/SHORT fixtures, index-specific negatives, native crypto compatibility,
missing/stale/mismatched/future inputs, typed execution prohibition, numeric spending
boundary, environment stripping, denied network/process/secret/broker/publisher import
and byte-identical isolated repeats are covered.

The original 523 tracked files are hash-checked unchanged from the Phase 4 baseline.
Prior Phase 3A/3B source and acceptance artifacts, original 69 Fibonacci assessments
across 12 episodes, and frozen/earlier research checkout identities remain preserved.
September 21 04:37 and the 21 Class E omissions remain unresolved in the original
study. Phase 4 neither repairs nor waives them, nor makes that study's 200-bar
continuity veto a prerequisite for a separate scoped indicator calculation.

Private evidence: `private-reports/phase4-acceptance-v2/`; both replay files, source/input
manifest and immutable artifacts. Regression XML/logs: `private-reports/phase4-full-tests-v2/`.
Machine acceptance records the final hashes and runtime versions; failed/development
versions remain separate and are not substituted for accepted results.

## Live readiness and acquisition

| Requirement | Current audited state | Required before separately authorized activation |
|---|---|---|
| Streaming / subscription | Existing GC adapter only, explicit opt-in, bounded duration, reconnect_policy none | Multi-contract lifecycle and authorized entitlements; no Phase 4 subscription registered |
| Reconnect / provider outage | Existing stream quarantines gaps/replay interruptions | Tested backoff, channel-aware continuity and snapshot recovery with fail-closed state |
| Sequence / snapshots | Native sequence/flags retained; record sequence is not a universal unique execution ID or per-contract contiguous counter | CME channel/schema-specific continuity protocol; no empty-window certification from EOF |
| Heartbeat / staleness / closure | Existing snapshots, shared lifetimes and native status/calendar utilities | Recorded live heartbeat/outage/closure scenarios and snapshot-to-stream parity |
| Contract roll | Explicit contract identities and mapping sample reset; no synthetic continuous prices | Reviewed roll source/effective time, definition revision lifecycle and subscription switch |
| Backpressure / memory | GC stream queue and callback backlog both bounded at 2,048; local indicators bounded at 50,000 positions | Measured sustained/burst multi-asset rate, CPU/RSS/p99 latency, overflow quarantine/recovery |
| Persistent provenance | Immutable research files, existing SQLite; runtime PostgreSQL/Redis already present | Live checkpoint/restart parity and schema/roll/source audit durability |
| Infrastructure | No demonstrated database/transport capability gap for this offline workload | Quantified gap before any QuestDB/Grafana/Kafka/other infrastructure proposal |

No live-readiness certification is claimed from fixture throughput or unit tests.
The isolation guard is defense in depth for trusted source, not a hostile-code OS sandbox.
The current broker/native-crypto export adapter accepts reviewed continuous finalized
UTC windows; authentic broker holiday/closure/history-calendar exports and native current
quotes/derivative provenance need dedicated validation before claiming an end-to-end
authentic broker or crypto preview. Canonical runtime adapters remain available and intact.

Two minimal ESZ6/NQZ6 definition candidates are recorded for October 5 00:00–00:01 UTC,
with unknown publisher/IDs rather than invented definitions. Those names are proposals,
not proof of listing/availability. Only after reviewed native identity discovery would
an exact-contract 15:00–15:15 sample be constructed and checked with the existing cache
overlap planner. Fresh provider count/size/cost, licensing/entitlement, account credit and
residual exposure review are required. No estimates, receipts or budgets are fabricated.

General credit permission is retained. The Phase 4 prompt additionally requires a
**separately confirmed numeric credit-only ceiling** and **reviewed request-specific
receipt** before any billable request. No such amount is provided, so the default $0
budget remains unchanged. Historical cache billing remains unreconciled and is not
relabelled free. No cash, automatic retries, secondary assets, options chain, depth or
live subscription is purchased.

Next steps: review the bounded ES/NQ identity/sample proposals with current account
metadata and a concrete ceiling; provide separately verified synchronized broker
exports and calendars; validate native options exercise/chain/OI/rate coverage and model
stability; then rerun these source-bound previews. Production deployment, live data,
trading activation, GIL and policy amendments require separate authorization.
