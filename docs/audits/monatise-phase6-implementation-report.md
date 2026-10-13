# Monatise Phase 6 research implementation report

13 October 2026. Safely achievable Phase 6 engineering is implemented and verified
on dedicated branch `codex/monatise-phase6`, from frozen
`51988f0ced35ee6bbe378174e80b57f2c9943a47`. Research limitations remain explicit:
ES/NQ billing quarantine is retained, genuine broker basis validation and genuine
options analytics remain blocked, and production activation is not authorized.

## Baseline and preservation

The [baseline audit](monatise-phase6-baseline-audit.md) identifies reused components,
gaps and compatibility risks before implementation. **All 575 original tracked
files are unchanged.** The baseline branch still points to 51988f0. The separate
frozen selector checkout remains clean at f1de9d46. All thirty original native
archive hashes, thirteen prior evidence files and five replay pairs were rechecked.
The original authenticated encrypted Phase 1–5 backup retains its original hash.
Its independently verified private Google Drive copy and separate Apple Passwords
key record are preserved; no new backup was generated or any original deleted.

The actual saved frozen GC replay still contains 557 assessments, **69 valid
Fibonacci assessments across 12 H1 episodes**, zero qualified Gold setups and null
win rate. No extension touch is relabelled a trade win. The original twenty-one
Class E GC omissions and independent certification restrictions remain unresolved.

## ES/NQ billing and admission

The six original acquisitions were inspected without redownload. Exact native
identities: ESZ6 / publisher 1 / instrument 10252; NQZ6 / publisher 1 / instrument
261401. Definitions cover 5 October 2026 00:00–15:00 UTC; trades and OHLCV cover
15:00–15:15 UTC, exclusive ends. Saved acquisition times, request/archive/manifest
hashes, one attempt each and original one-use reservations are bound in the new
private report. Dataset is GLBX.MDP3 throughout.

| Request | Saved provider estimate USD |
|---|---:|
| ESZ6 definition | 0.000000823289 |
| ESZ6 trades | 0.013806223869 |
| ESZ6 ohlcv-1m | 0.000054761767 |
| NQZ6 definition | 0.000000823289 |
| NQZ6 trades | 0.012618362904 |
| NQZ6 ohlcv-1m | 0.000054761767 |
| Total estimate | **0.026535756885** |

**Actual six-request API usage, promotional-credit allocation and cash expenditure
remain unknown.** Six $1 reservations remain, totalling $6 reserved rather than
charged. No settlement or budget mutation was performed. The user's conditional
research-admission instruction is recorded; it does not override missing billing.

Refreshed authenticated Safari billing shows $123.45 rounded remaining credit,
$0.00 balance due, aggregate service charges $1.55, applicable credits $1.55 and
rounded GLBX subtotal $1.54. The Phase 5 usage view had shown $1.56. This discrepancy
is retained, not solved by estimating individual charges. The portal states the
first invoice becomes available **1 November 2026**. It shows usage access enabled
with no limit; no account settings changed. Temporary connectivity recovered.

**Missing release evidence:** an independently reviewed provider journal/settled
statement matching each of the six original exact requests, authoritative amounts,
credit/cash allocation and acquisition attribution. An aggregate invoice alone may
still be insufficient. `billing.reconcile` and `release_bundle` enforce all-or-none
research admission with native cache, explicit admission and independent quality
gates. A positive mocked settlement/release path and negative scope, time, origin,
cash, estimate-only, quality and changed-manifest cases pass. The actual result is
`BILLING_OR_QUALITY_QUARANTINE_RETAINED`; no observations entered canonical scoring.

## GC CVD investigation

Native Phase 5 observations were preserved and the existing MBP-1 archive was read
at original ordinals. The three trades' original aggressor fields remain absent.
All captured trade/quote timestamps, sequences and source hashes are in the private
investigation. No additional trade or quote history was acquired.

| Exchange-side result | Value |
|---|---:|
| Buyer-initiated contracts | 671 |
| Seller-initiated contracts | 796 |
| Unknown-side contracts | 3 |
| Captured executed contracts | 1,470 |
| Known CVD | −125 |
| CVD bounds | **[−128, −122]** |
| Classified-volume coverage | 99.7959% |

