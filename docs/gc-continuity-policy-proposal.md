# Proposed GC data-policy amendment — not activated

**Proposal ID:** `gc-native-sparse-interval-policy-proposal-v1`.
**Status:** NOT APPROVED, NOT IMPLEMENTED, NOT ACTIVE.

Phase 3A's additional admission contract rejects a source window whenever any
expected full-session bar is absent. Its UTC aggregation also requires every child
minute. This is more conservative than the vendor's sparse OHLCV representation,
but it is explicit policy rather than an accidental 200-bar indicator period.

The canonical regime needs 51 H4 bars for 50 returns, not 200. This does not make
shortening the supplied prefix harmless: liquidity, pivots, zones, anchor selection
and target production inspect other portions of the supplied history. No arbitrary
50/100-bar replacement or context-lifetime extension is proposed here.

Two source-policy study arms could be reviewed separately:

1. **Authentic native higher-timeframe observations.** Acquire only independently
   justified exact native `ohlcv-1h` scopes, preserve their separate hashes and
   vendor clocks, and reconcile them against available minutes/complete trade
   evidence. An actual published H1 observation can exist despite a zero-trade
   child minute. H4 may be derived from four validated native hours, while retaining
   the UTC grid. Admission/lineage rules would explicitly recognize this additional
   source rather than pretending every H1 came from 60 observed minute records.
2. **Complete-trade sparse aggregation.** After an independently reviewed complete
   trade scope establishes each empty child, derive a higher-timeframe bar from
   all qualifying executions in the interval. Empty child minutes would remain
   no-trade observations without price candles. Open/close come from the first/last
   actual execution; high/low from actual executions; volume sums actual quantities
   with verified native multiplicity. No previous price is carried forward.

Either arm needs a reviewed source interface, correction/condition conventions,
equivalence or explicit difference reports, deterministic fixtures, and a full
unchanged-window comparison before approval. A no-trade minute by itself does not
resolve the canonical M1/M5/M15 history semantics; those roles require their own
explicit admission review. Neither arm can waive quote freshness, Gold chronology,
native identity, tick units, structural stops, nearest targets, minimum RR or expiry.

Required approval must name the exact versioned data-policy arm, eligible source
evidence, retrospective assumptions and allowable admission differences. Acquisition
approval additionally needs reliable exact-scope estimates and a concrete bounded
credit-only budget, with residual uncapped billing exposure acknowledged. General
credit permission does not approve either policy amendment or a trading policy.

Current code retains the strict 200-bar continuity and full-child policy. No synthetic
minute is created, no proposed arm is activated, and no production Gold rule changes.
