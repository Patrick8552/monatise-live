# Monatise unified trade decision system — implementation specification

Version: 1.1 · Prepared 4 November 2026 · Repository: `Patrick8552/monatise-live`

## 1. Objective and scope

Build an isolated, shadow-only native-futures decision layer. Three pathways evaluate the same causally available evidence separately, then a deterministic process returns one selected opportunity and one final decision per exact instrument and evaluation cycle: `BUY`, `SELL`, or `NO_TRADE`.

Prioritize reproducible, auditable decisions over parameter optimization. Earlier recognition and better trading performance are hypotheses to evaluate, not promised outcomes. Separately evaluated pathways are not statistically independent sources of confirmation.

Required processing branches:

`Validated evidence → Pathway observations → Provisional event/watch admission and episode resolution → Persistent opportunity tracking`

`Completed candidates → Full eligibility → Actionable deduplication → Context permissions → Deterministic arbitration → Final revalidation → Atomic decision/selection/outbox commit`

Observation admission validates causality and source identity but does not require a complete trigger or economic plan. Ambiguous episode links retain provisional identities and cannot publish BUY/SELL.

Use a common validated data snapshot before pathway evaluation. Run candidate eligibility checks before deduplication; run final current-state checks again after selection. A failed final check returns `NO_TRADE` for that cycle rather than silently promoting a previously rejected candidate.

Initial instrument scope is reviewed native CME/COMEX futures supported by the existing native-futures path, including standard GC and standard BTC where their exact native definitions validate. Do not infer support for other products from ticker similarity. Spot/perpetual crypto and broker CFDs are outside this implementation.

## 2. Repository inspection and architectural isolation

Inspect the repository, applicable `AGENTS.md` files, dependencies, data readers, risk controls, and test infrastructure before implementation. Record the actual starting branch and commit in an architecture note.

Reviewed reference: `codex/native-btc`, commit `1979440d8c25dda5d2b7d7c3a92ba5ede1a008d7`. The reviewed native-futures work and `main` differ. This reference is evidence of the reviewed implementation, not an instruction to assume it remains the newest branch. Verify the appropriate base and preserve unrelated work. Do not merge, deploy, or change production routing.

Do not integrate, modify, replace, call, or depend on the existing 20 analytical engines. Also exclude canonical crypto decision routes, broker Gold hierarchy, retired frozen H1 selectors/expiry rules, GIL qualification, and the XAUUSD signal router. Ordinary H1/H4 candles remain valid evidence.

Permit reuse of approved native-futures data validation, confirmed-swing calculations, Fibonacci, observed price references, executed VWAP/profile, aggressor flow, source models, persistence infrastructure, and engine-independent risk policy. Reuse must pass an explicit dependency audit. Define an allowlist of approved modules and a denylist of forbidden packages/routes.

Important repository finding: `monatise/engines/__init__.py` eagerly imports existing engines. Importing a child module may execute that initializer. Verify transitive runtime imports, not just explicit imports in new files. Do not modify that initializer merely to make this project pass isolation checks.

Suggested isolated components, with final locations chosen after inspection:

- Evidence snapshot adapter and causal event ledger.
- Parameter registry and definition functions.
- Pathway A, B, and C evaluators.
- Shared eligibility validator and context-permission policy.
- Opportunity identity registry and deduplicator.
- Deterministic arbitrator and final decision validator.
- Signal lifecycle/event store and report formatter.
- Offline replay and shadow outcome evaluator.

Preserve the existing analytical path. New decisions must identify their own policy, parameter, code, and schema versions. Do not relabel existing descriptive native observations as an already-qualified strategy signal.

## 3. Data contract and causal availability

Every evaluation receives one immutable snapshot with:

- Exact dataset, publisher/venue, instrument ID, raw symbol, product, expiry, currency, tick size, and multiplier.
- Evaluation cycle ID, UTC cutoff, observed-at/available-at timestamps, source hashes, archive positions, and replay state.
- Available completed candles, confirmed events, retained executions, and quotes, each with its own coverage and freshness record.
- Reviewed product-specific session/maintenance calendar, clock uncertainty, provider flags, gaps, degraded dates, and historical/live boundaries.