Strictly earlier event/receive/sequence, fresh unlocked two-sided quotes and exact
price touches support separate **heuristic** classifications of two sells and one
buy. Their combined diagnostic delta is −126, conditional on that rule. This does
not recover exchange-reported sides: full exchange CVD stays null/incomplete and
complete-window certification stays false. Unknown-volume bounds and cumulative
paths remain available. The report does not certify packet/sequence continuity or
original historical availability from later archive acquisition.

## Basis methodology and validation

The [research interface documentation](../monatise-phase6-research.md) describes
rolling median, recency-weighted median and MAD-filtered candidates, baseline reuse,
causal clocks, broker/server/session/contract binding, expiry buffer and uncertainty.
The observed envelope includes all residuals, BBO half-spreads and a separately
reviewed timing/aging bound. Mappings are contextual estimates only; actual broker
entries, stops, targets and sizing retain broker price/specification authority.

Engineering walk-forward tests use eight synthetic pairs and three held-out points.
All candidates and the existing service show zero error on this deliberately
constant-basis example. It is a determinism/code-path check, **not evidence of
improvement or authentic predictive accuracy**. Perturbed holdouts do not alter their
training hashes. Outliers remain in uncertainty; roll, stale/future data, missing
receipts, wrong identity, session changes and excessive uncertainty reject mapping.
No synchronized genuine broker exports/original capture proofs were found. Authentic
mapping therefore returns `MAPPING_UNAVAILABLE`. No production basis replacement.

## Options readiness and research GIL

Implemented: explicit independently reviewed definition/rate availability and
standard OG exercise/settlement input review; bounded exact-contract acquisition
proposal using existing cache and metadata preflight seams; American CRR IV reuse;
American sensitivity stability experiments; European engineering theta/Greek/OI
scenarios and candidate grid crossings; exact-contract options-level context mapping.
No mandatory external GIL provider is imposed on these new research modules.
Historical/production GIL routing and canonical index positioning remain unchanged.

