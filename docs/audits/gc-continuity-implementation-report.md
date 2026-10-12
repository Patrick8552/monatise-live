# Phase 3B — continuity forensics, safe fixes and revalidation

**October 12, 2026, Africa/Lagos.** Authorized isolated work is implemented and
validated. All 21 missing expected minutes receive Class E classifications with
supporting native coverage, status, availability and parent-bucket evidence. No
current gap meets the independent completeness requirement for recovery. The
unchanged evaluation window still has **zero admissible/qualified candidates**.
No strategy/admission policy is weakened, no synthetic price is created, and new
Databento spending/credit use is **$0**.

## Verified source baseline and evidence

At task start, `research/databento-cme-foundation` was clean at actual Phase 3A
commit `0b3050d02afb563385f8a8f9286e2f56d87caeb8`. Its committed source blobs were
independently hashed against saved acceptance. Production-source baseline is
`0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`, CME foundation `3340bfc5…`, frozen
selector `f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35`, earlier research `a144db7f…`.
Frozen/earlier trees were clean and unchanged. No pre-existing user edits were present.

Preserved Phase 3A ledger:
`7adea734578fc03768fb49840705df0c5f1a9e1258c6a0a8c6ee2ad33f37e5ed`.
Preserved prepared input:
`036eba3d67420b80d5e3f6ea5d4c03f24bbf4c58cfc6e4d6e3e14778101849a3`.
Both original ledgers, archived raw bytes, selector results, configurations and
acceptance documents remain unchanged.

Two fresh native scans reverify 24 complete archives and 6,563,434 records: definitions
23, OHLCV-1m 34,209, trades 428,821, MBP-1 6,100,133 and status 248. The controlled
qualification preparer repeats definition and all 34,207 admitted-minute/9,768-derived
bar lineage validation. Original failed/quarantined downloads remain excluded.

## The September 21 H4 bucket

| Evidence | Verified result |
|---|---|
| Exact identity | GLBX.MDP3 / GCZ6 / publisher 1 / instrument 41271 / XCEC |
| Expected interval | September 21 04:00–08:00 UTC |
| Native reconstructed session | September 20 22:00–September 21 21:00 UTC |
| Session relationship | Entire H4 interval inside trading session; no status transition within it |
| Native OHLCV children | 239 observed minutes; summed published quantity 16,555 |
| Missing child | September 21 04:37–04:38 UTC |
| Request coverage | The verified September 21–28 OHLCV request covers the full interval |
| Direct trade archive/count | No September trade archive; count is **null**, not zero |
| Derived H4 | Intentionally omitted by the full-240-observed-minute policy |
| Root cause | Missing child is established; no-trade versus lost activity remains unresolved |
| Classification/remedy | E; retain rejection, investigate independently complete trade evidence or a separately approved source-policy arm |

