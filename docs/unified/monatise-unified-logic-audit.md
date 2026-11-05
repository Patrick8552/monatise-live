# Monatise unified decision specification — logic audit before implementation

Reviewed: `monatise-unified-trade-decision-implementation-spec.md`, version 1.0.

Verdict: the overall architecture is coherent. The written specification still has important state, identity, and replay ambiguities that should be resolved before implementation. These are specification findings, not failures observed in an implemented strategy. No trading implementation was written for this audit; the prepared worktree remains pinned to `1979440d8c25dda5d2b7d7c3a92ba5ede1a008d7` with no code changes.

## What is logically consistent

- Three separately evaluated pathways can feed one decision without becoming three independent confirmations.
- Model A can qualify without Model B. Completed M5 confirmation does not logically require completed M15 alignment.
- Bias can be bullish/bearish while action is No trade. An armed direction is not a triggered action.
- Eligibility before ranking, conflict abstention, same-side dominance, and a final fail-closed check are deterministic.
- One underlying opportunity can retain its identity as classifications change.
- One to three observed targets, structural invalidation, cost-adjusted R:R, and shadow-only futures reference outputs are compatible.
- Unresolved parameters can correctly prevent action. This is a configuration/readiness outcome, not evidence of a profitable or useful strategy.

## Required clarifications

### 1. Give conditional opportunities a defined path into persistence

Relevant requirements: sections 1, 7, 8 and 10.

Problem: pathway candidates pass eligibility before deduplication/tracking, and eligibility requires completed structure, participation evidence and a complete economic plan. The specification does not separately say how incomplete WATCHING/ARMED observations become persisted opportunities. If the action gate is applied to everything, early observations are discarded until trigger completion, losing detection history and undermining the A→B entry-efficiency study.

Correction: distinguish observation admission from action eligibility. Admit valid causal partial observations into a provisional event/watch ledger. Attach a durable opportunity ID once its canonical episode is identifiable. Ambiguous observations retain provisional IDs and cannot publish action. Deduplicate watch observations before writing redundant records. Only completed triggered candidates pass the full action gate and enter actionable arbitration. This watch branch does not bypass any eligibility requirement for BUY/SELL.

Acceptance example: A detects an incomplete setup at t0, becomes armed at t1, triggers at t2, and B confirms at t3. One opportunity retains all four timestamps; only an eligible selection after t2 can emit a trade signal.

### 2. Separate market trigger, selection, and publication

Relevant requirements: sections 9–10.

Problem: an opportunity can satisfy its market trigger but lose arbitration. The current wording uses an immutable trigger event both for market confirmation and prevention of duplicate trade emissions. These are different facts. Conflating them can make a later first selection appear already consumed, or can permit repeated selections to create repeated trades.

Correction: retain three identities: `market_trigger_event_id`, `selection_event_id`, and an idempotent publication/outbox event ID. A market trigger is recorded independently of arbitration. `is_new_selection` becomes true only on the first eligible selection within an experiment/decision stream, then remains false on repeat delivery. A later A/B classification update does not create another selection. No simulated fill can precede selection, even if the market trigger occurred earlier.

Acceptance example: two opposing opportunities trigger at t0 and arbitration returns No trade. At t1 one has been invalidated by actual evidence. The other may be selected only if still fresh and otherwise eligible, with its original trigger timestamp and a new first-selection timestamp. Staleness or a missed entry still vetoes it.

### 3. Make episode equivalence and reset conditions an executable contract

Relevant requirements: section 8.

Problem: “canonical originating structural episode” and “reset epoch” express the right intention but do not yet define equivalence. A can reference an H1 break and B a later M5 retest, so hashing each pathway's local trigger would create different IDs. Hashing only side and price would wrongly merge unrelated opportunities.

Correction: define a common episode resolver before pathway-specific identity decisions. It must link model-local events to one causally established parent episode, record the structural references that protect it, and define exactly what evidence creates a new episode after invalidation/expiry. Define stable serialization, identity schema version and reset rules. Keep source archive hashes as provenance rather than using a changing capture hash as the opportunity identity. Unprovable relationships remain ambiguous and ineligible; do not merge by price proximity.

Acceptance examples: an A→B upgrade keeps one ID; two unrelated breaks of the same level receive different IDs; moving a quote or changing archive packaging does not create another opportunity; a contract roll always changes instrument identity.

### 4. Separate market identity from experiment and persistence namespaces

Relevant requirements: sections 8, 10 and 12.

Problem: the specification requires stable opportunity IDs across policy changes and also asks for A-only, B-only, C-only and unified comparisons. If all runs share the same consumed-trigger/lifecycle records, one experiment can prevent another from selecting the same market opportunity. This contaminates the comparison.

Correction: preserve one canonical market `opportunity_id`, but namespace mutable lifecycle, selection, shadow positions and outcomes by an immutable `experiment_id`/decision stream. Include the frozen configuration hash and replay manifest in that namespace. Keep production-style duplicate protection scoped to one stream, including across policy updates within that stream. A policy update may add a new experimental stream, but must not silently reissue an already consumed opportunity in an existing stream.

