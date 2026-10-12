# Phase 4 integration audit

Read-only audit completed on October 12, 2026 before implementation. This local
research branch is `research/databento-cme-foundation`, clean at Phase 3B
`f784b268257a55fad31b4d85c88e7d75ffefca1a`. It descends from production-source
`0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`, foundation `3340bfc5…`, and Phase 3A
`0b3050d…`. These describe local source history, not the current deployed service.
The frozen selector checkout is clean at `f1de9d46…`; earlier research is clean at
`a144db7…`. Phase 3B final source hashes match acceptance. A private baseline binds
all tracked files and these identities. No user changes or AGENTS.md were present.

## Component and dependency matrix

Runtime status below means observed source wiring; no production endpoint or
credential is accessed. Research packages are opt-in and not runtime registrations.

| Component / source | Classification | Public interface / dependencies / runtime | Existing verification |
|---|---|---|---|
| Historical acquisition, `research/databento/acquisition.py` | REUSABLE | HistoricalRequest, preflight, GuardedHistoricalAcquisition; injected SDK/metadata, explicit one-use approval | research/test_databento_history*, test_cme_infrastructure |
| Raw DBN/ZSTD, `research/databento/archive.py` | REUSABLE | NativeDBNArchive, dbn_records; DBN decoder, immutable hashes/EOF verification | archive tamper, truncation, count/cap tests |
| Dataset discovery, `research/databento/datasets.py` | REQUIRES ADAPTER | DatasetRegistry, discover, select_contracts; observed metadata, GC/OG/ES/NQ/CL only; no entitlement implied | test_cme_infrastructure |
| Gold definitions, `research/databento/registry.py`, `gc_fib/native_contract.py` | REUSABLE | GoldInstrumentRegistry, reconstruct_native_gcz6; narrow reviewed native GC economics | test_databento_foundations, test_gc_native_contract |
| Cache/budget/storage, `research/databento/controls.py`, `candles.py` | REUSABLE | ResearchLedger.plan/report, ResearchArtifactStore.publish; SQLite/local immutable artifacts; production separately has PostgreSQL/Redis | cache overlap, reservation, settlement, immutable layer tests |
| Historical replay, `research/databento/replay.py` | REQUIRES ADAPTER | HistoricalGCReplay; GC reference and bounded source scope. Generic hash dedup is not complete execution-volume evidence | test_databento_history; Phase 3B multiplicity audit |
| Trades/MBP, `research/databento/advanced.py` | REUSABLE | AdvancedAdapters.normalize, book_metrics; explicit metadata/schema opt-in; needs outer flags/availability/source-position boundary | test_cme_infrastructure |
| Candles/calendar, `research/databento/candles.py`, `gc_fib/candles.py` | REUSABLE | normalize_candle, aggregate, quality; explicit session evidence, native fixed prices; no gap fill | test_cme_infrastructure, test_gc_fib |
| Native status, `research/gc_continuity/sessions.py` | REUSABLE | status_sessions, complete_minute_sessions; raw transitions and source order; GC nominal calendar is a cross-check | test_gc_continuity |
| Native GC qualification, `research/gc_qualification/*` | REUSABLE | isolated prepare/qualify/runner; frozen pinned engines, exact-contract data admission | 33 qualification cases, twin replay hashes |
| GC continuity, `research/gc_continuity/*` | REUSABLE | forensic scan, ABCDE classification, guarded recovery; no certified empty-interval evidence | 36 cases; 21 unresolved E minutes, unchanged 4,049-cutoff result |
| Futures/broker basis, `application/gold_basis.py` | REQUIRES ADAPTER | GoldBasisService.add/estimate/map_level; synchronized genuine quotes, bounded samples, dispersion/residual, roll reset. General index policy absent | test_databento_gold |
| Gold, `application/gold_analysis.py` | REUSABLE | GoldHierarchyAnalysis/GoldAnalysisCoordinator; GoldLayerEvaluator, broker candles/units, structural risk, TP; shadow release remains blocked | test_gold_technical_first, gold_sessions, price_guard |
| Indices, `application/market_intelligence.py`, `hierarchy/assets.py` | REQUIRES ADAPTER | FuturesMarketIntelligenceCoordinator validates FlashAlpha context, then AssetHierarchyAnalysis on broker candles. Gold evaluator is not the index evaluator | shared_timeframe_hierarchy, nq_direction_integrity |
| Crypto, `application/production_analysis.py`, `hierarchy/*` | REUSABLE | build_production_analysis_run; native exchange/CoinGlass market and derivatives, canonical scoring. Independent crypto hierarchy also exists | application_real_pipeline, coinglass*, runtime_regressions |
| Fibonacci / structure / sweeps / reclaim / regimes | REUSABLE | engines/fibonacci_liquidity, market_structure, liquidity_sweep, reclaim, regime; unchanged typed requests/defaults | corresponding engines tests |
| VWAP/profile/POC/CVD | PARTIALLY IMPLEMENTED | Existing GC replay metrics; outer coverage, exact multiplicity and multi-asset provenance needed | historical replay tests; Phase 3B native reconciliation |
| OI statistics/options, `research/databento/options.py`, `application/gold_options.py` | PARTIALLY IMPLEMENTED | normalize_open_interest, join_inputs, option_analytics; standard OG American price/IV, European benchmark Greeks; American gamma uncertified | test_gold_options, test_cme_infrastructure |
| Gamma integrity, `application/gamma_evidence.py`, gamma_reconstruction.py | PARTIALLY IMPLEMENTED | GammaEvidenceLadder: certified primary, injected independent chain/cross providers; no concrete ThetaData/UW adapters in this checkout | gamma_evidence, gamma_approval, gamma_confidence |
| Decision Layer, `engines/decision`, `application/registry.py` | REUSABLE | DecisionEngine.assess; crypto typed evidence and policy, distinct hierarchy decision contract | engines/test_decision_engine |
| Risk/sizing, `engines/risk_validation`, capital_allocation; `application/hierarchy/risk.py` | REUSABLE | typed risk and structural invalidation/RR; production account governance separate | numeric/risk/FTMO tests |
| Telegram/approval, `application/trade_publication.py`, deployment.py | NOT APPLICABLE | publish_proposal/TelegramNotificationTransport/approval state; excluded from Phase 4 runner | trade_publication, telegram_approval_window |
| MT5/FTMO, `application/ftmo_master.py`, ftmo_execution.py | NOT APPLICABLE | authenticated bridge, symbol specs, governance, one-use approval; never instantiated | ftmo_master/execution, mt5_bridge_contract |
| Providers, `adapters/coinglass_production.py`, hyperliquid.py, alpaca.py, flashalpha.py | REUSABLE | existing live adapters remain untouched; offline transports injected | provider adapter/regression tests |
| Deployment, render.yaml, Dockerfile, deploy/*, live/server.py | NOT APPLICABLE | existing local/server/PostgreSQL/Redis architecture; no Phase 4 registration, migration or deployment | production_entrypoint, application_deployment |
| Unified institutional observations / preview | MISSING | add research-only contracts/adapters; do not add a production engine | new focused tests required |

## Assets, authentic evidence and compatibility

| Asset | Existing local authentic evidence | Canonical preview boundary |
|---|---|---|
| GC → XAU/USD | GCZ6 publisher 1/instrument 41271: definitions, OHLCV, trades, MBP-1, status; no synchronized broker data | GC captured indicators available; broker mapping unavailable; genuine Gold preview cannot be qualified from GC prices |
| ES → US500.cash | No authorized exact ES definitions/observations in the accepted archives | Explicit missing data; engineering fixtures may exercise index hierarchy |
| NQ → US100.cash | No authorized exact NQ definitions/observations | Same boundary as ES; no assumed ES/NQ contract IDs |
| OG / ES options / NQ options | No accepted local authentic option chain, OI, quotes or rate inputs | Model interfaces/controlled fixtures; authentic analytics unavailable |
| BTC/ETH/SOL | Existing production adapter source, no authorized local authentic native exchange export for this task | Unchanged production crypto request builders/engines exercised with labelled fixtures |
| CL/YM/RTY/CME BTC/ETH | Architecture descriptors only, disabled | Need exact definitions, reviewed economic conventions and separately scoped validation |

The registry actually uses `XAU/USD` and `USOIL.cash`. Requested XAUUSD and USOIL
names are economic aliases, not authority to rewrite registered broker identities.
GC/XAU-EUR/AUD mappings are excluded because currency and quote units differ.

Databento describes futures and futures-options in GLBX.MDP3, native trade-summary
sides including unknown implied aggressors, and published OI statistics in its
[feed specification](https://databento.com/docs/venues-and-datasets/glbx-mdp3).
Published schema availability does not establish this account's present entitlement.
No fresh authenticated entitlement, credit balance or estimate is available here.
[Definitions](https://databento.com/docs/schemas-and-data-formats/instrument-definitions)
must establish exact IDs/expiry/ticks; DBN fixed prices are not multiplied again by
display_factor. Native GC multiplier field is undefined; reviewed native economic
terms and contract conventions must supply the monetary multiplier explicitly.

The desired FlashAlpha → ThetaData → Unusual Whales hierarchy is preserved.
ThetaData's public [FAQ](https://www.thetadata.net/faq) explicitly says CME futures
are not currently available. Its [product plans](https://www.thetadata.net/subscribe)
for stock/index options do not establish OG or ES/NQ futures-option coverage.
Unusual Whales now advertises CME futures on its [API page](https://unusualwhales.com/public-api),
but that does not prove OG chain/OI/Greeks or independent dealer inventory access.
No provider subscription or GC GIL activation is made.

## Risks and minimal proposed source changes

Use a new `research/institutional/` package with normalized native-source wrappers,
bounded captured-window indicators, a general context mapping wrapper around the
existing basis math, isolated options model joins and a typed non-executable preview.
Use canonical Gold/index evaluators and unchanged crypto stage-input builder/engine
registrations. Replace only offline transport and clock, never analytical rules.

Preserve native source positions: byte-identical executions at distinct ordinals
can be legitimate. Hash-only dedup cannot certify volume. Explicit flags, incomplete
coverage, undefined sides and retrospective availability remain visible. OI does not
identify dealer sign; American IV does not certify American gamma. Model assumptions
and option exercise family require reviewed evidence rather than a root-name guess.

No source-policy amendment, shorter lookback, longer lifetime or H4 realignment is
authorized. September 21 GC continuity is local to its original historical study;
it does not block processing another explicitly scoped captured window or asset.
No new infrastructure is justified by the bounded offline workload. Live reconnect,
channel sequence/snapshot recovery, staleness and throughput certification remain
separate work; current GC stream has bounds but is not a reusable certified live
multi-asset service.

Tests must cover identity/units/clocks, flags and multiplicity, indicator coverage and
unknown sides, synchronized mapping/rolls/expiry, option assumptions and unsigned
exposure, actual canonical asset paths, stale/incomplete/mismatched rejection,
environment/filesystem/network/publishing isolation and deterministic repeats.
Run the existing full offline regression suite. Preserve all prior source/artifact
hashes and the default $0 budget; new requests remain proposals until a concrete
numeric credit-only ceiling, current quote/entitlements and reviewed receipt exist.