Genuine GLBX options capability is supported by the authenticated prior OG catalog
and [official Databento options example](https://databento.com/docs/examples/options/options-on-futures-introduction).
Published OI has separate reference/publication fields in the
[statistics schema](https://databento.com/docs/schemas-and-data-formats/statistics).
Neither establishes this account's exact option-contract coverage or entitlement.
[CME Rule 115](https://www.cmegroup.com/rulebook/COMEX/1a/115.pdf) documents standard
Gold American exercise into the underlying future. Actual native definitions,
expiries, multiplier and settlement review must still bind each research input.

No authentic OG definitions, synchronized option quotes, published OI or dated rates
were acquired or accepted. Authentic options status is `BLOCKED_AUTHENTIC_INPUTS`.
American gamma/delta/vega/theta remain uncertified/null. The synthetic CRR experiment
shows gamma variation about 0.010176 across step/bump choices, supporting continued
non-certification. European benchmarks report unsigned OI sensitivity and explicitly
assumed per-leg inventory signs. Candidate crossings are model-grid scenarios,
not observed gamma flips; aggregate OI is not dealer inventory. Missing OI keeps
exposure and affected concentration subtotals null. No verified signed dealer GEX,
chain completeness, institutional positioning or authentic options-to-spot level.

## Canonical outcomes and data matrix

| Market path | Authentic outcome | Reason |
|---|---|---|
| Gold/XAUUSD | BLOCKED_AUTHENTIC_INPUTS | Genuine reviewed broker candles and synchronized quotes absent |
| ES/US500.cash | BLOCKED_AUTHENTIC_INPUTS | Broker inputs and mandatory canonical positioning absent; native billing unresolved |
| NQ/US100.cash | BLOCKED_AUTHENTIC_INPUTS | Same independent requirements |
| BTC | BLOCKED_AUTHENTIC_INPUTS | Genuine native crypto/derivative observations absent |

Separate engineering Gold fixtures exercise LONG, SHORT and NO_TRADE with existing
canonical geometry. Engineering ES/NQ return NO_TRADE. Invalid/incomplete/future
inputs report REJECTED_QUALITY. New GC/options context does not participate in
canonical scoring, no replacement strategy is created, and no trade win rate exists.

| GLBX.MDP3 schema | Authorized genuine local observations | Phase 6 treatment |
|---|---|---|
| definition | GC, ESZ6, NQZ6 | Reuse identity/economics; index admission gated |
| ohlcv-1m | GC, ESZ6, NQZ6 | Captured deterministic replay; no fabricated gaps |
| ohlcv-1h | Existing interface/derived context | No new native acquisition; 15-minute samples do not supply complete H1/H4 |
| trades | GC, ESZ6, NQZ6 | Exchange-side metrics/bounds; index billing retained |
| mbp-1 | GC | Preceding-quote investigation; index/option quotes absent |
| statistics/status | Prior GC archives; no accepted OG OI | Existing normalizers reused; no missing OI invented |
| mbp-10/mbo | Existing offline adapters | No new acquisition; MBO remains disabled by default |

Other feeds remain registry extension points, not newly implemented integrations.

## Validation, files and reproducibility

**2,232 tests passed**, zero failures/errors/skips, 50.66 seconds: original 2,131
plus 101 Phase 6 cases. Separate frozen selector: **53 passed**, zero failures/errors/
skips, 58.93 seconds. The first broad test invocation had a PATH/CLI setup failure
and service-dependent skips; the existing credential-free disposable PostgreSQL/
Redis harness resolved them. There are no final regressions or production test DSNs.

Two final authentic replays in private `phase6-acceptance-v3` are byte-identical.
Runtime: Python 3.14.6, Databento 0.87.0, databento-dbn 0.70.0. Versioned output binds
source/runtime/input hashes, model versions, native identities/provenance, rejection
reasons, quality and actual canonical outcomes. Immutable outputs and failed/earlier
run receipts remain separate. [Machine validation](monatise-phase6-validation.json)
records the exact counts and hashes.

| Evidence | SHA-256 |
|---|---|
| Final repeated replay | `1e8bad9e7adfa7f7302e2aab3df66a06f1b035d793a78e7b5cfbbace662067d5` |
| Logical Phase 6 input | `b0355dde3c0f29f30f634e89d5da0db192b3917c1e25bd2290816033f45956e0` |
| GC normalized, unchanged | `2c9d0fb72a2a04ed5dc635010c652bc9aac05a562f737883445da7433ccc67ba` |
| ES normalized, unchanged | `d671c2e13fc16274b9f3682cef5d0c1878156fcacf38e29d9322cbbb714cf687` |
| NQ normalized, unchanged | `d224d1120402f154e91cc73f1721967ee3197a01c3ff314738309dcaddcc1817` |

New source files: phase6 `__init__.py`, `billing.py`, `cvd.py`, `basis.py`, `options.py`,
`acquisition_plan.py`, `signals.py`, `examples.py`, `worker.py`, `bootstrap.py`,
`runner.py`; `tests/research/test_phase6.py`; this report, baseline audit, validation
JSON and research interface documentation. **No existing file modified.** Reused
components are listed in the audit and methodology; no new runtime dependency,
feed service, QuestDB, Grafana, Kafka or production infrastructure.

## Expenditure, limits and next phase

Phase 6 historical downloads: **0**. Incremental Databento usage, credit consumption
and cash spending: **$0**. Earlier actual request amounts remain unknown; they are
not included as zero historical spending. Provider quotations use the existing
[metadata cost API](https://databento.com/docs/api-reference-historical/metadata),
never an assumption that signup credit makes a download free.

Next independent requirements:

1. Obtain exact provider billing/allocation records, resolve the aggregate discrepancy,
   apply reviewed ledger settlement and explicitly admit the unchanged ES/NQ bundle.
2. Supply independently reviewed genuine broker candles and synchronized bid/ask with
   server/specification/session clocks and original availability proof. Any terminal
   login, live bridge/store operation or new broker access needs separate authorization.
3. Resolve a small exact OG contract set and quote its definition/quote/statistics
   windows after cache inspection. Verify entitlement, fresh credit/expiry and
   zero-cash protection, then obtain **fresh explicit approval for those exact nonzero
   requests and one-use permits**. Broad chains, depth and MBO remain disabled.
4. Validate genuine held-out basis behavior and American Greeks/conventions; demonstrate
   robustness before any model certification. Alternative index positioning research
   cannot silently replace canonical production requirements.
5. Preserve new detailed Phase 6 outputs in a new separately authorized encrypted
   backup checkpoint. The unchanged existing Google Drive package covers Phase 1–5,
   not these new reports. Full restore and cross-device key recovery remain untested.
6. Live-feed engineering/certification and any production activation, GIL-routing
   change, strategy change, deployment, approval/Telegram publication or order
   execution require separate explicit approval. None occurred here.

The final delivery identifies the completed implementation commit SHA. The frozen
starting commit and existing baseline branch are not overwritten. No merge or
production deployment, and no remote Phase 6 preservation claim from a local commit.