The published child bars establish activity elsewhere in the four-hour interval,
not the count or presence of trades in its missing minute. There is no native
`ohlcv-4h` schema or missing H4 download: H4 is a client derivation under the
[published OHLCV schemas](https://databento.com/docs/schemas-and-data-formats/ohlcv). The aggregation
implementation is obeying its explicit contract. No acquisition range defect,
wrong instrument, known closure, timezone shift or session crossing was demonstrated.

The gap cannot legitimately be labelled Class A merely because it falls on a UTC
boundary or on an unrelated platform's holiday. GC's regular overnight session
supports this interval according to [CME GC specifications](https://www.cmegroup.com/market-regulation/files/gold-futures-and-options-fact-card.pdf)
and [session/holiday guidance](https://www.cmegroup.com/trading-hours.html); product-specific native status remains the primary historical
boundary. The independently rebuilt full-minute schedule exactly equals the review.

## Other omissions and trade evidence

The 21 minutes propagate to 19 missing M5, 15 M15, 11 H1 and one H4 bucket. Two
additional native minutes were already excluded because they intersect brief native
session interruptions; they are observed partial-session records, not missing prices.
Partial H4/H1 buckets remain separate from missing expected complete buckets. Native
status snapshots and no-change/unspecified fields are handled using
[Databento's status semantics](https://databento.com/docs/schemas-and-data-formats/status).

| Missing UTC minute | Existing trade evidence | Class |
|---|---|---|
| Sep 7 16:05, 17:03, 17:11, 17:27, 17:31, 17:41, 17:43 | No trade archive | E |
| Sep 7 22:14, 22:59 | No trade archive | E |
| Sep 10 23:28 | No trade archive | E |
| Sep 21 04:37 | No trade archive | E |
| Sep 23 23:01, 23:11 | No trade archive | E |
| Sep 24 23:28 | No trade archive | E |
| Sep 29 22:24 | No trade archive | E |
| Sep 30 22:23, 22:27, 22:28 | No trade archive | E |
| Oct 5 23:21 | Zero observed records in existing trade archive; continuity uncertified | E |
| Oct 6 23:09, 23:44 | Zero observed records in existing trade archive; continuity uncertified | E |

All are wholly inside the reviewed trading intervals. No missing minute has verified
closure, contradictory positive executed activity, or a valid native record wrongly
discarded. A/B/C/D classifiers are implemented and tested, but none is asserted for
these 21 observations. Detailed per-minute sources, clocks, parent intervals and
uncertainty are retained in the immutable forensic report.

Native receive-time trade aggregation exactly matches all 6,777 published minute
records in the five-day trade scope, including price and volume. No mismatch or
trade-containing minute absent from OHLCV was found. This is strong captured-data
consistency evidence, not an independent exchange-continuity certificate. The three
October holes are consistent with empty captured intervals but are not promoted to
verified no-trade observations from transport EOF alone.

There are 883 repeated native byte values at distinct source ordinals. Preserving
those positions reproduces published volume; blindly deduplicating by serialized hash
would change it. Recovery therefore deduplicates repeated ingestion of the same
source position, retains distinct positions, and requires correction/multiplicity
review, consistent with the [trade fields](https://databento.com/docs/schemas-and-data-formats/trades)
and [CME trade-summary normalization](https://databento.com/docs/venues-and-datasets/glbx-mdp3).
Existing uncertified generic trade aggregates must not be treated as complete
execution-volume evidence simply because they have a dedup hash.

## Canonical lookback audit and implemented corrections

| Component | Actual default history requirement |
|---|---|
| H4 regime | 51 bars: 50 returns; ATR/compression also require enough preceding bars |
| Liquidity | 50 bars for default range window |
| Structure | Nine bars at swing window three; pivots need three right-side confirmations |
| Supply/demand | At least 15 bars for its ATR/zone inputs |
| Gold transport/data boundary | 50 finalized bars per role; H4 must additionally satisfy 51-bar regime warmup |
| Supplied research history | Up to 200 bars; older observations can influence structure/zones/targets |

The original H4 50-bar warmup label was inaccurate. The research adapter now derives
the true H4 requirement from unchanged canonical defaults and rejects insufficient
51-bar warmup. Other floors remain 50. This is a stricter data correction, not a
period, expiry or strategy change; the actual replay had enough H4 records, so the
correction does not change its candidate result.

The requirement that every expected bar in the supplied 200-bar window exist is
an **additional conservative research admission policy**. The regime alone does not
mathematically need 200 bars, but reducing the prefix also changes inputs to other
engines. That policy remains unchanged. A [separate versioned proposal](../gc-continuity-policy-proposal.md)
describes native-hour and complete-trade sparse source arms; neither is approved,
implemented or activated. There is no arbitrary 50/100-bar fallback.

New summary counters distinguish quote staleness, candle transport age, continuity
and closure. The prompt's comparison label assigning 269 to quote freshness was
incorrect: saved ledger reasons show **269 candle freshness failures and zero quote
staleness failures**. Likewise, 4,049 is total unavailable evidence, while 3,929
open-session cutoffs have continuity failures and 120 are closed-session decisions.
Original artifacts/counters are preserved; corrected meanings are explicit.

## Controlled before/after result

The exact original UTC window, all 4,049 timestamps, GC identity, quotes, canonical
Gold rules, structural stop formula, target/RR requirements and lifetimes are preserved.

| Metric | Phase 3A actual | Phase 3B |
|---|---:|---:|
| Scheduled cutoffs | 4,049 | 4,049 |
| Data-admissible cutoffs | 0 | 0 |
| Unavailable cutoffs | 4,049 | 4,049 |
| Admitted analytical rejections | 0 | 0 |
| Qualified LONG observations | 0 | 0 |
| Qualified SHORT observations | 0 | 0 |
| Distinct analytical candidates | 0 | 0 |
| Admitted M15 setups / M5 triggers | 0 / 0 | 0 / 0 |
| Target/RR rejections | 0, not reached | 0, not reached |
| Continuity-rejected cutoffs | 3,929 | 3,929 |
| Closed-session cutoffs | 120 | 120 |
| Candle transport freshness failures | 269 | 269 |
| Quote staleness failures | 0 | 0 |

Per-timeframe omission categories overlap: H1/H4 3,929 each, M15 2,729, M5 2,035,
M1 435. They are not independent losses/trades and must not be added. Actual canonical
engines still execute 3,929 explicitly unadmitted diagnostics; these cannot enter the
candidate path. Five frozen H1 episode associations remain distinct from candidates.
The original 69 constrained assessments/12 valid episodes are preserved, not trades.

## Implementation, tests, reproducibility and costs

Added `monatise/research/gc_continuity/` modules for session reconstruction,
classification, verified recovery primitives, forensic scanning, exact-scope proposals
and credential-free orchestration. Modified only three existing research files:
`gc_qualification/adapter.py`, `prepare.py`, `worker.py`. Added 36 continuity tests,
runbook, source review, policy proposal, this report and machine acceptance evidence.

The guarded recovery interface accepts only independent complete/correction-reviewed
trade evidence and native definition lineage. It rejects bad clocks/gaps/snapshots,
wrong identities, incomplete counts, unsupported fills and session crossings. Verified
empty intervals create no price bar. Reconstructed observations remain separate from
raw OHLCV and cannot silently enter qualification. No actual recovery review or
reconstructed candle is manufactured for current data. These
[native flag meanings](https://databento.com/docs/standards-and-conventions/common-fields-enums-types)
do not replace independent completeness/correction evidence.

**2,017 repository tests pass**, zero failures/errors/skips, including 36 new continuity
tests and the 33 Phase 3A qualification tests. Coverage includes all five classes,
source multiplicity/revisions, receive/event clocks, precision/volume/ordering,
strict completeness, no-trade/no-synthetic behavior, maintenance/holiday/partial
sessions, Chicago DST, unknown status fields/snapshots, true H4 warmup, corrected
counts and disabled acquisition. Existing raw/source-integrity and isolated Gold
positive/negative parity tests also pass. Frozen source remains unchanged; production
files, policies, risk, FTMO, MT5, Telegram, GIL and deployment are untouched.

Two forensic outputs are byte-identical:
`4cbdab424776c82786a13efd0540a16a3416f09fddbb60d10c35bc1d2a410c59`.
Two new qualification ledgers are byte-identical:
`04717c36f2bd0a9425e2c2e6b39c85239781d1c2097b3f30f49c5ae8bde77637`.
Source hashes and original schedule equality are checked before immutable publication.
Private licensed evidence lives under `private-reports/gc-continuity-acceptance-v1/`;
[machine acceptance](gc-continuity-validation.json) records checks without publishing
raw prices. No fills, P&L, win rate, drawdown or account returns are calculated.

A final trailing blank-line removal in the continuity subprocess bootstrap preserves
its Python AST. Two further forensic scans using the final source exactly match the
accepted report. Qualification source and accepted ledgers remain unchanged. Machine
acceptance preserves the full-run source hashes and records final hashes and this
formatting follow-up separately.

The original cache ledger is copied, never reconfigured. Its $0 budget, 24 verified
cached requests and unknown historic billing are preserved. Eighteen exact one-minute
warmup `GLBX.MDP3/trades` requests are prepared; the priority is September 21 04:37–04:38
UTC for GCZ6/publisher 1/instrument 41271. The three cached October trade scopes are
not repurchased. No new OHLCV, quotes, options, MBO, MBP-10 or other instrument is bought.

Acquisition remains disabled. No concrete nonzero budget was specified, and no fresh
authenticated cost/credit/entitlement verification is asserted. Existing metadata-only
preflight support is available; old credit and estimates do not become a new receipt.
Before a billable branch, the user-requested controls require a reliable exact quote,
current credit/entitlement review, an explicitly approved maximum credit-only amount,
residual uncapped exposure review and the existing one-use guarded receipt. Cash
expenditure is not authorized. New API spending, credit consumed and cash paid are $0.

## Next decisions

1. Obtain independently sufficient evidence for the 18 uncovered warmup trade minutes
   and contract-specific continuity/correction review for captured empty intervals.
   New data may confirm no trades and still provide no legitimate price to recover.
2. Review the separate source-policy proposal before accepting sparse/no-trade or
   native higher-timeframe observations into qualification. Do not shorten history,
   carry forward prices or waive freshness to force candidates.
3. Only after sufficient evidence or an approved amendment exists, repeat the same
   window and actual Gold path. Zero candidates remains a legitimate result.
4. Live integration, trading outcomes, production activation, deployments, broker
   connections, GIL and publication/approval changes remain separately authorized.
