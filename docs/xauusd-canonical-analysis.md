# Canonical XAU/USD analysis: review branch, shadow only

This describes implemented code, not a deployed or live-certified service. Audit and baseline: [technical-first audit](audits/xauusd-technical-first-audit.md).

## Runtime route and price authority

`OrchestrationRuntime._gold_coordinator()` owns one `GoldAnalysisCoordinator`. Both `analyse_ftmo_futures_instrument` and `_analyze_ftmo_futures` use it. The standalone futures coordinator also accepts this service by injection. XAU/USD is selected by exact equality with the verified registry entry, its USD currency and GC relationship. The registry's GC/MGC mapping is unchanged. XAU/EUR, XAU/AUD, silver, other futures, stocks, indices, forex and crypto retain their existing providers. FlashAlpha is neither mandatory nor a fallback for XAU/USD.

Gold is included in the enabled futures scanner independently of the FlashAlpha root allowlist. XAU/USD is excluded from FlashAlpha root requests; other Gold currencies can still request their legacy GC context. A GC request in a mixed scan must not be interpreted as XAU/USD depending on FlashAlpha.

Broker candles establish structure and observed price. The exact native closed M1 observation remains separate from planned entry/zone. No exchange, screenshot, option strike or basis-adjusted price replaces it. Executable Bid/Ask, account risk, point/tick/lot sizing and final order geometry remain the existing broker control plane's responsibility.

## Reused hierarchy and versioned strategy

`GoldHierarchyAnalysis` extends `AssetHierarchyAnalysis` through an evaluator factory; it does not copy the crypto pipeline. `GoldLayerEvaluator` reuses canonical regime, liquidity, sweep, supply/demand, reclaim and structure engines with a market-aware output adapter. Their mathematics stay unchanged; Gold output scope is `broker_xauusd_candles`, and volume is `tick_volume`. Fibonacci uses the unchanged engine's validated anchors, confidence and ratios. Target generation still uses the canonical candidate adapter and multi-target builder, with minimum RR at least 1.5. The analytical target builder is enabled inside the shadow evaluator; no execution flag is enabled.

| Role | Gold authority |
|---|---|
| H4 | Advisory regime, never independent directional override |
| H1 | Directional structure |
| M15 | Causal liquidity setup and structural invalidation |
| M5 | Later aligned, recent confirmed structural trigger |
| M1 | Entry zone/refinement and volatility buffer |

`gold-sweep-reversal-technical-v1` requires broker candles. `gold-sweep-reversal-gc-v1` additionally requires usable GC evidence. `gold-sweep-reversal-options-v1` additionally requires usable options/GIL and basis evidence. These policies are constructor-selected, frozen contracts, not automatic provider-failure fallbacks. Optional evidence availability alone does not add conviction. Their production adapters/activation are unfinished; runtime defaults to technical shadow.

Qualification requires the underlying hierarchy's valid parent chain, mandatory Gold chronology, entry/stop/target geometry and RR. Independent groups are H1 structure, M15 causal liquidity setup and M5 confirmation. Each contributes at most one vote. Reclaim/Fib/location outputs are advisory and do not provide an extra correlated vote; score is not win probability. Unavailable technical data has an unavailable score, with precise reasons.

## Causal sweep/reversal contract

Two-sided liquidity and opposing structure pivots must each be confirmed by two subsequent finalized candles **before** the sweep. A recent candle must sweep the liquidity level and close back across it. A later candle must displace with body/range at least 0.55 and close beyond pre-existing opposing structure. A subsequent retest within three candles must touch that broken level, close on the reclaimed side, and retain both the level and original sweep invalidation through assessment time. A gap inside the pattern rejects it, including a session break; no bars are synthesized. Only the most recent twelve sweep candidates are searched.

The M5 structural trigger must follow the M15 retest, be within the latest three finalized bars, agree with H1/M15 direction, and break a pivot whose three-bar confirmation was already available. A single wick, historical CHoCH, Auto Fib touch, ribbon, BUY/SELL alert or favorable options geometry cannot substitute for the contract. No extra discretionary setup types have been added.

The stop starts at the broker M15 sweep extremum. Volatility, spread and slippage allowances are retained; authenticated broker point/tick units and observed spread can widen them. SL is rounded outward to the broker tick. Entry refinement cannot reduce the structural stop to fit a risk budget. Actual targets must come from canonical evidence and pass the unchanged first-objective RR rule; nearby inadequate objectives reject a setup rather than being skipped.

## Transport, sessions and lifetime

The existing signed MT5 endpoints remain unchanged. History requests remain account/server/symbol/nonce/lease bound, require all five intervals, and use compare-and-swap consumption. Duplicate responses, identity mismatches, future captures, malformed OHLCV, invalid units and stale data are rejected. Read-only `_healthy_bridge` already checks authenticated connection identity and heartbeat age without requiring arming, so no execution bypass/helper was necessary.

EA 1.23 advertises history v2 and adds point, tick size, spread price and the honest timestamp policy `current_offset_uncertified_history`. Index history v1 remains accepted. Gold requires v2 units. The EA's use of today's offset for historical bars is **not** historical DST certification. Broker/COMEX calendars remain separate; Gold never uses the US equity RTH calendar. Broker session closure is reported as closure rather than provider absence. Complete historical holiday, maintenance and DST-aware normalization is still a release blocker. Results using the uncertified current-offset history policy can expose a technical assessment but cannot analytically qualify (`gold_history_timezone_uncertified`).

