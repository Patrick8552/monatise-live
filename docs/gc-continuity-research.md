# GC continuity forensics and controlled revalidation

Phase 3B separates data admission, Gold analytical qualification and trading outcomes.
It provides source-verified diagnostics and guarded recovery primitives. It does not
invent prices, waive continuity, alter the Gold strategy or enable production.

## Source and data boundary

The verified Phase 3A commit is `0b3050d02afb563385f8a8f9286e2f56d87caeb8` on
`research/databento-cme-foundation`. Its tracked source-file hashes, prepared input,
two accepted ledgers and original acceptance JSON are checked before scanning.
The unchanged canonical baseline, CME foundation, frozen selector and earlier
research identities remain `0f12862…`, `3340bfc…`, `f1de9d4…` and `a144db7…`.

The scanner accepts only the 24 manifests named by that acceptance. It verifies
their hashes, native DBN bytes, metadata/request coverage and actual record counts.
Quarantined acquisitions are excluded. Definition validation and complete native/
derived candle-lineage verification are repeated by the qualification preparer.
No raw file, old result, source baseline or existing spending ledger is overwritten.

`gc_continuity.bootstrap` runs with `-I`, stripped credentials, no networking/child
processes and the existing read/write guard. `runner` requires two identical forensic
reports, then two identical unchanged-window qualification runs. It checks source
hashes and the complete original cutoff schedule before immutable publication.

## Session and missing-data classification

`sessions.py` independently rebuilds native effective-event sessions, handling
midnight snapshots and same-event transitions in native receive/source order.
Unspecified trading state on a no-change message does not create a closure. Truly
indistinguishable conflicting positions fail closed. Reviewed whole-minute intervals
must exactly equal the prior review; a discrepancy stops the scanner rather than
quietly replacing the calendar.

The nominal GC regular schedule uses `America/Chicago`, including DST. Weekend,
maintenance, reviewed early-close/holiday and brief native interruptions are distinct.
Nominal hours are an independent cross-check and never replace native exceptions.
Full, partial, closed and unreviewed intervals remain separate. UTC H4 anchoring,
complete-child aggregation and source/parent expiry are unchanged.

Missing expected minutes are classified from explicit evidence:

| Class | Required evidence |
|---|---|
| A | Reviewed exchange closure; no expected trading observation |
| B | Independent complete trade evidence proves no qualifying executions |
| C | Actual qualifying executions contradict absent required observations |
| D | Valid authentic records exist but aggregation/admission incorrectly omits them |
| E | The available source cannot establish the cause |

No-record OHLCV is not proof of no trades. API transport completion, dataset-level
availability, matching cached schemas or lack of bad flags cannot independently
certify exchange continuity. Observed trade count is null where no archive exists;
zero counts from an uncertified archive remain explicitly uncertified.

## Recovery contract

`recovery.py` requires native contract/definition lineage and a separate external
`TradeContinuityReview` binding exact minute, archives, requests, independent evidence,
complete coverage, correction review, source-position multiplicity and expected count.
This is a trusted reviewed-input boundary, analogous to existing coverage attestations;
Python objects cannot authenticate the reviewer. The scanner never creates a passing
review merely from an EOF or count. There is no acquired certificate for current holes.

Reconstruction accepts executed `T` records, exact GC identity, native fixed-point
precision/tick, positive quantities and verified source ordering. It uses receive-time
buckets to match the documented vendor OHLCV convention, while retaining original
event nanoseconds. It rejects bad-clock/gap/snapshot flags, unreviewed corrections,
source conflicts, incomplete coverage and session-crossing recovery. Informational
fills and quotes cannot become executed volume.

Repeated ingestion of an identical archive ordinal is idempotent. Identical serialized
records at distinct ordinals remain separate source observations; neither byte hashes
nor CME sequence fields identify a unique execution. Cross-archive overlapping/tied
recovery requires a further reviewed ordering and is rejected in this initial interface.

Authentic results carry `TRADE_DERIVED_VERIFIED`, complete contributing record lineage
and the review hash. Engineering fixtures remain `ENGINEERING_SYNTHETIC`. Verified
empty intervals return an observation with no candle or carried-forward price. Recovery
results are stored separately and have `qualification_admitted=false`; incorporating
their source type requires an explicitly reviewed qualification interface. Raw OHLCV
is never overwritten and a reconstructed bar is never called vendor-published OHLCV.

## Verified fixes and policy boundary

The H4 regime actually requires 51 bars for 50 returns; the old research warmup test
accepted 50. `required_history` derives the requirement from canonical defaults and
strengthens H4 admission to 51 while leaving other transport floors at 50. It changes
no indicator period, history cap or expiry. Configuration identifies this stricter
warmup correction as admission version 2.

New summary fields separate candle transport freshness, quote freshness, continuity
and closed-session rejections. The original generic freshness counter remains for
compatibility. Original artifacts are preserved, including the 269 candle freshness
failures that must not be relabelled as quote failures.

The maximum 200 supplied bars and rejection of any missing expected bar in that
window remain unchanged. The latter is an additional conservative research admission
policy, not a 200-bar mathematical minimum of the canonical regime engine. Canonical
structure, zone, liquidity and target producers can nevertheless depend on older
supplied observations, so reducing the prefix to the warmup minimum is not neutral.
No shorter-history or sparse-child policy is activated here.

## Spending and reproduction

The existing cache ledger is copied for read/planning only. Default budget stays $0.
Exact uncovered warmup trade-minute proposals exclude the three October holes already
covered by the cached trade request. No new OHLCV request repeats a complete cached
range. Proposals never create receipts, raise budgets or start downloads.

`acquisition_plan.metadata_only` accepts an injected existing SDK metadata source for
fresh preflights and has no acquisition call. Reliable quotes, current entitlement/
credit checks, a concrete approved credit-only amount and residual uncapped exposure
review are required before using the existing guarded acquisition mechanism. General
credit authorization is acknowledged; a nonzero amount was not supplied in this task.
No fresh authenticated quote or credit balance is asserted from old account evidence.

```sh
.venv/bin/python -m monatise.research.gc_continuity.runner \
  --data-root /path/to/admitted/monatise-gc-research-2026-10-11 \
  --phase3a-root private-reports/gc-qualification-acceptance-v1 \
  --h1-checkout /path/to/unchanged/monatise-gold-h1-fib-f0 \
  --cache-ledger private-reports/cme-validation-v1/research.sqlite \
  --output private-reports/gc-continuity-NEW
```

Run the existing isolated regression harness with a fresh output directory and the
pinned checkout. It uses disposable local test services and no production credentials.
The [Phase 3B report](audits/gc-continuity-implementation-report.md) and
[public source review](audits/gc-continuity-source-review.json) record evidence,
remaining classifications, comparison and approval dependencies.