Do not join different contracts or expiries into one candidate. Do not silently use a continuous adjusted series for tradable price levels. Roll handling must end or invalidate the old contract's opportunity; a new contract receives a separate identity and fresh evidence.

Only use records available by the evaluation cutoff. A candle must have closed and become available; a swing becomes usable at its confirmation time, not its pivot time. All constituent evidence must pass source lineage and quality checks. Replay mode is explicit and frozen in the manifest. AS_RECORDED replay uses actual captured admission/availability, preserving gaps and latency. HISTORICAL_EVENT_TIME simulation uses genuine historical records and a declared publication/latency model, preserving original retrieval provenance and labelling reconstructed availability. These modes cannot be mixed silently or used to claim unobserved original live delivery. Confirmation and warm-up availability follow the chosen mode.

Timeframes need not close simultaneously. Use each timeframe's latest eligible completed candle and expose its age. Developing candles can appear in diagnostics, but cannot satisfy a closed-candle confirmation rule. Never fill unknown gaps with synthetic flat candles. Reviewed provider no-print intervals and scheduled closures remain explicitly distinct from missing data.

Freshness limits are feature-specific, instrument-specific, versioned policy parameters. An old H4 candle and an old entry quote are not equivalent. Revalidate the trigger, entry tolerance, target reach, structure, data quality, and reference price immediately before emitting an actionable research decision.

Executed volume is not automatically directional flow. Use available aggressor-side fields under documented native semantics; retain unknown-side volume separately. Establish how much unknown or missing flow invalidates directional confirmation through the parameter process below. L1 is not full depth, institutional identity, replenishment, or confirmed absorption.

Executed VWAP/profile must identify exact retained window boundaries and input coverage. Do not label a rolling window as a complete session. Session metrics require reviewed session anchors and sufficient verified retained coverage. Entitlement metadata alone does not establish connected feeds.

No live provider connection, paid data download, purchase, subscription change, or broker development is authorized by this specification. Use existing authorized archives/readers for implementation and testing. Report data acquisition gaps without substituting fabricated evidence or another market.

## 4. Definitions and parameter development

Do not invent universal thresholds for pivots, displacement, sweep size, rejection, retest duration, volume, or freshness. Also do not silently promote an existing descriptive default into a validated trading rule.

Before enabling candidate eligibility:

1. Inventory genuine available data, resolution, coverage, native terms, and limitations for each supported instrument and session.
2. Inspect existing native definitions and identify reusable calculations. For example, the reviewed swing implementation uses strict extrema, closed-bar confirmation, and a configurable radius. Its existing default is a documented research baseline, not proof of a profitable setting.
3. Propose explicit initial definitions and any required numeric parameters. Justify them using native price resolution, causal event semantics, observed data behavior, economic costs, and historical examples/counterexamples. Do not select them by maximum backtest profit.
4. Record the development data window, rationale, alternatives considered, necessary data resolution, and unsupported cases.
5. Validate behavior and boundary cases historically, then freeze a complete versioned configuration before out-of-sample performance evaluation.

Every required parameter has a name, value or explicit `UNRESOLVED` state, units, instrument/session scope, rationale, evidence references, version, and availability constraints. Required unresolved parameters produce `NO_TRADE: POLICY_NOT_READY`; diagnostic observations may still be produced. Do not silently skip the corresponding eligibility test.

Definitions must specify:

| Concept | Required deterministic definition |
| --- | --- |
| Confirmed pivot | Left/right observation requirements, strict/equal-price handling, outside-bar ambiguity, required continuity, and confirmation/availability time. |
| Structure | Rules for higher/lower swings, range/neutral, mixed/transition, confirmed directional break, and invalidation. |
| Structural break | Previously established reference ID, directional closed-price condition, applicable tick tolerance, and evidence timestamp. |
| Displacement | Measured price/body/range movement, causal preceding baseline, close location, and any volume requirement; comparison uses no future data. |
| Retest | Eligible previously broken reference, touch/zone rule, required later rejection/hold, ordering, deadline, and maximum adverse excursion. |
| Failed reclaim | Attempt to recover a previously lost reference, completed failure condition, confirming direction, and invalidation. |
| Sweep and rejection | Reference established before excursion, excursion rule, return/rejection rule, event ordering, and deadline; no inference of resting orders. |
| Volume support | Exact window, source, preceding baseline, directional statistic if available, minimum usable sample, unknown-side treatment, and pass/fail rule. |
| Targets and costs | Permitted observed references, visibility/confirmation time, tick rounding, cost/slippage model, and minimum net reward/risk. |

If the available data cannot determine the required intrabar ordering, mark the event ambiguous. Do not infer a favorable sweep, retest, or fill sequence from OHLC alone.

## 5. State definitions and directional bias

Timeframe evidence states are `UP`, `DOWN`, `NEUTRAL_RANGE`, `MIXED_TRANSITION`, or `UNAVAILABLE`. A confirmed break is a separately timestamped event. Map existing native observations into these states using documented rules; do not treat every mixed native state as neutral or automatically redefine it as a trend.

`UNAVAILABLE` never satisfies a neutral allowance. A mixed state requires an explicit pathway rule; it is not an automatic permission.

Market bias is separate from entry eligibility. Compute one `BULLISH`, `BEARISH`, or `NEUTRAL` context label using a versioned H4/H1 context decision table, and publish its evidence availability separately. `NEUTRAL` must not conceal missing evidence: include `bias_evidence_status` and the relevant reason code. This context label does not vote for a candidate or authorize an order.

## 6. Three entry pathways

Each evaluator independently returns a typed candidate or `NO_TRADE`, with evidence and rejection codes. The shared validator and arbitrator may still reject a pathway candidate. Models share the same approved evidence calculations; they must not count repeated evidence as additional confirmation.

BUY and SELL rules must be explicitly specified and mirrored where economically appropriate. Any intentional asymmetry must be documented and tested.

### Model A — early continuation

- Require a defined H1 directional structure or a qualifying completed H1 structural-break event under a frozen transition rule. A mixed H1 label alone is insufficient.
- Use H4 context permissions. For the initial policy, a confirmed opposing H4 trend vetoes A; a fully observed neutral/transitioning H4 requires an explicit permission rule. Missing required H4 evidence vetoes eligibility.
- Require completed M5 displacement and breakout/retest or failed-reclaim confirmation in the candidate direction, with required executed-volume support.
- M15 may be aligned or genuinely neutral; a confirmed opposing M15 structure/reversal vetoes A. A mixed M15 requires an explicit permission rule, not a neutral shortcut.
- Do not require Model B qualification or full M15 directional alignment. Earlier means less higher-timeframe agreement, not an unfinished M5 trigger.
- The candidate must still have a current, defensible entry, structural stop, target, and cost-adjusted risk/reward.

### Model B — confirmed continuation

- Require confirmed H1/M15/M5 directional agreement under the frozen structure rules.
- Require the specified completed breakout/displacement/retest sequence and executed-volume support.
- Apply the same H4 opposition veto and explicit neutral/transition permissions as A in the initial policy.
- Detect overlap with A through the opportunity registry. B can add confirmation to an existing A opportunity; it does not create a second independent trade or automatically supersede its original decision.

### Model C — liquidity-reference reversal

- Identify a sweep of an established, causally available high/low reference.
- Require completed rejection, displacement, an identified M5 structural reversal, and a later completed retest or failed reclaim. Record the protected reversal extreme and all ordering evidence.
- For the initial policy, C may reverse a local M5 move when H1/H4 support the candidate direction or satisfy explicit neutral-context permissions. It may not fade a confirmed opposing H1 or H4 trend merely because a local sweep occurred.
- A future higher-timeframe countertrend variant requires a separate named, versioned, historically validated permission policy; it is not a hidden exception in v1.
- Define M15 opposition rules explicitly; a confirmed opposing M15 reversal vetoes the initial C policy. Missing required context vetoes eligibility.
- Require supported participation evidence and defensible structural risk. Never infer a reversal from the excursion alone.