Two matching provider observations finalize candles. Forming bars stay excluded; closed-bar revisions discard parents. Gold parent lifetime is capped by the original candle close plus canonical lifetime and the parent expiry. Repeated reads cannot renew it. Qualified shadow identities retain the strictest source/session expiry and supersede older identities. Source loss invalidates a previously dependent shadow setup without strategy downgrade. The coordinator's dependency/supersession ledger is bounded and process-local; restart-safe dependency persistence and managed pending-order revocation integration remain unfinished. There are no new approval proofs or managed pending orders to revoke under this patch's disabled policy.

## GC, basis and options: available offline components

The optional `gold-data` extra pins the official Databento SDK to 0.87.0. `GCReplay` parses point-in-time definitions and joins records to an explicitly selected GC outright. Publisher metadata is injected and verified as GLBX.MDP3/COMEX; unknown metadata, spreads, user-defined instruments, continuous aliases, incompatible units and null sentinels are rejected. Contract selection is explicit and replayable; rolls reset quotes, statistics and levels. Automatic most-active roll selection is not implemented.

Only trades contribute volume, VWAP/profile and CVD. MBP-1 contributes quotes; duplicate trade observations in that schema do not count again. Unknown side stays unknown and is accompanied by side-coverage diagnostics. Packet sequences are not falsely assumed contiguous in a filtered trade subscription. Unsupported corrections, reordering, reported gaps, queue/cache overflow and feed errors quarantine the snapshot. A caller must attest completion of the entire session replay envelope; first/last trades alone cannot certify full-session VWAP. No absorption claim is invented.

The SDK stream method uses bounded subscriptions, cancellation/termination and bounded callback/consumer queues. It is explicit opt-in, reuses its adapter, and cannot start from construction or scanning. Live replay watermark verification, automatic definitions discovery, verified market-status/session ingestion, correction application, production stream ownership and reconnect/backoff certification remain unavailable. SDK reconnect is disabled; any disconnect requires reconstruction/replay and produces unavailable evidence.

`GoldBasisService` compares contemporaneous equivalent midpoints, validates quote geometry, age, skew, monotonic unique samples, count, dispersion and residual. It retains the contract, original GC level, observation window, uncertainty, mapped range and expiry. Roll/staleness/mismatches quarantine mapping. It is contextual only and never returns an executable order price. Options underlyings require their own contract basis. Runtime basis sampling/provider wiring remains unfinished.

`gold_options.py` joins standard OG definitions to their actual GC future, with independent option/future expiry and point-in-time availability. The exercise/settlement convention must be supplied explicitly from a reviewed specification. Weekly/strategy families are rejected rather than assumed equivalent. American futures-option CRR pricing and bounded IV solving are implemented; Black-76 and analytic Greeks are European benchmarks only. American Greek stability/certification is unavailable, so standard OG analytics remain DEGRADED, gamma_flip null, and options-dependent strategies cannot be certified by them. Quote/underlying/rate/definition/OI publication times stay distinct. Missing OI is null, not zero, and refreshed quotes never refresh OI.

The numerical root helper accepts an explicit signed exposure model and position assumption; it rejects insufficient coverage, no-root, multi-root, grid/flat and unstable cases. It does not construct dealer inventory from OI. CERTIFIED/CONFIRMED/DEGRADED/UNVERIFIED/INVALID remain integrity/availability vocabulary, never trade direction or profitability. No live Gold options/GIL certificate provider is wired in this branch.

Official references checked: [Databento definitions](https://databento.com/docs/schemas-and-data-formats/instrument-definitions), [fixed-point prices and sentinels](https://databento.com/docs/standards-and-conventions/common-fields-enums-types), [official Python SDK](https://github.com/databento/databento-python), [statistics](https://databento.com/docs/schemas-and-data-formats/statistics), [CME Gold options specifications](https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.options.html), [CME standard/weekly option conventions](https://www.cmegroup.com/articles/files/2023/a-golden-opportunity-revisiting-gold-futures-and-options-webinar-slides.pdf). Live entitlements and redistribution permissions have not been certified.

## Reference inputs and publication

Production TradingView Gold references are opt-in via `MONATISE_GOLD_TRADINGVIEW_REFERENCE_ENABLED=false` by default. The existing webhook authentication, size/rate limits and durable deduplication remain. Exact XAUUSD/XAU/USD aliases, supported timeframe, event timestamp and finite positive price are required. Accepted labels are WAIT, reference-only; entry/SL/TP/grid/hedge inputs are removed. GC remains GC and never normalizes into XAU/USD. Scanner references go to the same coordinator, which independently reassesses broker evidence. On-demand Gold currently does not fetch stored chart references.

Gold results expose shadow/replay mode, policy/strategy, observed price, bias, group scores, technical missing reasons, optional statuses, structural candidates and capped expiry where qualified. Qualification, visibility, publication, approval and execution are separate. `publication_valid`, approval, pending eligibility and execution are always false. This happens before the shared service can persist an executable proof. Runtime proposal creation independently blocks Gold policy results; master proposal creation blocks the new Gold strategy/provider identities. The separately authorized manual operator trade path and previously approved legacy position management retain their existing controls.

## Manual chart checklist

1. Identify exact chart source, XAU/USD versus GC contract, timezone, session and finalized bars.
2. Trace H1 structure and the M15 prior liquidity, sweep, rejection, displacement, shift and retest in chronological order.
3. Check later M5 confirmation, M1 observation/entry zone, broker-unit M15 invalidation and evidence-backed targets.
4. State which observations are manual and which provider/process evidence is unavailable.
5. Screenshots cannot prove authenticated broker history, revisions, actual engine/Fib execution, GC volume/CVD, point-in-time OI, options models/GIL, valid basis, native executable quote, risk sizing, account identity, approval or live eligibility.
