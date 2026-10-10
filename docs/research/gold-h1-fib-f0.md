# Gold H1-Fib F0: isolated engineering milestone

Policy: `gold-fib-h1-structural-leg-v1`. Engine: `gold-h1-fib-f0-engineering-v1`.
Canonical source baseline: `0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`.
Specification baseline: approved Revision 2, `outputs/monatise-gold-fib-specification/specification.md` in the user's workspace.

This is an opt-in local research package, not a runtime registration. No production module imports it. Its result is a research record, not an approval proof or execution intent. GIL target-modification arms are absent. No provider clients, messaging transport, approval store, order manager or broker execution transport is constructed by the runner.

## Current behavior and isolated changes

The canonical Gold evaluator keeps H4 advisory, H1 directional, M15 causal sweep/rejection/displacement/shift/retest, M5 confirmation and M1 entry refinement. Gold's stop remains the M15 pattern's structural invalidation plus the existing M1 volatility/cost buffer with outward tick rounding. Observed M1 price remains separate from the zone-clamped proposed entry.

The existing target adapter collects all-timeframe liquidity, structure, zones and generic Fib candidates. This remains the default. `GoldHierarchyAnalysis` also explicitly vetoes publication, approval, pending orders and execution under the current unreleased Gold shadow policy. A canonical evaluator baseline in this experiment is not a live production signal or a replay of the older FlashAlpha production route.

Shared seams added in the isolated checkout:

- `PreparedRiskInputs` separates authentic target-independent entry/stop preparation from completion with an actual target. `StructuralRiskInputBuilder.build` still completes the same default proposal.
- `GoldLayerEvaluator.prepare_entry_stop` reuses the same Gold stop formula. It does not generate a target or fabricate passing RR.
- `target_independent_reasons` shares the existing strategy, quality, setup, trigger and expiry admission rules.
- `FibonacciRequest.anchor_constraint=None` leaves generic scoring unchanged. An explicit typed pair must match real canonical OHLC pivots, symbol, timeframe, direction, both supplied pivots, history, age, ATR range and confidence. The optional path cannot select a replacement pair or alternate anchor.
- `crypto_layer_candidates(include_fibonacci=False)` exposes only existing canonical non-Fib objectives; default `True` is unchanged.

## Research flow

`OfflineReplay` -> canonical `GoldLayerEvaluator` with capture hooks -> target-independent `GoldSetupSeed` -> original `H1ParentSnapshot` -> causal `H1StructuralEpisodeAdapter` -> `GoldH1StructuralLegSelector` -> constrained authentic Fib assessment -> fixed raw slots -> technical target validation -> F0 research comparison.

`CaptureGoldLayerEvaluator` records H1 context at creation and keeps the first capture for that context identity. Later refreshes cannot enrich its original evidence. Same-parent revisions fail closed; archived candle revisions invalidate the research context chain. Captures and seeds are detached, sealed JSON/hashes, and tampering is rejected before assessment. The seed independently recomputes canonical preparation to reject a forged narrower stop. Required Gold confirmations and current lower-timeframe snapshots must already pass before seed creation; a target-related canonical rejection does not prevent a genuine target-independent seed.

### Exact v1 anchor hypothesis

Rebuild authentic structure assessments on successive finalized H1 prefixes using actual archived first-final observation times. A break's broken pivot and origin must have been confirmed strictly before the break bar opened. A downloaded historical candle's timestamp is not its known-at time.

The first causal confirmed bullish/bearish BOS or CHoCH starts the active family. Repeated same-direction breaks of the same pivot do not reset it. A different pivot supersedes it. Failed/opposite breaks and origin breach terminate or supersede the family; an unresolved newest event cannot be replaced with an older favorable episode.

LONG A is the latest confirmed H1 low preceding that event and known before its open; SHORT A is the symmetric high. B is the first canonical confirmed favorable pivot at/after the event, before the first later confirmed opposing pivot/episode boundary. It must be the favorable extreme of A..B; A must be the opposing extreme. Plateaus use the canonical plateau endpoint. Missing/unconfirmed B, geometry failure or unavailable origin rejects the pair. No M15 leg, generic highest-scoring H1 swing, older H1 replacement or mixed-timeframe anchor is allowed.

The original parent assessment validates the pair with minimum 15 bars, positive ATR14, confidence >=0.45, range >=2 ATR and both endpoints within the last 160 bars. The replay respects the canonical 200-bar analysis window. A/B are frozen for the H1/M15/M5 association before final target validation, even when RR later rejects. A later entry/trigger observation cannot move them. New parent/setup/trigger identities are required for a new assessment.

Episode identity uses instrument/direction, causal event, broken pivot, origin and policy. Leg identity adds stable A/B candle/content identities, not their sliding-window indices. Separate context, M15, M5, seed and assessment identities remain available.

### Targets and eligibility

Raw identities are always `FIB_TP1`=1.272, `FIB_TP2`=1.414 and `FIB_TP3`=1.618. Price = A + ratio*(B-A), including SHORT's negative signed leg. If no trustworthy pair exists, retain three null slots with truthful reasons; do not invent prices.

