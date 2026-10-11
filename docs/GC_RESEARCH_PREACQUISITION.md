# Native GC research: pre-acquisition boundary

This implementation is isolated research, not production integration. It deliberately stops before billable acquisition. GIL and all publication, approval, pending-order and execution capabilities remain absent.

## Baselines and implementation plan

The development branch starts at broker Phase 4 `890b8f7deba379931a3ce7df5b6e6fb5760f2d73`, which contains Databento Phase 2 `0851fb7c7b5340e1e0f8d038e30215d6b15ed2ec` and canonical Gold `0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`. The separately checked-out H1 research remains pinned to `f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35`. The repository remote is Patrick8552/monatise-live.

Before editing, the plan was communicated: add a native GC research interface, deterministic candle aggregation and a credential-free subprocess calling the existing selector; reuse guarded acquisition preflight; quote exact bounded requests; stop for approval. Existing components are not overwritten. No dependency, production code, strategy policy, migration or deployed service is changed.

## New files and reusable components

All additions are under `monatise/research/gc_fib`, with `tests/research/test_gc_fib.py` and this document:

| Addition | Responsibility |
| --- | --- |
| `__init__.py` | Pinned baselines, v1 selector identity and false isolation flags |
| `preflight.py` | Exact-contract metadata checks and bounded quote partitioning; no acquisition command |
| `candles.py` | Immutable native GC OHLCV, raw clocks/hash references, reviewed sessions and aggregation |
| `runner.py` | Pinned-checkout validation and sanitized subprocess environment |
| `bootstrap.py` | Selectively load new research modules while keeping original engines/selector |
| `worker.py` | Causal H1 parent capture, unchanged episode/selector, constrained Fib diagnostics |

Reuse:

- `research/databento/acquisition.py`: HistoricalRequest, SDKHistoricalSource.preflight, bounded one-attempt download authorization, PostgreSQL HistoricalMetadata and HistoricalAcquisition.
- `research/databento/archive.py`: original DBN encodings, immutable content hashes, staged/quarantined objects and bounded decoder.
- `research/databento/replay.py`: genuine definition reconstruction, native RecordObservation and retrospective GC identity/coverage gates.
- `adapters/databento_identity.py`: GLBX feed identity separately from economic exchange XCEC. The historical reconstruction path already handles this correctly; the legacy default fixture publisher convention is not used as an authentic-feed identity claim.
- `research/gold_retrospective/runner.py`: verify unchanged pinned checkout.
- Frozen `research/gold_fib/models.py::H1ParentSnapshot`, `episode.py::H1StructuralEpisodeAdapter`, `GoldH1StructuralLegSelector`, and the optional constrained FibonacciRequest path.
- Existing GoldLayerEvaluator price analytics, MarketStructureEngine, liquidity, sweep, supply/demand and reclaim engines; existing causal `sweep_reversal` for M15 diagnostic evidence.

## Acquisition scope and authorization

Dataset GLBX.MDP3; raw symbol GCZ6; expected publisher 1 and instrument 41271, verified by fresh symbology/publisher metadata. Start 2026-10-05T00:00:00Z; end 2026-10-10T00:00:00Z exclusive. Schemas: definition, status, ohlcv-1m, trades and mbp-1. No options, continuous symbols, parent symbols or live subscriptions.

Each request retains the existing limits: at most 1,000,000 records, 256 MiB wire bytes and a seven-day maximum window. Metadata record count and uncompressed billable size are queried without the record cap, so a capped quote cannot masquerade as complete-window coverage. Oversized scopes are recursively partitioned with exact adjacent UTC minute boundaries, fewer than 64 requests and conservative decoded-size headroom. API completion still cannot prove gap-free exchange coverage. Record-limit equality remains suspicious and requires reconciliation.

The generated proposal binds each request hash, preflight hash, contract, schema, time range, cost and limits. The native archive root is operator-owned research storage: `staging/<request_sha256>.dbn.part`, `objects/<native_sha256>.dbn`, and separate quarantine objects. Compression/DBN versions remain native despite the `.dbn` object suffix. No archive content hashes exist before acquisition.

Costs, account credit/expiry, access evidence and exact partition intervals are recorded separately in the private task outputs, not committed here. Authentication and metadata do not establish entitlement. Operator review must independently confirm account usage access and this dataset's historical licence requirements. That attestation is distinct from a successful data-endpoint test.

Before any paid request, the existing Phase 2 service requires a recorded exact-scope human approval, opaque review/entitlement/credit references, matching request/preflight digests, fresh preflight and credit checks, verified unexpired sufficient credit, acknowledgment that estimates are not hard charge caps, and a short-lived receipt (maximum five minutes). One receipt permits one attempt. No automatic paid retry. Partial transport is preserved with unknown final billing until reconciled. The research PostgreSQL store must be operator-owned and durable; private integration-test clusters prove the storage interface, not that a persistent acquisition store is already provisioned. No production DSN is required.

## Native data and timeframe semantics

Phase 2 normalization must first verify authentic definitions, publisher, economic exchange, maturity, tick/units and archive integrity. `from_observation` then accepts exact native GC OHLCV observations and keeps prices in their original scale until Decimal conversion. Nanosecond clocks, retrieval and admission remain integers. Undefined DBN prices and contradictory finalization clocks fail closed.

The native OHLCV bar timestamp is the start of a provider receive-time aggregate. It is not proof of original local availability. The research availability convention is explicitly bar close plus ten seconds; it is never reported as genuinely observed point-in-time evidence. The engine's datetime/float views are derived analytical views; native clocks and Decimal prices remain in source provenance.

