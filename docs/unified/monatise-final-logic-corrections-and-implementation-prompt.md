# MONATISE — FINAL LOGIC CORRECTIONS AND IMPLEMENTATION

## Task and authoritative references

Implement the isolated Monatise Unified Trade Decision system using:

1. `monatise-unified-trade-decision-implementation-spec.md`
2. `monatise-unified-logic-audit.md`

Both files are in `/Users/thankgod/Documents/Codex/2026-11-04/analyse-btc/outputs`.

The implementation specification defines the strategy and acceptance requirements. The logic audit's corrections take precedence over the conflicting version 1.0 clauses in the seven audited areas. First reconcile them into specification version 1.1, replacing contradictory text rather than merely appending an addendum. Record a correction-to-requirement/test traceability table and the updated document's hash. Version 1.1 becomes the implementation baseline; retain the original version for provenance.

This is an implementation task. Complete the authorized work through verification and a reviewable delivery. Separate completed functionality from unresolved data/validation requirements; do not silently downgrade the requested implementation to a design-only report.

## Repository base and scope

Work in the prepared isolated worktree:

`/Users/thankgod/Documents/Codex/2026-11-04/analyse-btc/work/monatise-unified`

Reviewed base branch: `codex/native-btc`.

Reviewed base commit: `1979440d8c25dda5d2b7d7c3a92ba5ede1a008d7`.

Inspect status, branch, commit, applicable instructions, dependencies and existing native-futures capabilities before editing. Preserve unrelated work. Treat the reviewed commit as the immutable base: do not amend, rewrite, rebase away from, or silently replace it with `main`. Implementation changes belong on the isolated implementation branch/worktree; new descendant commits or a reviewable working-tree diff do not violate the pinned-base requirement. Report the base and resulting code revision/diff.

Do not integrate, modify, replace, invoke, or depend on Monatise's existing 20 analytical engines. Also exclude canonical crypto decision routes, broker Gold hierarchy, retired frozen H1 selector/expiry rules, GIL qualification and the XAUUSD signal router. Ordinary H1/H4 candles remain valid evidence.

Reuse only explicitly audited, engine-independent native-data utilities and risk controls. Verify direct and transitive imports, including package initializers. Do not modify an existing engines initializer or production startup/routing to bypass isolation tests.

Initial scope is supported, definition-verified native futures. Keep exact venue, contract, expiry, tick, multiplier, price unit, source identity and product-specific calendars. Futures research prices are not broker CFD execution prices.

## Phase 1 — Reconcile the seven logic gaps

### 1. Observation admission and opportunity tracking

Create a distinct observation-admission path for valid causal WATCHING/ARMED observations. It must not demand a completed trade trigger or a complete economic plan merely to retain early detection history.

Persist provisional observations and deduplicate them. Attach a durable opportunity ID once the underlying episode is deterministically identifiable. Preserve unresolved relationships as provisional and ineligible; do not assign a misleading equivalence.

Keep the actionable path separate:

`Completed pathway candidates → Full eligibility → Actionable deduplication → Context permissions → Deterministic arbitration → Final revalidation → Atomic decision commit`

The observation path cannot bypass any BUY/SELL eligibility gate.

### 2. Distinct identities and timestamps

Define at least:

- Provisional observation/event identity.
- Canonical market `opportunity_id`.
- `market_trigger_event_id`.
- `selection_event_id` for the selected reference signal.
- Cycle/decision identity and input hash.
- Idempotent publication/outbox event identity.

A market trigger is recorded independently of arbitration. Losing arbitration does not imply selection, execution, or consumption of a first selection. A later first selection is allowed only while the original trigger and entry remain valid and fresh.

Record detection, arming, market trigger, selection and subsequent simulated fill times separately. No simulated fill may precede selection. A repeated report or later pathway confirmation cannot emit another selection. Use `is_new_selection`, distinct from whether the market trigger was newly observed.

