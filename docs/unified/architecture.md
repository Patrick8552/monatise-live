# Isolated native-futures unified decisions

## Base and boundaries

Base: `codex/native-btc` at `1979440d8c25dda5d2b7d7c3a92ba5ede1a008d7`. New package: `monatise.research.unified`. It is opt-in via `python -m monatise.research.unified`; no application entrypoint, existing engine, router, startup, execution setting or production file is changed. Runtime decisions bind a SHA-256 of all new package Python sources, the frozen policy, and source manifest.

The package creates no provider client and reads no API credential. `archive.py` uses public DBN decoding/file APIs and the approved native definition validator only. Actual source controls, hashes and per-schema bytes must reconcile before use. Subscription metadata is not accepted as proof of a connected feed. Source order violations, mismatched overlap, invalid ticks or incomplete replay fail closed.

## Components

| File | Responsibility |
| --- | --- |
| `models.py` | Frozen snapshots, exact contracts, Decimal prices, stable event/opportunity identities and a fixed 40-digit arithmetic context. |
| `policy.py` | Explicit unresolved default and opt-in versioned exploratory definitions; no optimization for profit. |
| `archive.py` | Genuine hash-bound historical/native DBN sources, replay reconstruction, product calendars, explicit availability clocks and labelled modeled spreads. |
| `evidence.py` | Real-child aggregation, causal strict pivots, confirmed structure, completed breaks/displacement/retests, provisional sweeps and shared reversal parent episodes. |
| `diagnostics.py` | Confirmed-anchor Fibonacci and exact retained-execution VWAP/profile/delta; never session certification or an extra vote. |
| `pathways.py` | Independently testable A/B/C permissions; A need not wait for neutral M15 alignment; C remains local and context-permitted. |
| `eligibility.py` | Data, lifecycle, participation, geometry, nearest-target net R:R, price tolerance, freshness and final revalidation. |
| `arbitration.py` | Same-episode/evidence deduplication, opposing-direction abstention and unique economic/timing dominance. A separate registered earliest-trigger comparison baseline cannot alter the default policy. |
| `store.py` | SQLite WAL/FULL durability, atomic decisions/first selections/lifecycle/outbox, stream isolation, immutable plans and monotonic timestamp guards. |
| `service.py` | One reference decision per exact instrument/stream/cycle; final time is selection time; no retrospective fill permission. |
| `outcomes.py` | Separate immutable hypothetical fills/outcomes. Unsupported OHLC ordering remains unresolved; no synthetic broker fills. |
| `replay.py` | Frozen input replay, independent experiment state and shared immutable feature work; no forward-test claims. |
| `__main__.py` | Offline inventory/replay/comparison CLI and explicit No-trade source-validation failures. |

## Identities and persistence

A canonical M5 break is the continuation/reversal parent. A and B share that parent; a C sweep is provisional until a separate later matching reversal break is proven. Only then can C attach to the same parent. Contract, side, structural references and episode event determine market identity; model labels, mutable quotes, admission timestamps and archive packaging do not.

Source availability remains in provenance. It is not erased when event identity is stable. Different genuine episodes at the same price are different opportunities. Explicit roll events supersede old reference signals without falsely closing positions.

Streams bind configuration, source-manifest and implementation hashes. A changed configuration/code requires an explicitly new experiment. A-only, B-only, C-only, unified and baseline state never consume each other's selections. Source market identity may be shared; mutable lifecycle and outcomes are not.

The ledger stores raw/provisional observations, market events, context/trade classifications, opportunity lifecycle, immutable selected plans, decisions, local outbox and separate position events. A market trigger does not claim selection. A later first selection can occur only while still eligible. Repeated reports retain the selection ID and use `is_new_selection=false`.

A selected plan freezes owner, entry zone, stop, targets, costs, evidence, initial modeled risk and management. Later classifications are annotations. A subsequent simulated fill records actual fill risk separately; realized-R uses that stated original fill denominator. Terminal opportunities cannot resurrect. Completed shadow opportunities cannot be selected again.