## 7. Eligibility and context permissions

Candidate eligibility requires validated identity/data, resolved policy parameters, causal event order, completed required structure, required participation evidence, valid lifecycle, defensible price geometry, and a cost-adjusted economic plan. A required feature that is missing or degraded beyond its policy allowance fails eligibility.

Entry/stop/target geometry must respect native ticks. A BUY has stop below entry and target(s) above entry; a SELL reverses this ordering. Invalidation must reference an actual structural event or level, with a justified buffer. A tighter stop chosen only to improve R:R is invalid.

Entry zones are evaluated using the least favorable permitted entry and conservative costs. Reject a missed entry, a target passed during the registered post-arm missed-opportunity window, invalidated structure, unsuitable current spread/cost, expired trigger, or stale quote. Target-ahead geometry at selection is separate from prior touches that established a swing reference; those historical touches are not post-arm target hits. Post-entry target hits belong to shadow-position outcomes. Price tolerance and deadlines must be explicit policy parameters.

After eligibility and deduplication, apply an executable context-permission matrix covering pathway, side, H4/H1/M15 states, session phase, maintenance, scheduled major US news, and any existing shadow position/opportunity restrictions. The matrix must return `ALLOW`, `REJECT`, or `UNRESOLVED`; unresolved means ineligible. An alignment summary by itself is not this matrix.

News-event exclusions and timing are policy parameters, with versioned calendar data available as of the replay cutoff. No automatic universal blackout duration. Missing calendar coverage must be exposed and handled according to an explicit prerequisite rule, not interpreted as “no news.”

## 8. Persistent opportunity identity and deduplication

Create a shared causal event ledger independent of A/B/C. Events have stable reference IDs, original/confirmation/availability timestamps, parent-event links, instrument identity, and source provenance. Candidate classifications attach to these common events.

Define each opportunity around the exact contract, direction, canonical originating structural episode, and reset epoch. The origin is the underlying event episode, not the model name, current evaluation cycle, mutable entry quote, or latest source hash. Define a shared deterministic resolver, canonical serialization and identity schema. Link model-local events to their causally established parent break/reversal episode and protected references. A reset requires evidence of a new structural episode; packaging or quote changes are not resets. Provisional pre-break observations are retained until a canonical origin exists.

Do not deduplicate merely because prices are close or direction matches. Publish exact equivalence rules for associating a later confirmation with an existing parent episode. Ambiguous equivalence blocks a new actionable publication with `OPPORTUNITY_IDENTITY_AMBIGUOUS` until deterministically resolved; it must not create a probable duplicate.

Persist:

- Stable `opportunity_id`, creation time, canonical origin/reference IDs, exact contract and side.
- Pathway classifications and when each first qualified or ceased qualifying.
- Initial and subsequent evidence revisions, trigger/status events, and policy versions.
- Selected representative candidate, selection history, rejection reasons, and any shadow outcome linkage.

Example: A recognizes a bearish opportunity at 10:00 and B confirms the same episode at 10:15. Update its classifications to `[A, B]` under the same ID. Preserve the original detection and any original trigger/fill; do not backdate B, restart the trade, or count two trades.

A new opportunity requires a demonstrably new episode/reset under the registered rules. Revisiting the same price alone is not a reset. Contract roll, opposite direction, or a genuinely new post-invalidation structural episode cannot inherit the old identity.

