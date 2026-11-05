# Requirement and acceptance mapping

The authoritative v1.1 specification and preserved v1.0 hash are in `requirements-manifest.json`. Tests are under `tests/research/unified`. Engineering fixtures are expressly synthetic and are never market-performance evidence. Genuine integration tests require `MONATISE_UNIFIED_MANIFEST_ROOT`; no test acquires data.

| Audit finding | Implementation | Acceptance evidence |
| --- | --- | --- |
| Conditional observation tracking | Causal observations and provisional sweeps persist before actionable eligibility | `test_conditional_records_persist_without_action`, `test_provisional_sweep_needs_no_completed_economic_plan` |
| Trigger versus selection/publication | Independent event/opportunity/selection/cycle/outbox IDs, later first-selection semantics | Trigger dedup/retry tests; opposite candidates do not select; no position event before selection; one outbox after concurrent first selection |
| Exact episode equivalence | Shared canonical break resolver; proven later C reversal parent; separate events at same price/contract | Raw-price A/B/C BUY/SELL cases, same-level distinct episode/roll tests, evidence deduplication |
| Experiment isolation | Frozen stream config/source/code; separate lifecycle/selection/position/outcome tables | `test_experiment_state_isolation_and_frozen_configuration`, shared-evidence cache isolation |
| Replay clocks | Captured admission versus declared historical event time; no modeled quote in as-recorded mode | Genuine `test_archive_retrieval_and_event_time_are_distinct`, clock-mode rejection, publication-cutoff and future-record tests |
| Immutable plan and target windows | DB immutable-selection triggers, fixed source/cost/risk snapshot, append-only fills/outcomes | A→B update, selected-plan SQL update rejection, pre-arm/post-arm target test, exact costs, ambiguous OHLC outcome |
| Atomic/monotonic persistence | WAL/FULL, one transaction, unique cycle/selection/outbox constraints, timestamp cursor | Concurrent workers, whole-cycle crash rollback, changed-input/stale-cycle tests, standalone lifecycle timestamp and rollback regressions |

Additional acceptance covers neutral versus missing/mixed evidence, A without B, C opposition veto, robust unknown aggressors, observed nearest target and net costs, final entry/context revalidation, spread widening, stop-breach recovery, final selection timestamp, completed-opportunity non-reentry, alternate baseline ties, deterministic decimal precision, archive hashes/counts/replay controls, clean-process import isolation and no provider client construction.

Original native-futures regression tests remain unchanged and are run separately from the new tests, including localhost-only chart tests. They do not connect to a market feed.

Performance acceptance is separate: zero eligible/resolved genuine opportunities gives unavailable return metrics, not zero-risk profitability or proof of a useful strategy. The available source period was previously inspected; its chronological holdout cannot be called untouched out-of-sample. Forward testing is not performed without new authorized future data.