### 3. Deterministic opportunity equivalence

Implement a shared causal event ledger and episode resolver. Link A/B/C observations to a common parent episode using explicit structural reference IDs, event ordering and protected invalidation references.

Specify canonical serialization, identity schema version, parent-link rules and evidence-based reset conditions. Do not key the opportunity by model label, evaluation cycle, changing quote or archive packaging/hash. Keep source hashes as provenance.

A at t0 and B at t1 describing the same episode update one opportunity. Similar direction/price alone is insufficient. A genuinely new episode, opposite side or different contract must remain distinct. Unprovable equivalence produces an explicit ambiguity reason and blocks affected actionable publication.

### 4. Experiment isolation

Use one stable canonical market opportunity identity, while isolating mutable lifecycle, selection, publication, shadow positions and outcomes by experiment/decision stream.

Create explicit A-only, B-only, C-only and unified experiment namespaces with frozen configuration hashes and replay manifests. Experiments may evaluate the same market opportunity independently; they must not share consumed-selection or position state.

Preserve duplicate protection within a stream across retries/restarts and policy updates. A configuration change cannot silently reissue an already selected opportunity. A different research experiment must be explicitly named and must never affect production behavior.

### 5. Replay clocks and availability

Implement separate, explicit modes:

- **As-recorded:** actual captured availability/admission, provider timestamps, delivery gaps and observed latency.
- **Historical event-time simulation:** genuine historical records with a declared, frozen publication/latency model; reconstructed availability remains labelled as modeled.

Preserve original retrieval/capture provenance. Do not backdate archive retrieval or claim that reconstructed application availability was observed live. Do not mix modes silently within one performance result.

Only use information available under the selected mode and cutoff. Pivots become usable when confirmed and available; candles must be completed and available. Preserve original contract and calendar semantics. Ambiguous intrabar ordering or unsupported latency assumptions must produce withheld/bounded outcomes, not favorable guesses.

### 6. Immutable selected plans and target windows

At selection, freeze an immutable plan containing intended entry/entry method or permitted zone, structural stop, one to three supported targets, modeled initial risk, costs, management policy, evidence, pathway provenance and all relevant versions.

An actual simulated fill occurs later under the frozen fill rule. Append it as a separate immutable event. Retain the modeled selection risk and separately record actual initial fill risk; identify the denominator used for realized-R reporting. Later classifications, prices or costs must never rewrite the selected plan, original fill or original risk record.

Management events must be timestamped and governed by the frozen policy; they cannot retrospectively improve earlier results. Preserve first-detection and first-selection provenance when B later confirms A.

Define separately:

- Target-ahead price geometry at selection.
- Any registered missed-opportunity rule after arming and before selection.
- Target hits after entry for outcome/position management.

A historical touch that established a swing target is not automatically a post-arm target hit. Resolve target/stop ordering only from sufficient causal evidence; otherwise report ambiguity.

### 7. Atomic persistence, retries and monotonic state

Use transactions, uniqueness constraints and compare-and-set/revision checks to commit the cycle decision, selected-plan snapshot, first-selection claim, lifecycle changes and outbox record atomically.

Identical cycle ID and inputs return the stored decision. Reusing a cycle ID with different inputs is an explicit conflict. Older cutoffs cannot overwrite newer lifecycle state or resurrect a terminal opportunity. Define deterministic ordering for events sharing timestamps.

Concurrent workers and crash/retry scenarios must produce one selection and one logical outbox event. External delivery is not part of a database transaction: use an idempotent outbox protocol rather than claiming exactly-once network delivery. This task authorizes local shadow records, not external messages, broker intents or order delivery.

## Phase 2 — Implement the native-futures decision system

Implement modular A/B/C evaluators from causal market evidence, not hard-coded candidate eligibility booleans or an always-No-trade placeholder.