Deduplicate evidence as well as candidates. Multiple labels are not extra votes, multiplied volume, or higher confidence. A superseding plan for the same episode is an auditable revision, not an extra opportunity. A policy-version change does not silently reissue the opportunity as a new trade. Canonical market identity is shared, but lifecycle, selections, outbox, positions and outcomes are namespaced by an immutable experiment/decision stream with frozen configuration and replay-manifest hashes. A-only, B-only, C-only and unified experiments cannot share mutable state or consume each other's selections. A changed frozen configuration requires an explicitly new experiment; it cannot mutate an existing stream.

## 9. Deterministic arbitration — initial policy

Arbitrate opportunities, not raw model votes. Only current, triggered, eligible, context-permitted opportunities compete for a BUY/SELL decision. Watching/armed plans cannot outrank a qualifying triggered opportunity.

The initial rule is deliberately conservative and must be tested for its abstention rate:

1. No eligible triggered opportunity → `NO_TRADE` with reason codes and reconsideration conditions.
2. One eligible triggered opportunity → select it, subject to final revalidation.
3. Both BUY and SELL opportunities survive → `NO_TRADE: OPPOSING_ELIGIBLE_OPPORTUNITIES`. Do not use majority voting, model labels, or invented probabilities. A genuinely invalidated/superseded candidate should already have been removed by its explicit rules.
4. Several distinct same-side opportunities survive → compare only those with compatible context-permission categories and the same defined cost/evaluation basis. Rank using dominance across conservative net R:R to the nearest defensible target (higher is better), modeled round-trip cost divided by initial risk (lower), and trigger-to-current-entry lateness (lower, under its explicit comparable definition). Every candidate must already satisfy the structural-quality gates.
5. Select a unique opportunity only if it is no worse than every alternative on every defined comparable dimension and better on at least one for each alternative. If no unique dominator exists, or required comparison dimensions are unavailable/incomparable, return `NO_TRADE: NO_UNIQUE_DOMINANT_OPPORTUNITY`.

No weighted confidence score, automatic preference for B, or selection by a distant TP3. Do not break an economic/structural tie with random choice or an opportunity ID. Native tick/cost precision and any equality tolerances belong to the frozen comparison policy.

This dominance policy is a transparent initial research choice, not a claim of optimal selection. Alternative ranking policies must be separately versioned, evaluated against the baseline, and frozen before out-of-sample comparison. Do not tune the arbitrator after seeing individual outcomes.

If one opportunity has several valid same-episode plan revisions, apply the same plan-validity and comparison rules inside that opportunity. Multiple labels with an identical plan require no ranking. If materially different valid plans remain incomparable, withhold action rather than choose a favorable stop arbitrarily.

## 10. Lifecycle, action semantics, and final output

Signal states: `WATCHING`, `ARMED`, `TRIGGERED`, `INVALIDATED`, `EXPIRED`, `SUPERSEDED`. Define and test allowed transitions and their evidence. Missing data can suspend current eligibility without falsely asserting structural invalidation; record that separately from lifecycle.

`opportunity_direction` is BUY/SELL. `trade_action` is BUY/SELL only when a selected opportunity is `TRIGGERED` and passes all current gates. Otherwise `trade_action = NO_TRADE`. Thus an “armed SELL” has SELL direction, ARMED status, and NO_TRADE action. None of these states authorizes execution in this implementation.

Keep distinct opportunity, market-trigger, first-selection, cycle-decision and publication/outbox identities. A market trigger is recorded even when arbitration selects nothing; it does not consume selection. A later still-valid first selection records its own timestamp and `is_new_selection = true`. Repeated reports or later classifications retain the original selection and use `is_new_selection = false`. No simulated fill precedes selection.

Atomically commit the cycle decision, immutable selected plan, selection claim, lifecycle changes and local outbox record using transactions, uniqueness constraints and stream revision/cutoff checks. An identical cycle/input returns the stored decision; changed input for the same cycle conflicts. Older cutoffs cannot overwrite newer state. Publication delivery is outside the database transaction and uses idempotent outbox acknowledgement; do not claim exactly-once network delivery or create a network delivery path for this shadow task.