Acceptance example: A-only and B-only can independently simulate the same opportunity for comparison, while repeated A-only evaluations cannot create a second trade. Experiment state never leaks into another experiment or into production.

### 5. Distinguish as-recorded replay from reconstructed historical research

Relevant requirements: sections 3 and 12.

Problem: “available at the time” can refer to exchange/provider observation time, local capture admission, historical archive retrieval, or later strategy processing. An archive downloaded in November cannot prove what the application received in October. Conversely, using November retrieval as the eligibility time for every October bar makes an October replay empty rather than informative.

Correction: define two explicitly labelled modes:

- **As-recorded replay:** respect actual captured availability/admission times, gaps and delivery latency. Claim only the coverage present in that capture.
- **Historical event-time simulation:** use genuine historical records with a documented modeled publication/latency rule. Preserve original retrieval provenance and label application availability as reconstructed, not observed. Do not reuse this mode as evidence of original live delivery.

Do not combine the two modes silently. Freeze the chosen semantics in each manifest, including candle and pivot confirmation availability. If latency/ordering cannot be supported, withhold affected outcomes or report bounds.

Acceptance example: downloading an old bar today does not rewrite its recorded retrieval time. An event-time simulation may still use its earlier market event under declared assumptions, but its result cannot be described as a proven original live signal.

### 6. Freeze selected plans and define target-reach windows

Relevant requirements: sections 7–8 and 10–12.

Problem: plan revisions and primary-pathway changes are allowed, while the entry-efficiency comparison depends on preserving the original decision. The specification does not explicitly freeze the selected entry, initial risk, targets, management, costs and ownership at selection. It also says to reject an “already-reached target” without defining the relevant observation window. Every prior swing-high target was historically touched when that swing was formed; that alone cannot invalidate it.

Correction: freeze an immutable selected-plan snapshot and its initial-R denominator when selection occurs. Later classifications are annotations; historical selection/trigger ownership and simulated fills remain unchanged. Subsequent management requires separately timestamped events under the frozen management policy, never rewriting initial risk or outcomes.

Define target-ahead geometry at selection separately from an explicit missed-opportunity rule covering the period after plan arming. A historical touch that established a resistance/support reference is not automatically a post-arm target hit. After entry, target hits belong to outcome/position management. Ambiguous event ordering remains unresolved.

Acceptance examples: B confirmation cannot improve an earlier A entry or tighten its historical stop. A swing high may be used as an ahead-of-entry target despite having been touched before arming. A target already passed after arming triggers the configured missed-opportunity rule rather than a retrospective favorable fill.

### 7. Define atomic decision commits and monotonic evaluation rules

Relevant requirements: sections 1 and 10.

Problem: persistent IDs and idempotency are necessary but do not specify the transaction boundary. Two workers can both observe “not yet selected” and each publish. An older evaluation arriving late can also overwrite newer lifecycle state.

Correction: atomically persist the cycle decision, selected-plan snapshot, selection claim, lifecycle update and publication outbox event, with unique constraints for cycle/input identity and opportunity selection in its stream. Check the expected stream revision/cutoff when committing. Repeating a cycle with identical inputs returns the stored decision; reusing a cycle ID with different inputs is a conflict. Older cutoffs cannot move state backwards. Use deterministic timestamp/event tie ordering.

Acceptance examples: concurrent first selections produce one selection/outbox event; retry after a publication failure does not create another trade; a late older cycle cannot resurrect an invalidated opportunity; replaying identical inputs produces the same decision content and identities.

## Policy choices to retain explicitly, rather than treat as bugs

1. Model C v1 is a **local reversal with permitted higher-timeframe context**. It is not a general H1/H4 countertrend system. This restriction is coherent, but its name/documentation must not imply broader capability.
2. Pareto dominance deliberately abstains when distinct same-side opportunities cannot be ranked unambiguously. Measure that abstention rate; do not secretly introduce a weighted score to reduce No trade counts.
3. A failed final revalidation returns No trade rather than selecting a runner-up in the same cycle. This is conservative and internally consistent.
4. Required unresolved parameters produce `POLICY_NOT_READY`. A replay consisting only of that reason verifies fail-closed behavior; it does not validate pathway performance, early-entry value, or arbitration quality. Performance metrics must remain unavailable until there is a meaningful eligible sample.

## Recommended clarified flow

`Validated causal evidence → pathway observations → provisional watch admission/event resolution → persistent opportunity tracking`

`Completed pathway candidates → full eligibility → actionable deduplication → context permissions → deterministic arbitration → final revalidation → atomic selection/decision/outbox commit`

The watch branch and actionable branch share event/opportunity identity. Only the actionable branch can produce BUY/SELL. Both remain shadow-only native-futures research.

## Audit status

The architecture can proceed after these state/identity/replay contracts are incorporated into the authoritative specification. Numerical trading parameters still require the separate data-definition and historical-behavior work already required by that specification. This audit does not certify a profitable strategy and does not authorize additional data acquisition or execution.
