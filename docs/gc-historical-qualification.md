# Native GC historical analytical qualification

Phase 3A is local, opt-in research. There is no production registration, broker
connection, publisher, approval workflow, GIL activation, execution or deployment.
GCZ6 remains GCZ6. A qualified analytical candidate is not a fill or a trade.

## Source baseline and architecture

The initial source audit verified the clean `research/databento-cme-foundation`
checkout at `3340bfc5bd136a3b9e51e6185a9f54222c4b4f37`, original production baseline
`0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`, frozen research checkout at
`f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35`, and earlier GC research checkout at
`a144db7f89e7bb3bb5748b83660d51243f69dc51`. The completed October 11 Phase 3 audit,
CME implementation audit/report, runbook and saved acceptance artifacts were read
before implementation. The Phase 3 audit remains outside this repository at
`../monatise-gc-phase3-trade-qualification-audit-2026-10-11.md`.

Only `monatise/research/gc_qualification`, its offline fixtures/tests and this
documentation are added. Production Gold methodology, coordinator, XAUUSD identity,
FTMO controls, MT5, Telegram approvals, provider hierarchy, deployment and acquisition
controls remain unchanged. The incomplete `gold_retrospective.run_replay` interface
is not invoked. Its functioning pinned-checkout verifier is reused.

The pipeline is verified native DBN → existing GC candle normalization and source
lineage checks → prefix/session/quote admission → pinned Gold hierarchy → frozen
target-independent entry/stop preparation → canonical target production/selection
with native target normalization → immutable all-cutoff ledger.

The bootstrap loads the unchanged frozen checkout's compatible analytical modules
and appends this checkout's research namespace. It never mixes replacement versions
of the selector or canonical hierarchy. New adapter-file hashes are recorded separately
from the audited source commit and checked before replay. The frozen tree must stay
clean and pinned. Raw archives and licensed observations remain outside Git.

## Exact native contract and evidence

The initial scope is `GLBX.MDP3`, publisher 1, instrument 41271, `GCZ6`, economic
exchange `XCEC`. All admitted native definition records are reconstructed through
the existing narrow GC reference validator. The decision contract binds the
October 5 definition's record hash, clocks, catalog, actual expiration and native
terms. Native tick is 0.1 USD per troy ounce; multiplier is 100 troy ounces; monetary
tick is 10 USD per standard contract. The original display-factor/amount convention
is validated. Already normalized DBN prices are not scaled a second time.

The canonical numeric `broker_units` carrier receives a research-only exchange
price quantum equal to the validated tick, the same tick, and observed MBP-1
spread. This is a field adaptation, not an MT5 point value or lot-size mapping.
No account sizing, margin, broker alias, basis conversion or spot prices are produced.

Supported observations here are existing GCZ6 `definition`, `status`, `ohlcv-1m`
and `mbp-1`; trades archives are reverified for provenance but are not mandatory
entry evidence. Existing UTC M5/M15/H1/H4 derivations are source-matched. No new
schema, option chain, depth acquisition, indicator or strategy filter is introduced.

## Information cutoff and admission

The predeclared window is October 5 00:00 through October 7 19:30 UTC, exclusive,
selected from admitted quote-request boundaries before candidate qualification.
The scheduler emits 4,049 M1 close-plus-ten-second cutoffs strictly inside that
window, including unavailable/closed decisions. It never selects a period by
candidate count. Exact quote partition coverage is a union, not a bounding box.

Each timeframe supplies at most the existing 200 bars, requires at least the
canonical 50 closed bars, and excludes bars beyond the cutoff. Any absent expected
full-session bar inside that source window rejects admission; old holes are not
silently dropped by shortening history. Partial-session buckets are distinct from
missing expected buckets. Reviewed status sessions are conservative whole-minute
intervals; closure is never filled or used to renew a parent.

The existing two-interval transport-age bound and original Gold source/parent TTLs
remain in force: H4 five hours, H1 two hours, M15 45 minutes, M5/signal 15 minutes.
The adapter resets dependencies after unavailable evidence. No H4 reanchoring,
session extension, revised bar acceptance, duplicate conflict or fake independent
second observation is permitted.

Historical candles assume availability at close plus ten seconds. Quote sampling
uses the last admitted event whose native receive time is no later than the cutoff,
requires both native event/receive ages at most 60 seconds, a valid tick-aligned
two-sided BBO, and an event in the current session. Sixty seconds is a declared
conservative research admission assumption, not a calibrated canonical quote rule.
Original exchange, receive, retrieval and archive admission clocks are retained.
These observations are **RETROSPECTIVE_ASSUMED_AVAILABILITY**, never certified local
historical production receipts. Definition/status knowledge is also retrospective.

Where admission fails but prefixes permit analysis, the actual Gold engines run
only under `UNADMITTED_PREFIX_DIAGNOSTIC_ONLY`. That result cannot enter the candidate
path: the ledger remains `UNAVAILABLE`, with null candidate/entry/stop/targets. These
diagnostics explain engine states; they do not overrule missing-data or freshness
rejections and do not count as qualified opportunities.