Invalidated, expired, and superseded versions cannot resurrect. A triggered opportunity cannot return to armed to manufacture another entry. Define signal expiry separately from an open shadow position's management: an entry permission expiring does not itself close a position. Store position/outcome state separately.

Expiry must use explicit new opportunity rules and relevant invalidating events/session/deadline conditions. Do not restore the retired frozen H1 selector or its fixed lifetime. Price invalidation, target reach, source failure, and opportunity supersession may revoke eligibility before a deadline.

Final decision schema:

| Field | Requirement |
| --- | --- |
| Identity | Exact native contract, expiry, venue, price unit; `CME FUTURES REFERENCE PRICES`. |
| Decision identity | Cycle ID, decision ID, opportunity ID if selected, plan revision, policy/config/code versions. |
| Market bias | BULLISH/BEARISH/NEUTRAL, evidence status, context rationale. |
| Trade action | BUY/SELL/NO_TRADE under the semantics above. |
| Signal status | Lifecycle state of the selected/previously tracked opportunity; null if none exists. |
| Pathway | Primary A/B/C classification if selected, plus all supporting classifications; no claim of independent confirmations. |
| Entry | Exact completed trigger and permitted current entry/zone for an actionable reference plan. |
| Stop/invalidation | Native structural stop plus non-price invalidation conditions. |
| Targets | One to three defensible observed targets with source references; unused fields null. |
| R:R | Conservative cost-adjusted reward/risk for each target, assumptions, and any planned exit allocations. |
| Timing | Snapshot, source observations, trigger/detection/availability times, deadline and invalidating events. |
| Evidence | Passed gates, causal event/reference IDs, input hashes, coverage and freshness. |
| Arbitration | Selected policy, comparisons, and why other candidates were rejected/deduplicated/withheld. |
| Safety | `mode = SHADOW`, `execution_eligible = false`, no broker order intent. |

For `NO_TRADE`, published actionable entry/stop/target/R:R fields are null. State the actual reason and reconsideration condition. Keep genuinely observed conditional plans in a separate internal watch record; do not fabricate prices or present them as a second final trade. If necessary, link the watch record without publishing an actionable plan. `selected_opportunity_id` is null when no unique opportunity is selected; conflicting alternatives remain in the audit record.

The primary pathway is provenance, not a vote or preferred engine. Before selection retain classification/plan revisions. At selection freeze the owning pathway, intended entry method/zone, stop, targets, modeled initial risk, costs, management, supporting evidence and versions. Later confirmations append observations and do not rewrite that plan. Subsequent simulated fills and actual initial fill risk are separate immutable events; realized-R reports state their denominator. Management follows the frozen policy and cannot retrospectively improve initial risk or outcomes.

The full decision/audit record contains competing-candidate reasons. For GC shorthand responses, display only the single selected setup or No trade, actual timestamps, and material limitations; do not list competing bullish/bearish scenarios.

## 11. Risk, targets, and execution boundary

Preserve existing kill switches, execution permissions, approval requirements, capital limits, and account safeguards. Reuse engine-independent controls through audited adapters; do not copy only a per-trade limit while losing portfolio/drawdown/open-risk constraints. If necessary account evidence is unavailable, report account-risk validation unavailable and keep reference research separate from account sizing.

No live trading, order placement, production execution wiring, automatic approval, broker connection development, or deployment. The absence of a broker feed must not block explicitly requested futures-reference research, but it always blocks claims of broker-ready prices, broker sizing, or executable approval.

Support one to three observed targets. Do not invent TP2/TP3, stretch targets to pass a gate, or treat Fibonacci ratios as guaranteed targets. Missing optional targets remain null; missing a defensible required objective fails eligibility.

Use an explicit reference cost model appropriate to the futures instrument, with sourced inputs or clearly documented research assumptions. Do not use zero costs silently or claim futures assumptions are broker CFD costs. If required cost inputs cannot be supported, expose gross diagnostics and withhold cost-qualified action.