Existing liquidity OR zone OR confirmed-structure confluence is mandatory. The original engine's BOS-only extension confluence rule is retained; a confirmed CHoCH alone is not silently promoted to BOS confluence. Round a LONG destination down and SHORT destination up to the broker tick; preserve raw price and adjustment separately.

Admission retains profitable-side, five-hour freshness, five-second future tolerance, confidence >=0.35, relevance >=0.4 and maximum relative distance 0.25. The nearest credible non-Fib canonical objective from every timeframe remains an independent minimum-RR checkpoint. A farther Fib target cannot hide a nearer objective below RR 1.5 or a higher configured minimum. The existing builder retains the nearer price on spacing merges, requires first-target minimum RR and renormalizes existing allocations to exactly 100% for the actual number of targets. It never fills a missing slot.

`candidate_admitted_count` means raw destinations passed per-candidate admission. `eligible_target_count` and `final_target_count` mean the full Decision/plan checks passed. A nearer-objective rejection can have three admitted raw candidates and zero eligible/final targets. Slots retain both candidate and final-decision rejection facts. Final sequential names (`tp1`, etc.) retain original raw ratio identities and merged source lineage.

Final plans pass the existing `TakeProfitPlan.validate` and canonical evidence validator with an actual completed target. No executable evidence bundle is exported. Every final target includes setup/episode/anchor identities and timestamps, raw source slots/ratios/prices, tick adjustment, final price, allocation, RR and freshness. GIL evidence, contract, maturity, basis and uncertainty are explicitly null/disabled, rather than invented.

### Deadlines

Do not renew any deadline. Gold caps H1 at its original candle close +2h, M15 at original retest close +45min, M5 at original source close +15min, then applies ancestor and session minima. The actual repository can shorten H1 through H4/macro expiry (macro TTL is two 900-second refresh periods). A two-hour H1 cap is not a guaranteed two-hour lifetime. F0 retains the earliest effective expiry and reports individual expired deadlines as well as a deterministic rejection reason.

## Local replay contract

`python -m monatise.research.gold_fib.replay INPUT.json OUTPUT_DIRECTORY`

Use the checkout's Python environment or explicitly set `PYTHONPATH` to this checkout when using another environment. No environment feature flag can enable publishing or execution.

Input schema `gold-h1-fib-observation-archive-v1`:

- `evidence_kind`: `POINT_IN_TIME_ARCHIVE` or `ENGINEERING_SYNTHETIC`;
- `source_commit`: pinned canonical baseline above; `source_version`;
- reviewed `gold-broker-sessions-v1` calendar plus matching account/server/symbol identity;
- actual broker `point`, `tick_size`, `spread_price`;
- ordered observations: aware `at`, candle arrays keyed by 4h/1h/15m/5m/1m, each with timestamp/open/high/low/close/volume; optional `warmup_only`.

Observation times must strictly increase. Bars must be unique, ordered, session-aligned and finalized by the existing two-observation +10-second grace normalizer. Known-at is the first actual final observation of that content hash. Revised content cannot inherit the prior content's known-at. A stale/missing/forming expected bar does not receive a cached substitute. Only first assessment of each H1/M15/M5 association contributes a seed event. Duplicate runs yield identical hashes and immutable files; conflicting writes fail instead of overwriting evidence.

Outputs are replay, diagnostic and manifest JSON. The package contains no optimization, wall adjustment, automatic v2, future-data pivot confirmation, hypothetical fill generation or reachability claim.

## Engineering pilot and research limits

`PYTHONPATH=. python scripts/gold_fib_engineering_pilot.py OUTPUT_DIRECTORY`

The artificial cases exercise LONG/SHORT, repeated lower setups under one H1 episode, unconfirmed B, late origin confirmation/geometry, late historical download, the fixed 2 ATR rule, the fixed 160-bar age rule and one/two/three admitted destinations under the fixed distance ceiling. Separate component tests exercise zero/one/two/three final targets and spacing merges. These component tests isolate candidate feeds; they are not canonical qualified trades.

These are synthetic boundary inputs, including independent timeframe patterns, not a coherent recorded broker tape. Counterfactual boundary cases and deliberately constructed target distances must not be treated as a sample of actual Gold availability, reachability, returns or execution quality. The two-setup cases do test real repeated M15/M5 identities under the same synthetic H1 episode; clustered reports preserve that dependence. Unknown episodes cluster by exact parent capture hash rather than being invented.

A representative causal historical archive, archived configuration/contract versions, real calendar, spreads/costs and future outcome observations are required before strategy conclusions. Existing workspace evidence does not supply that archive. Do not substitute retrospective known-at timestamps or claim the fixtures establish which leg is optimal.

Potential later research questions: B-confirmation latency versus opportunity lifetime; episode availability/origin strictness; active-leg breadth and distance/expiry interaction; nearer-objective obstruction incidence; alternative H1 hypotheses compared on the same archive. Any alternative is a separately approved v2; F0 v1 stays fixed.

Stop here: no runtime integration, deployment, publication, approval binding, pending orders or execution. No GIL adjustment arm has been implemented.