## Unchanged analytical rules and explicit differences

The actual evaluator controls H1 direction, Gold M15 sweep/reversal chronology,
current causal M5 confirmation and M1 supply/demand zones. The actual accepted M5
semantics are preserved: a confirmed structure event is required, but the canonical
implementation does not impose an additional BOS/CHoCH-only enum restriction.
Tests explicitly cover its existing failed-break event behavior.

Stops use `prepare_entry_stop` and `_gold_stop_values`: M15 sweep extremum plus
`max(native quantum, tick, M1 ATR × existing multiplier)` plus the maximum of
observed spread and existing spread floor, plus the unchanged estimated slippage
allowance. Stops round outward. The existing ATR multiplier 1.0, spread allowance
0.0002 and slippage allowance 0.0003 are not recalibrated. Missing zones or invalid
geometry reject. Observed M1 close, clamped analytical entry and waiting status
remain separate. No Fibonacci invalidation replaces the structural stop.

Actual canonical target producers collect all existing timeframe evidence. The
actual `build_plan` retains freshness, relevance, direction, spacing, nearest
objective, allocations and TP1 RR ≥1.5. It selects with native tick 0.1; chosen
prices then round inward, retain raw values, recompute RR, and validate again.
A rounding failure rejects the plan; it never skips to a farther target. The
inherited default 1e-8 duplicate planning step is bypassed in this research wrapper
because the same producer/builder already ran with the native tick. Risk completes
through the actual `PreparedRiskInputs.complete` interface.

Exact production/broker parity is **not claimed**. Explicit differences are native
identity/volume/units, retrospective cutoff/session/quote admission, observed
exchange spread, native target tick/rounding, and use of target-independent research
preparation instead of preliminary target-dependent risk. Tests prove component
entry/stop/context parity for controlled fixtures and demonstrate the expected
target-price difference. The frozen XAUUSD-only seed/coordinator are not used for GC.

Frozen H1 episodes/legs/anchors/known-at times, 50/61.8/78.6 retracements and
1.272/1.414/1.618 extensions remain unchanged. Saved, hash-bound original-cutoff
selector results are advisory associations, not additional entry gates. The earlier
557 assessments, 69 valid constrained assessments and 12 distinct valid episodes
remain preserved; none becomes an independent trade.

## Ledger, determinism and safety

Each cutoff records run/config/source/raw/derived/definition hashes, GC identity,
latest/prefix candle lineage, known-at evidence, relevant pivot confirmations,
contexts, quote clocks, session state, missing flags, rejection reasons and actual
risk/target inputs when admissible. Stable setup/trigger/zone/candidate IDs derive
from original event times and evidence rather than observation time. Repeated
observations of the same candidate are reported separately from distinct candidates;
there is no one-trade-per-episode rule.

Runs use exclusive fresh output paths. Failed or incomplete runs remain quarantined
and are not promoted to immutable storage. Two complete replays must agree byte for
byte before the existing `ResearchArtifactStore` publishes the ledger and quality
summary as hash-addressed, fsynced, read-only research objects. Filesystem owner
permissions are not a substitute for backups or external WORM storage.

The worker receives only PATH/LANG, starts with Python `-I`, disables bytecode writes,
blocks sockets and child processes, limits reads to explicit local source/runtime/
input roots, and confines mutations to its new output directory. The audit guard
is defense in depth for trusted code, not an OS sandbox against arbitrary malicious
Python/native extensions. No acquisition client, provider, broker, order, publisher,
approval or GIL service is constructed. All five activation flags remain false.

## Reproduction

Use existing locked development/SDK dependencies and unchanged pinned source:

```sh
.venv/bin/python -m monatise.research.gc_qualification.runner \
  --data-root /path/to/admitted/monatise-gc-research-2026-10-11 \
  --h1-checkout /path/to/unchanged/monatise-gold-h1-fib-f0 \
  --output private-reports/gc-qualification-NEW

.venv/bin/python scripts/test_cme_offline.py \
  --output private-reports/gc-qualification-tests-NEW \
  --h1-checkout /path/to/unchanged/monatise-gold-h1-fib-f0
```

The regression harness uses temporary local PostgreSQL/Redis, not production
credentials/services. Tests use controlled analytical fixtures and existing offline
evidence. Qualified LONG/SHORT fixtures are actual analytical paths, not mocked
qualification decisions or authentic market performance claims.

New Databento spending for this implementation is zero. General permission to use
credit does not bypass exact-scope estimates, cache/overlap checks, entitlements,
explicit bounded budget/receipt and unresolved billing controls. No API call,
acquisition, automatic retry, production change, push or deployment is part of this CLI.

See the [acceptance report](audits/gc-qualification-implementation-report.md) for
the real-data outcome and limitations. Subsequent data repair, alternative continuity
handling, historical availability certification, execution modelling or production
activation requires a separate, concrete reviewed scope.