Only supplied, externally reviewed exchange-session intervals are accepted. GCSession is separate from broker GoldSessionCalendar. M1 bars are aggregated deterministically into M5/M15/H1/H4 on UTC grids. A coarser bar must fit entirely inside one reviewed session and contain every required minute; partial session bars and missing-or-no-trade minutes are excluded with reasons. No empty bars are generated. An absent minute alone is not proof of a provider gap. No cross-contract aggregation, roll adjustment or spot conversion occurs. GC exchange calendars/status reconstruction from actual records remains an acquisition-stage validation responsibility.

## Frozen selector and truthful scope

The worker uses the original `gold-fib-h1-structural-leg-v1` adapter and selector directly. It captures H1 parents at original assumed availability, uses at most the canonical 200-candle history, excludes future evidence, freezes the captured objects, keeps confirmed pivots/first impulse endpoint/episode association intact, and does not renew expiry when rereading an old parent. History, structure confidence, anchor age and 2 ATR gates remain intact. No v2, M15 anchor or generic historical fallback is introduced.

Raw FIB_TP1/2/3 identities remain associated with 1.272/1.414/1.618, indexed by ratio rather than engine sort order. Raw prices are not final TPs. All candidate eligibility is false until a qualified setup exists; no fabricated entry, stop, RR, target plan, spread or execution quote is supplied. H4 remains an advisory diagnostic, M15 exposes causal Gold pattern evidence, and M5/M1 expose price analytics only. Their outputs do not assert a qualified trigger or entry.

This is an intentional interface limitation. The original GoldSetupSeed checks broker XAUUSD identity, session, units, observed spread/stop allowances, five-context association and recomputed prepared risk. The original F0 final validation binds XAU/USD. These wrappers cannot accept native GC unchanged. The safe reusable boundary is native price analytics plus the unchanged H1 selector and constrained Fibonacci engine. Canonical analytical comparisons are therefore limited to those reused components. Canonical XAUUSD decisions and TP plans are explicitly unavailable. The full F0 target admission, nearest-objective RR, spacing and final validation are not claimed to have run on GC; they cannot be replaced with invented broker facts.

The five-day window also cannot supply the 50 H4 bars required by the existing regime/liquidity defaults. No earlier warmup is silently acquired. A later expanded warmup scope needs separate approval. Missing lower-timeframe evidence stays unavailable.

## Engineering and real-market evidence categories

Synthetic tests cover exact GC identity separation, five timeframe aggregation, missing/no-trade intervals, duplicate/revision handling, session boundaries, nanosecond precision, caps/partition adjacency, deterministic native long/short constrained anchors, B confirmation latency, later pivot exclusion, frozen-parent expiry, immutable output and sanitized environment. Production modules do not register this package; the worker imports no Telegram/approval/execution interface and exposes no paid data transport.

Synthetic fixtures are artificial price patterns reused from the frozen research tests. They are not GC observations, historical performance or FTMO validation. Separate native-GC synthetic diagnostics reproduce A/B and raw extensions, reject unconfirmed B, and reject expired parents. Repeated parent assessments are clustered by H1 episode; they are not counted as independent qualified Gold setups.

The completed engineering suite reports 1,990 passed and 14 skipped. All 28 new focused tests pass without skips. The unchanged pinned selector/Fibonacci regression suites report 62 passed without skips. The initial full run's packaged-CLI failure was a missing virtualenv executable on PATH, resolved by using the existing runtime path; production code was not changed. Seven initially skipped cross-checkout tests ran after supplying the pinned checkout. The remaining 14 skips require explicitly configured general PostgreSQL/Redis integration endpoints; the isolated Phase 2 private PostgreSQL tests passed.

The small artificial diagnostic pilot contains four parent assessments in two H1 episode clusters: two valid constrained Fib assessments, one B-unconfirmed rejection, and one expired-parent rejection. Long A/B = 2450/2530 gives raw 2551.76, 2563.12, 2579.44. Short A/B = 2550/2470 gives raw 2448.24, 2436.88, 2420.56. Those prices are deliberately artificial. GoldSetupSeed counts, final target eligibility, nearest-objective RR, target-distance rejections and trade outcome distributions are unavailable, not zero measured market results.

Authentic market-data, retrospective real-market and verified PIT categories remain unavailable until an approved acquisition supplies genuine records. No authentic candle count, archive hash, target reachability, stop-first, same-bar order, MFE/MAE, fill or profitability result is inferred from the metadata or engineering fixtures.

## Next milestone and acceptance boundary

After exact acquisition approval: provision/verify isolated durable research persistence, refresh the required checks and receipts, use the existing one-attempt downloader, validate native definition/status and data records, preserve quarantine/revisions/coverage, review exchange sessions, aggregate the five timeframes and run native H1 diagnostics with recorded availability assumptions. Stop on contradictory identity, incomplete transport or invalid evidence; do not retry paid requests automatically.

Qualified native-GC setup and final target comparison require an explicitly documented GC technical evidence contract that preserves the canonical causal checks without pretending futures units/spreads are broker inputs. Until that incompatibility is resolved, the adapter must keep full target eligibility and outcome statistics unavailable. A later price-path evaluator must independently state its hypothetical reference, expiry, missing coverage and same-bar ambiguity; it must not report fills or trading profit. No production integration, research merge, GIL activation, broker access or selector revision is part of this milestone.
