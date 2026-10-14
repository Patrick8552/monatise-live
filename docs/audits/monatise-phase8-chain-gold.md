# Phase 8 isolated chain and Gold research audit

The isolated branch adds auditable GC family/coverage reduction, bounded American-option model diagnostics, native-futures hypothetical subset gamma, and a bridge to the preserved frozen H1 selector. Production qualification and provider authority are unchanged. Basis is `DEFERRED_NOT_CERTIFIED`, intentionally not a Phase 8 veto. No futures level is mapped to spot.

Starting commit: `22a77940f4dad84af1046d4fdb63bd3e04a7daab`. Branch: `codex/monatise-phase8-chain-gold-certification`. Frozen H1 source: `f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35`, base `0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`. Historical Run Gold pin is separately preserved. All 625 existing tracked-file hashes match; no production or frozen checkout file was changed.

## Evidence and limits

The declared 90-day monthly/weekly GC scope contains 7,830 normalized contracts, zero definition errors, among 40,932 active catalogued options. Micro definitions remain separate. Six unresolved initial roots, unreviewed nonvanilla families, 33,102 outside-scope contracts and incomplete OI/quote/model coverage prevent a whole-exchange certificate. A parent resolver failure does not establish an empty listing or entitlement denial.

OI distinguishes published zero/nonzero, stale, unknown, not-captured, not-published and not-entitled. Only actual native zero becomes zero. No record in a completed replay window stays UNKNOWN; nonpublication requires explicit publisher evidence. Native event/receive/local clocks are retained separately; no local clock certificate is asserted. Original four-day OI, 30-second quote and one-second causal pair gates remain unchanged. Latest invalid quotes are not replaced by earlier valid marks.

64 representative model probes span both futures, 20 families, C/P, terms and moneyness. 56 validated, eight failed unchanged gates; 2,813 eligible inputs remain NOT_COMPUTED. Source-hash-bound immutable caches retain inputs, result hashes, numerical methods and failure diagnostics. No exchange-published Greek assertion is made. 42 validated/OI-eligible legs support partial-subset sign hypotheses only; missing exposure is unbounded/unknown. No dealer positioning, chain GEX, gamma flip or institutional wall is certified. No repriced curve is computed without adequate coverage.

Gamma units are sum(sign×OI×100×gamma): ounce delta-exposure change per $1/oz futures move, oz²/USD; no F² or1% normalization. Futures IDs remain separate. Sign assumptions and calculation cutoff are explicit. GIL compatibility is design-only: a reviewed native-coordinate interface would require futures identity, convention, clocks, coverage, source/model hashes and hypothetical sign tags. Production spot-qualified provider authority is not replaced.

## Actual frozen selector versus proposed behavior

The frozen checkout already implements the causal structural episode and selector. Pivots reuse the canonical plateau-aware detector and metadata swing window (default3); confirmed closes default1. Long origins are confirmed pre-break lows, short origins highs. Confirmed BOS/CHoCH starts/supersedes an episode; B is the first confirmed directional pivot after the event before the next opposing pivot. Full-span geometry must hold. The exact parent ID and snapshot hash bind selection. Pivot known_at is max actual receipt of the pivot/right-side confirming bars; the broken pivot must be known strictly before break open. Origin breaches, failed breaks, direction mismatch and latest unresolved events reject. Side/bar/level dedup and broken-pivot families suppress repeats.

Canonical H1 lifetime is original close+2h, also capped by the higher parent. Seeds intersect context/setup/trigger/prepared-risk/session expiries; F0 rechecks them. First-parent association caching and revision rejection prevent retrospective improvement. Frozen optional typed Fibonacci anchor constraint and stop-preparation helper were not copied into production. Synthetic default-path canonical/Fib/candidate/risk parity is byte-identical; this proves default behavior only.

## Isolated Gold integration

The bridge invokes the existing frozen offline graph for explicitly labelled engineering/broker archives; a declared archive kind alone never grants a genuine source certificate. The genuine Safari path invokes pure canonical Gold layers and the preserved selector with explicitly degraded price-only observations. It never fabricates broker NormalizedCandle, historical receive time, volume, calendar, units, risk inputs or qualified parent.

The chart ledger requires ordered OHLC/cadence/UTC evidence and two actual observations to finalize bars; known_at is the second local receipt. Revisions reset finalization. H1 rows/hash freeze at first finalization and later lower-frame observations cannot improve that parent. The diagnostic close+2h cap is not a qualified higher-parent expiry. The full genuine canonical graph was not invoked. Wrapper algorithm metadata may retain broker/tick-volume tags; actual data-quality and root scope guards explicitly identify charts and volume=None.

Genuine chart diagnostics rejected H1 with latest_event_unresolvable and M15 with pattern_crosses_gap_or_session_boundary; M5 was not evaluated without a confirmed M15 setup; M1 cannot qualify independently. A/B, Fibonacci candidates, stop, targets and grid remain unavailable. Basis did not cause those rejections. Daily/H4 advisory context and required H1/M15/M5/M1 observations remain distinct.

## Verification, resources and remaining work

2,427 repository tests passed, 112 targeted tests passed, 53 preserved frozen-H1 tests passed; no failures/errors/skips. Disposable database/cache resources were cleaned up. Sealed native final replay and spot final replay are each byte-identical. Validation JSON binds source hashes, archive/replay hashes, XML results and preservation.

Six bounded subscribed-live capture attempts: three accepted, three quarantined; all sockets closed. Approximately439MiB native/framed capture bytes including failures. 64 models took198.121s; full2,877 linear projection8906s is only an estimate. Existing subscribed replay/caches and zero metadata estimates were used; no paid-history/purchase/upgrade/payment occurred, actual billing reconciliation remains unverified. Licensed native journals, quotes, credential material and personal CSVs are excluded from Git.

Remaining gates are coverage/spec review, genuine OI/quotes, uncomputed eligible sensitivities, unknown inventory/missing exposure and genuine point-in-time broker/spot setup/session/units/volume/risk data. No artificial certification closes these gaps. The request attachment is truncated after section9 Daily/H4; unseen instructions were not inferred. No orders, approvals, provider activation, secret/kill-switch modification, deployment or main merge occurred.

Primary convention references: [CME weekly FAQ](https://www.cmegroup.com/articles/faqs/metals-weekly-options.html), [weekly Gold rule1008](https://www.cmegroup.com/rulebook/COMEX/10/1008.pdf), [monthly Gold rule115](https://www.cmegroup.com/rulebook/COMEX/1a/115.pdf), [Micro rule125](https://www.cmegroup.com/rulebook/COMEX/1a/125.pdf), [Databento symbology](https://databento.com/docs/standards-and-conventions/symbology), [live replay](https://databento.com/docs/api-reference-live/basics/intraday-replay). Clearing-reference comparisons preserve dates and are not MDP finality certificates. No additional external provider was fetched.