Let `d` be +1 for BUY and −1 for SELL; `E` the modeled fill, `S` the modeled stop fill, `T_i` each modeled target fill, and `M` the contract multiplier. Calculate positive initial risk as `d × (E − S) × M + entry/stop fees`; calculate target reward as `d × (T_i − E) × M − entry/target fees`; net R:R is reward divided by initial risk. Model spread/slippage in the fills or as explicit additional costs, never both. Apply native rounding before these calculations.

Minimum net R:R, cost allowances, entry tolerance, and stop buffers are registered parameters with documented initial rationale, not universally invented constants. Evaluate the nearest relevant observed obstacle before accepting a farther objective.

For partial exits, register allocations summing to one, exit priority, stop management, and trailing/breakeven behavior before replay. Report realized net R against original risk. A weighted planned payout is not expected profit without validated outcome probabilities.

## 12. Historical replay, shadow evaluation, and acceptance

No invented backtests, pass counts, performance statistics, or claims of future live results. If genuine coverage is insufficient, deliver working deterministic components, limitation/reason reports, and pending validation status. Keep required unresolved configurations ineligible.

Required test matrix:

- Causal pivots, publication delay, future bars, equal/ambiguous extrema, outside bars, gaps, no-print proofs, maintenance, DST, expiry and roll identity.
- Exact mirrored BUY/SELL event sequences; structural invalidation; incomplete displacement/retest; unavailable versus neutral/mixed context; Model A qualifying without B.
- Adversarial sweep-without-rejection, rejection-without-displacement, intrabar ordering ambiguity, and unconfirmed reversal cases.
- Required/unknown/missing aggressor flow, exact VWAP/profile boundaries, no session-label leakage, stale quote, and degraded input propagation.
- Eligibility-before-ranking; all vetoes; opposing candidates; unique same-side dominance; ties and incomparable candidates; no random/majority decision.
- A→B same-opportunity updates before and after trigger, overlapping C classifications when a proven common episode exists, distinct episodes at the same price, contract changes, ambiguous identity, restart/concurrency/idempotency, and terminal-state non-resurrection.
- Watching/armed plans never emit BUY/SELL; repeated triggered status never emits a second trigger; no manufactured levels on No trade; invalid final revalidation fails closed.
- Rounding, worst permitted zone fill, spread/fees/slippage without double counting, invalid stop geometry, missing targets, partial exits, target already reached, and adverse fills.
- Forbidden direct/transitive imports, zero broker write calls, preserved production behavior, and deterministic replay hashes.

Historical simulation must process records in causal availability order. A newly confirmed signal cannot fill earlier in its confirming bar. A limit touch alone is not proof of an obtainable fill; document the fill model. If OHLC cannot resolve stop/target ordering, use suitable genuine finer data or report unresolved/bounded outcomes. Never silently select the winning sequence.

Develop definitions on a declared development window. Freeze the complete pathway/arbitration configuration before chronological out-of-sample or walk-forward evaluation. Prevent overlapping event/label leakage across folds. Record all attempted policy/parameter variants; repeated holdout inspection is not untouched validation.

Evaluate each pathway separately, a simple registered baseline, and the unified arbitrator on identical data, costs, calendars, fill models, account/exposure limits, and opportunity definitions. Deduplicate trades consistently and enforce realistic capital constraints. Compare:

- Sample size, calendar coverage, missing/unresolved outcomes, participation/exposure, and No trade/conflict rates.
- Win rate, net expectancy in R, profit factor, drawdown, costs/slippage sensitivity, and realized target/stop outcomes.
- Entry latency, entry efficiency, MAE/MFE, false-breakout frequency under a registered definition, and opportunity-level missed/selected outcomes.
- Out-of-sample behavior by instrument, pathway, session, and regime, with uncertainty appropriate to the sample.

For early recognition, compare A and later B within the same opportunity: detection time, trigger time, realistically available fill, adverse/favorable excursion and net outcome under predeclared management. Include A failures that never obtain B confirmation; do not select only successful A→B upgrades. Report early recognition without an earlier valid fill separately from actual entry improvement.

