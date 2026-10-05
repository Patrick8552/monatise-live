# XAU/USD technical-first audit

Baseline: main 9f396bfb148b44219020442cddc9d43f96af6565. No AGENTS.md found in the checkout or its parent workspace. Existing Gold price-tolerance branch is unrelated to provider routing. No open Gold/Databento PR returned by connector search. Reviewed `.github/workflows/tests.yml`: PR jobs run tests, paper Docker smoke, and UI checks; no deployment or market-data credentials. Render configuration is unchanged.

## Verified call graph and repair map

- On demand: deployment.analyse_ftmo_futures_instrument -> FuturesMarketIntelligenceCoordinator -> mandatory FlashAlpha -> flip/wall builder. Repair: route verified XAU/USD to the runtime Gold coordinator first.
- Scanner: deployment._analyze_ftmo_futures -> FlashAlpha root queue -> mandatory validation -> flip/wall builder. Repair: exclude XAU/USD from root requests and route to that same coordinator.
- Broker history: signed heartbeat/candles endpoints -> BrokerCandleService pending request -> authenticated identity, nonce, lease, exact hierarchy, CAS -> AssetHierarchyAnalysis. Prior index display-name gate rejected Gold. Repair: registered capabilities, retain index compatibility, history v2 Gold units.
- Reuse: candle finalization/revisions, hierarchy collection, H4 regime, H1 structure, M15 liquidity/zones, M5 break/reclaim, M1 refinement, canonical Fib and multi-target builder. Typed Gold evaluator wraps the reused outputs with correct market/volume provenance.
- New work: strict causal Gold sweep/reversal contract, Gold policy/coordinator, broker-unit stop buffer, Databento adapter/replay, basis, options model routines.
- Approval: deployment publication_allowed -> FTMO create_signal_proposal -> mapping -> shared proof/risk -> broker quote/manual approval -> commands. New Gold results are shadow-only before proof persistence; create_signal_proposal independently rejects the new Gold analytical strategy/provider identities. Existing order/approval checks remain in place.
- TradingView: authenticated webhook -> normalize -> durable reference storage -> Gold assessment, never broker history or execution.

## Test-backed defects

Baseline: `uv sync --extra dev`; `uv run pytest -q`: 1646 passed, 14 skipped (Postgres/Redis infrastructure). New Gold tests cover the repaired routing, registered capability, mandatory chronology, units, source dependencies, and proposal veto. Exact final commands/results are in the delivery report.

## Limits discovered

EA 1.22 converts ALL history using the CURRENT server offset. It does not supply historical DST transitions, exchange holidays, or an authoritative historical broker session calendar. EA 1.23 adds history v2 units and explicitly labels this limitation. The patch does not claim live timestamp certification. Gold patterns reject gaps within the causal sequence and never synthesize bars; closed/current-session failures remain unavailable. Complete historical DST/holiday certification remains release work.

This audit describes source changes and offline fixtures. It is not a deployed or live-certified system. Optional model and stream capabilities are separately documented; unsupported families and uncertain claims remain unavailable.