Every selection transaction includes lifecycle/cursor changes, selected plan, first-selection claim, decision and local outbox. Unique keys and `BEGIN IMMEDIATE` serialize concurrent workers. Same cycle/same inputs returns the stored decision; changed inputs conflict; older cycles cannot overwrite newer knowledge. Standalone lifecycle transitions also open a transaction and advance the cursor. Outbox acknowledgements are idempotent local writes, not exactly-once external delivery.

## Data semantics and recovery

Only completed available candles can confirm structure. Parent bars need real children or source-reviewed provider no-print intervals; missing trading minutes are not filled. Parent buckets spanning maintenance are excluded. Old degraded/unreviewed segments are omitted, and later clean segments must establish their own confirmed structure. This recovery does not certify the omitted segment or reconstruct its missing prices.

Historical event-time results explicitly model publication availability; actual archive retrieval remains preserved. As-recorded mode uses captured admissions and never relabels reconstructed quote availability as actual. Scheduled-news availability is likewise explicit. The small retrospective sample has incomplete news coverage; strict news-required policies remain ineligible, while the exploratory comparison explicitly reports its waiver.

The exploratory historical quote model uses a frozen maximum finite development-capture spread, rounded up to even native ticks. It is not a future spread bound or a broker feed. Actual recorded L1 is used when sufficiently fresh. Fee-equivalent and slippage assumptions are explicit native ticks, not broker commissions.

Executed bars can demonstrate participation plus directional price rejection, but not aggressor delta. The separate robust-aggressor variant requires retained execution coverage and a directional sign that survives assigning all unknown sides against it. Diagnostics never claim full-session VWAP/CVD, institutional identity, depth absorption, options or OI.

## Risk and execution separation

All outputs are `SHADOW`, `execution_eligible=false`, with no order intent or account sizing. The absence of broker data does not prevent futures-reference research. It does prevent claims of broker-executable prices, validated broker sizing or account risk approval.

`monatise.application.__init__` eagerly imports the existing engine application, so even importing its otherwise simple risk-policy child is not allowed in this isolated process. This release does not bypass that initializer or copy only a per-trade percentage and claim full risk approval. Existing production capital/drawdown/approval/kill-switch controls are unchanged. Account-risk validation is explicitly unavailable here. Research comparison enforces one pending/open reference exposure per instrument/stream; this is not a broker account risk model.

A failed final revalidation never promotes a runner-up. Final revalidation checks window stop/target breaches, price recovery after a breach, spread widening, expiry, data/news state and changed structural context. Selection and cursor timestamps cannot precede the final admitted snapshot.

## Output semantics

BUY/SELL means an eligible triggered reference plan has been selected; it is never a broker instruction. Armed direction remains NO_TRADE. No-trade actionable prices are null. Conditional lifecycle details persist in the watch/event ledger. `signal_status=null` in the final decision means no selected signal; watch records may still exist, as indicated by watch counts and the audit tables.

The complete machine record contains rejection/comparison evidence. A short GC response must still show one selected setup or No trade, actual timestamps and limitations, not competing scenarios.

## Dependency policy

Allowed runtime dependencies are Python standard library; local `monatise.research.unified`; the existing root/core/strategy initialization; and the audited native definition/data-normalization dependency closure under `monatise.adapters.databento_identity`, `monatise.research.databento`, and `monatise.research.institutional`. The DBN reader may import the installed Databento SDK for file decoding only.

Forbidden: `monatise.engines`, application orchestration/routers, canonical crypto engines, broker Gold hierarchy, retired selectors/GIL routes, provider client construction, network publication and order APIs. Clean-process tests verify core and genuine archive loading without importing the 20 engines; provider constructors are replaced with failing functions during integration tests. The validation report includes the observed runtime import closure.