- **A — Early continuation:** the specified H1 direction or qualifying structural transition, permitted H4 context, completed M5 confirmation and executed-volume support. M15 need not be aligned when its explicitly permitted state is neutral. Missing data is not neutral. A must be able to qualify without B.
- **B — Confirmed continuation:** the specified confirmed H1/M15/M5 alignment and completed confirmation/participation sequence. Update an existing same-episode opportunity instead of emitting a second trade.
- **C — Local liquidity-reference reversal:** a causally established reference, completed sweep/rejection/displacement/reversal/retest sequence, permitted higher-timeframe context and participation. Do not silently expand v1 into unrestricted H1/H4 countertrend trading.

Distinguish UP, DOWN, NEUTRAL_RANGE, MIXED_TRANSITION and UNAVAILABLE. Preserve explicit context permissions and required source coverage. Compute market bias separately from opportunity eligibility.

Preserve the specification's arbitration policy:

- Reject ineligible opportunities before comparison.
- Deduplicate opportunities and repeated evidence, not just labels.
- Only eligible, current, triggered, context-permitted opportunities compete for BUY/SELL.
- Opposing eligible directions produce `NO_TRADE`.
- Multiple same-side opportunities require the specified unique dominance across comparable economic/timing dimensions. Ties or incomparability produce `NO_TRADE`.
- Do not introduce majority voting, a weighted confidence score, automatic B preference, or selection by a distant TP3.
- Failed final revalidation produces `NO_TRADE`; do not promote a runner-up silently.

Implement WATCHING, ARMED, TRIGGERED, INVALIDATED, EXPIRED and SUPERSEDED with explicit transitions, eligibility suspension, terminal-state protection, and separate shadow-position state. An armed SELL retains SELL opportunity direction but has `trade_action = NO_TRADE`. BUY/SELL requires a valid triggered selection and remains reference-only.

Generate exactly one final market bias and one final decision per exact instrument, experiment stream and evaluation cycle. Include identity, versions, signal status, selected opportunity/pathway classifications, timing, source freshness/coverage, complete gate/arbitration evidence, and rejection/reconsideration reasons.

For BUY/SELL reference plans, include defensible entry, structural stop/invalidation, one to three supported targets and conservative cost-adjusted R:R. Apply native rounding, worst permitted zone entry, explicit costs/slippage and nearest relevant obstacles. Do not double count spread/slippage or invent optional targets.

For `NO_TRADE`, actionable entry/stop/target/R:R fields are null. Retain supported watch details separately. The full audit may contain competing candidates; a GC shorthand response displays only one selected setup or No trade.

## Parameter development and data restrictions

Inspect the available genuine data and existing approved native definitions. Propose defensible initial definitions for pivots, displacement, sweeps, retests, participation, freshness, expiry, costs and minimum economic suitability. Document units, instrument/session scope, rationale, examples/counterexamples, provenance and versions. Freeze them before out-of-sample performance evaluation.

Do not invent universal numeric thresholds, silently promote existing descriptive defaults into validated strategy settings, or optimize initial parameters for maximum backtest profit.

Required unresolved parameters produce `NO_TRADE: POLICY_NOT_READY`. Demonstrate functional BUY/SELL paths with clearly labelled engineering fixtures and test the actual evidence-to-event rules. Such fixtures are not genuine market performance evidence. A replay containing only readiness failures validates fail-closed behavior, not trading usefulness, early-entry value or arbitration performance.

Use existing authorized genuine native-futures archives/readers. Do not start live provider connections, purchase/download paid data, change subscriptions, develop a broker connection or substitute spot/perpetual/CFD data. If coverage is insufficient, implement the supported components and report the exact blocked validation requirements.

## Phase 3 — Validate and establish evidence

Run relevant unit, integration, genuine-data replay and isolation tests. Include at least:

1. A observed → armed → triggered → B confirmation: one opportunity, preserved timestamps, one first selection.
2. Triggered-but-unselected opportunities: later selection only if still eligible; no premature fill or consumed-selection bug.
3. Same price/direction but different structural episodes remain distinct; proven A/B/C equivalence survives restarts and archive repackaging.
4. A-only/B-only/C-only/unified state isolation and consistent opportunity-level comparisons.
5. Concurrent first selections, failed publication, process restart, repeated cycle, changed-input cycle conflict and stale-cycle rejection.
6. Immutable selected plans, original modeled/filled risk, classification updates and management-event chronology.
7. Pre-arm versus post-arm target touches; no target/stop look-ahead; ambiguous OHLC ordering and unsupported fills.
8. Captured versus reconstructed replay clocks, candle/pivot confirmation times, unknown gaps, no-print coverage, maintenance/DST, expiry and roll identity.
9. Missing versus neutral/mixed context, unknown aggressor volume, exact-window VWAP/profile, stale quotes, degraded data, costs and tick rounding.
10. Opposing directions, same-side dominance, ties, incomparable plans, final revalidation failure and no manufactured No-trade prices.
11. Direct/transitive forbidden-import checks in a clean process, zero broker/order/network delivery paths and unchanged production behavior.

Compare pathways, unified arbitration and the registered simple baseline on identical coverage, cost/fill assumptions and capital/exposure constraints. Use chronological out-of-sample/walk-forward evaluation only where sufficient genuine data exists. Freeze parameters and comparison rules beforehand; prevent overlapping label/event leakage and record all attempted variants.

Report sample size, coverage, eligible and selected opportunities, readiness/data exclusions, ambiguity/unresolved outcomes, abstention/conflict rates, net expectancy in R, win rate, profit factor, drawdown, costs/slippage sensitivity, exposure, entry latency/efficiency and MAE/MFE where supportable. Use unavailable values when a metric has no meaningful denominator.

Include early A failures that never receive B confirmation. Separate earlier recognition from an earlier obtainable fill. Do not describe retrospectively selected data as untouched out-of-sample evidence, historical replay as forward testing, or futures-reference results as verified broker performance.

## Phase 4 — Reviewable delivery

Deliver:

1. Specification v1.1, original-spec provenance and a seven-finding correction/test map.
2. Pinned-base architecture/dependency audit and files created/modified.
3. Working pathways, event/episode resolver, persistent store, lifecycle, eligibility/context rules, arbitrator and isolated opt-in shadow entrypoint.
4. Machine-readable configuration/schema versions, parameter rationales, data/replay manifests and deterministic identities.
5. Actual acceptance-test outcomes, isolation checks and reproducibility evidence, including failures and unresolved prerequisites.
6. Historical/out-of-sample findings where supportable; no invented trades, metrics, pass counts or profitability claims.
7. One complete unified output from genuine available data where possible, with a clearly labelled engineering fixture only if a genuine example is unavailable. A supported No trade is an acceptable example, not proof of strategy performance.
8. A reviewable diff/patch or implementation revision and concise instructions to reproduce the offline tests/replay without acquiring data or enabling execution.

Do not mark the whole task validated merely because the code always returns No trade. Report implementation completeness, behavioral validation, performance validation and forward-shadow evidence as distinct statuses.

## Non-negotiable boundaries

- Existing 20 analytical engines and prohibited strategy routes remain isolated.
- Existing production analysis/trading behavior, startup and routing remain unchanged.
- `mode = SHADOW` and `execution_eligible = false` for every output.
- No broker orders, executable broker approvals, live trading, deployment, merging, external messages or unapproved data acquisition.
- All displayed levels identify exact native contracts and **CME FUTURES REFERENCE PRICES**. No invented futures/CFD basis conversion or broker sizing.
- Never force BUY/SELL, fabricate evidence or claim unsupported profitability.

Final objective: three separately evaluated entry pathways, one canonical opportunity history per market episode, and one reproducible reference decision per instrument/stream/cycle, with an auditable explanation of selection or rejection.