Use a frozen replay manifest so identical source/config/code versions reproduce the same decisions and trigger IDs. Forward shadow evaluation starts only from available authorized inputs and records actual subsequent observations; historical replay is not forward testing. Report pending results honestly. Performance under futures-reference assumptions does not establish FTMO/Equity Edge executable performance.

## 13. Implementation milestones and deliverables

1. Repository/dependency audit, approved scope, data coverage inventory, and architecture note.
2. Causal evidence/event models, parameter registry, explicit definition tables, and deterministic behavior tests.
3. Three modular pathways, shared eligibility/context policies, persistent opportunity identity and lifecycle.
4. Deterministic arbitrator, one-decision formatter, rejection audit, and import/execution isolation checks.
5. Genuine historical replay with frozen configuration; out-of-sample comparisons and coverage limitations where supportable.
6. Shadow-only integration through an isolated opt-in research entrypoint. No production routing, deployment, or trade activation.

Deliver code/architecture summary, machine-readable policies and schemas, parameter rationale and provenance, pathway/context/arbitration decision tables, opportunity identity specification, sample decision/audit records, replay manifests, tests actually passed/failed, actual historical/forward results where available, unresolved limitations, and recommendations clearly separated from implemented behavior.

Success means identical evidence and configuration produce identical decisions, one underlying opportunity persists across pathway upgrades and cycles, every actionable reference plan has defensible current evidence/risk, and no unsupported or unauthorized execution is possible. Improved profitability is a later empirical finding, not an implementation acceptance shortcut.

## 14. Correction traceability

| Accepted correction | Specification coverage |
| --- | --- |
| A/B overlap and meaning of early entry | Sections 6, 8, 9; A can qualify without B; common-episode classifications do not multiply signals. |
| Explicit trading definitions and unavailable/neutral distinction | Sections 3–5 and causal/ambiguity tests in section 12. |
| Higher-timeframe and reversal permissions | Sections 6–7, with explicit v1 opposition rules and separately versioned countertrend variants. |
| Eligibility-first deterministic arbitration | Sections 1, 7, 9–10 and tie/conflict/final-revalidation tests. |
| One to three targets, structural risk and net R:R | Sections 7, 10–12, including costs, rounding and exit management. |
| Data quality, timing, futures/broker separation | Sections 2–3, 7, 10–12. |
| Signal lifecycle, branch/dependency isolation | Sections 2, 8, 10–12. |
| Seven logic-audit corrections | Sections 1, 3, 7, 8 and 10 replace conflicting v1.0 clauses; implementation acceptance mapping is in docs/unified/acceptance.md. |
| Arbitration as its own strategy; unbiased testing | Section 12 and versioned policy/parameter requirements throughout. |
| Persistent opportunity identifier | Sections 8, 10, 12; A→B updates never create a second trade. |
| No arbitrary threshold invention | Section 4; unresolved prerequisites fail eligibility; development is separated from profitability optimization. |

## Reviewed repository references

- [Native-futures scope instructions](https://github.com/Patrick8552/monatise-live/blob/1979440d8c25dda5d2b7d7c3a92ba5ede1a008d7/AGENTS.md)
- [Native futures observations, data semantics and research boundary](https://github.com/Patrick8552/monatise-live/blob/1979440d8c25dda5d2b7d7c3a92ba5ede1a008d7/docs/native-futures-chart-access.md)
- [Native BTC product and calendar scope](https://github.com/Patrick8552/monatise-live/blob/1979440d8c25dda5d2b7d7c3a92ba5ede1a008d7/docs/native-bitcoin-futures.md)
- [Existing engines package initializer](https://github.com/Patrick8552/monatise-live/blob/1979440d8c25dda5d2b7d7c3a92ba5ede1a008d7/monatise/engines/__init__.py)

This document specifies new research functionality. It does not claim that these pathways, arbitration rules, or validation results already exist in the reviewed repository.
