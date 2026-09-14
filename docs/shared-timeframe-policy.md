# Shared analysis timeframe policy

Stocks and indices now consume the existing crypto hierarchy through `hierarchy/policy.py`, `ShadowHierarchyCoordinator`, and `HierarchyLayerEvaluator`. Crypto's timeframe roles, analytical engines, defaults, candle confirmation, and risk construction are unchanged. The policy extraction adds metadata to its diagnostic output.

| Role | Shared timeframe | Existing lifetime |
|---|---|---|
| Context / advisory regime | H4 | 5 hours |
| Primary analysis / directional structure | H1 | 2 hours |
| Setup, liquidity, supply/demand, structural stop | M15 | 45 minutes |
| Trigger / entry confirmation | M5 | 15 minutes |
| Entry refinement and volatility buffer | M1 | Closed-candle evidence |
| Qualified signal | Same hierarchy | At most 15 minutes |

H1 structure remains the directional authority. H4 is advisory. Signal Core uses the existing structure, liquidity, value, and confirmation groups, with at least three of four required; canonical evidence and risk validation must also pass. The unchanged Fibonacci and liquidity/structure/zone candidate producers feed the existing multi-target builder across available finalized layers. The configured stock minimum reward/risk and existing per-route multi-target execution gates remain enforced.

## Data and entry points

The former stock H1/D1 scanner and H1/M15 on-demand confirmation paths delegate to one runtime-owned `AssetHierarchyAnalysis`. The index branch of both manual futures analysis and scheduled scanners uses that same service. Existing discovery, scanner schedules, shortlist limits, provider quotas, optional TradingView context, and cooldowns remain in place. Discovery snapshots do not qualify a setup.

- Crypto keeps its current provider and pipeline behavior.
- Supported US stocks request Alpaca `4Hour`, `1Hour`, `15Min`, `5Min`, and `1Min` candles. Exchange calendar data must confirm the regular session is open; holidays and early closes are honored. Non-US stocks lacking a verified provider continue to fail closed.
- Indices request the five policy intervals through the authenticated FTMO bridge. EA 1.19 adds `history_version=1` and read-only `CopyRates` history. Each response is bound to a random expiring request, account, server, exact mapped symbol, capture time, and complete interval set. MT5 supplies broker trading sessions and trade mode. Index volume is explicitly tick volume, not exchange-traded volume or CVD. History timestamps retain the broker's bar alignment and are converted using the bridge's observed server offset.
- FlashAlpha positioning context remains validated and required on these existing stock/index routes. Opposing stock institutional/positioning context still vetoes a setup. Quiver and Finnhub retain their supplemental roles and scanner enrichment quotas. Direct order-flow inputs are reported unavailable when no verified source exists; positioning snapshots are not relabeled as candle or CVD evidence.
- Gold and other non-index futures-linked instruments retain their previous analysis paths.

The service uses the same coordinator boundary scheduling and two-observation closed-candle normalization as crypto. Forming, missing, stale, malformed, unordered, duplicate, and future data cannot qualify. A revision to an already closed candle discards the stock/index parent chain. Missing data, context conflicts, cancellation, broker breaks, and session closure invalidate active evidence. Analysis has a bounded deadline and no snapshot-only fallback.

## Publication and execution

Manual analysis normalization and scanner notifications carry the policy and role metadata. H1, M15, M5, and M1 evidence flows into the proposal and execution intent rather than being reconstructed from a notification string.

The observed market price and the permitted entry zone are independent facts. Strategy calculations may propose an entry inside a zone, but must never overwrite an observed price with that planned entry, a zone edge, or a midpoint. If the actual closed M1 price is outside the zone, the stock/index result preserves both the observed price (with source, timeframe, and timestamp) and the unchanged zone while waiting. A missing observation remains unavailable.

Telegram normalization enforces this across crypto, stocks, and indices: it never infers market price from a planned entry, and missing/invalid observations block execution. Notifications label observed market price and permitted entry zone separately. Approval records retain the observation separately from the planned analysis entry and native MT5 executable Bid/Ask.

A stock/index analysis signal must match its persisted hierarchy proof: exact parent chain, symbol, policy, M1 entry evidence, direction, levels, and target plan. Expiry is capped by the crypto signal lifetime, parent expiries, and session close. Re-evaluation cannot extend an existing bundle's lifetime. Compare-and-swap persistence prevents an older analysis from overwriting a concurrent invalidation.

The master checks current proof when creating a proposal, publishing it, approving it, and delivering its command to the EA. Superseded/invalidated proofs and old snapshot-only signals are blocked. Explicit operator-entered trade proposals retain their separate manual path. The existing authorized-user checks, approval requirements, kill switch, arm/master gates, account binding, fresh native Bid/Ask validation, broker sizing, spread/stop/freeze checks, risk ceilings, replay protection, and position-management permissions remain enforced.

Namespaces use the existing document store; no schema migration is required:

- `hierarchy_candle_requests_v1`: bounded read-only history requests and responses.
- `shared_hierarchy_signals_v1`: persisted analysis proof, levels, ladder, and capped expiry.
- `shared_hierarchy_current_v1`: current valid bundle or invalidation per instrument.

## Validation and rollout

`tests/test_shared_timeframe_hierarchy.py` covers shared policy identity and real evaluator equivalence, all five provider intervals, confirmed stock/index flows through real coordination/risk/target generation and approval, M1 entry versus M15 stop provenance, four-target plans, session/expiry caps, closed-bar revisions, signed history transport and replay, malformed/stale data, cancellation, quotas, concurrent invalidation, and final EA-delivery rejection. Controlled analytical assessments make the positive integration cases deterministic; separate tests exercise unchanged real analytical engines. Existing publication, risk, approval, pricing, and crypto regression coverage remains enabled.

Backend deployment and installing the compiled EA 1.19 are both required for live index history. Deploying only the backend leaves older EAs unable to qualify indices, with an explicit missing-capability result. No execution or risk feature flags need to change. This branch does not deploy the backend, install an EA on a trading account, send Telegram notifications, or place trades. Live broker history/session acceptance remains a rollout check; compilation and deterministic tests are not a live-feed verification.

References: [Alpaca stock bars](https://docs.alpaca.markets/us/reference/stockbars), [MQL5 CopyRates](https://www.mql5.com/en/book/applications/timeseries/timeseries_mqlrates), [MQL5 trading sessions](https://www.mql5.com/en/docs/marketinformation/symbolinfosessiontrade).
