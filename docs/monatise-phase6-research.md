# Phase 6 isolated research interfaces

The frozen starting reference is `51988f0ced35ee6bbe378174e80b57f2c9943a47`.
All additions are under `monatise.research.institutional.phase6`. No application
registration, production configuration or decision threshold changes.

## Architecture and reproducibility

Verified local DBN archives → existing native normalization → Phase 6 diagnostics
and reviewed admission gates → unchanged canonical analytical adapters → immutable
research output. The existing offline audit guard blocks sockets, child processes,
secret paths and production execution/publication imports in the worker. Its parent
runs a fresh credential-free `python -I` process twice, compares bytes and source
hashes, and verifies the original ledger is unchanged. This is defense in depth for
trusted code, not an OS sandbox for hostile code.

Run with the project's existing environment, an unused **private** output directory
and the original authorized data locations:

```sh
python -m monatise.research.institutional.phase6.runner \
  --output private-reports/phase6-new-run \
  --data-root /absolute/path/to/authorized-gc-archives \
  --prepared-file /absolute/path/to/accepted/prepared-input.json \
  --esnq-root /absolute/path/to/phase5-esnq-acquisition-v1 \
  --ledger-path /absolute/path/to/cme-validation-v1/research.sqlite
```

No arguments activate acquisition, trading, GIL, Telegram, approval or deployment.
The Python `run` interface also accepts independently reviewed billing records,
conditional admission references and broker candle import specifications. Origin
reviews remain an operator trust boundary; a label or file hash does not authenticate
an exchange, broker or provider. Detailed outputs contain licensed observations and
must remain private. Old artifacts and the original encrypted backup are preserved.

## Billing and research admission

`billing.reconcile` checks six exact request specifications, acquired timestamps,
archive/manifest hashes, matching one-use reservations and native diagnostics. A
normalized provider journal/settled statement must bind each request to a provider
request ID, exact scope, original acquisition reference and independently verified
source hash. Actual usage must equal promotional credit plus cash. Cash discrepancies,
missing authoritativeness, missing explicit admission, changed cache or independent
quality quarantine prevent release. Rounded account totals and estimates are rejected
as settlement evidence. Reviews normalize provider fields without changing raw receipts.

`release_bundle` reuses `cached_bundle.admit` to build a **separate** admitted view
only after all six requests pass. Original manifests and archives are never rewritten.
The existing ledger's reviewed `settle` operation remains the operator seam for actual
settlement; this read-only runner neither erases nor converts reservations. Reconcile
and settle from the same verified provider records before accounting is closed.
Continuity, calendar, point-in-time and trading certification remain independent of
billing release. The current run retains quarantine and every reservation.

## CVD methodology

`cvd.evaluate` reuses native-position deduplication and provenance. It reports
B, S, U, known CVD B−S, bounds [B−S−U, B−S+U], classified-volume coverage and the
bounded cumulative path. Native duplicate positions are deduplicated; conflicting
revisions, mixed contracts and unordered observations fail. Unknown sides remain
unknown in the exchange-side result even when quote heuristics are available.

The diagnostic quote rule requires the latest captured quote to have strictly earlier
exchange event, capture-receive timestamp and native sequence, a positive unlocked
BBO, age at most 250 ms and an exact bid/ask price touch. Inside/outside-spread,
ambiguous, future or missing quotes stay unresolved. It does not use a tick-direction
rule or select an older convenient quote after a rejected newest quote. Native MBP-1
archive positions and record hashes identify each candidate. Inferred volumes are
reported separately; retrospective acquisition clocks cannot become historical
point-in-time availability. Sequence continuity and full-session completeness remain
uncertified, so even inferred coverage does not establish full-window CVD.

## Basis candidates and held-out evaluation

`basis.evaluate` reuses ContextMapper/GoldBasisService with the same exact GC
identity, units, unique increasing pairs, broker/server namespace, sessions and
availability gates. Candidate methods are rolling median, recency-weighted median
(weights `1/(1 + age_seconds)`) and median after a three-MAD filter. At least five
retained observations are required. A changed contract, session, provider, missing
receipt, late admission, stale/future quote or unvalidated near-expiry window rejects
mapping. Default age is 30 s, skew 1 s, observed basis range $0.50; expiry buffer one
day. These are research parameters, not calibrated production tolerances.

The candidate envelope is maximum residual across **all** admitted basis samples
(including filtered outliers), plus maximum combined half-spread and a separately
reviewed price-change bound applied to event-clock skew and observation aging.
Default illustrative timing bound is $0.01/s and maximum uncertainty $2; genuine
use requires a defensible bound review, not acceptance of fixture values. The result
is an observed engineering envelope, not a probabilistic confidence interval or a
guarantee about unobserved future basis moves. Expiry is bounded by the oldest
underlying event, sessions and contract expiry buffer. Original GC prices remain GC.

`basis.held_out` performs fixed-policy walk-forward fitting on preceding pairs only.
A test broker price is used solely for the residual/interval check. It reports each
training hash and comparison with the existing service. It does not tune parameters,
select a production replacement or claim authentic superiority from fixtures.
Independent historical original-availability evidence is required for genuine
validation. No genuine broker pairs are currently available.

## Options, research GIL and context mapping

The user's Phase 6 research-policy change permits independent GC options research
without mandatory FlashAlpha/ThetaData/Unusual Whales inputs. `POLICY` applies only
here. Existing production/historical GIL routing and canonical index positioning
requirements are preserved.

Reuse: exact standard OG native definitions, four-strike/eight-contract selection,
underlying identity/economics, published OI reference/publication/availability clocks,
quote joins and the existing American futures CRR implied-volatility model. New
`OptionInputReview` binds independently reviewed exercise-into-underlying-future
settlement, definition availability and dated rate availability/source. Missing OI
stays null; raw fields and model estimates remain distinct. American Greeks remain
uncertified/null. Numerical central-bump experiments across 200/400/800 CRR steps
report instability rather than certifying gamma.

European Black-76 engineering benchmarks reuse existing Greeks, add calendar theta
by time differentiation, unsigned `gamma × OI × multiplier × F² × 0.01` sensitivity,
selected strike/call/put OI and explicit per-leg inventory-sign scenarios. Gamma-grid
crossings use linear interpolation between opposite signs under fixed IV/rate/maturity.
A zero curve is not a flip. OI neither reveals dealer signs nor certifies a complete
chain. These benchmarks are not authentic OG analytics or verified dealer GEX.

`options.map_level` binds an actual strike to its exact option definition and GC
underlying, or requires a documented gamma-scenario assumption/source. It checks
as-of availability, basis expiry/uncertainty, observation age, option/future expiry
compatibility and matching evidence kind. It labels actual strike, calculated level,
contextual XAUUSD interval and observed broker reference separately. A mapped level
is never an entry, stop, target, order or price authority.

`acquisition_plan.requests/review` creates bounded exact-contract proposals only:
definition at most one day, quotes 15 minutes, statistics five days. It reuses cache
plans before calling the injected metadata-only preflight seam. Unknown cost,
unreviewed entitlement, partial overlap, insufficient/future/stale credit or absent
zero-cash protection blocks progress. Any nonzero cost requires fresh explicit
request-specific approval and the existing one-use permits. There is no downloader
or automatic permit creation. No options history was acquired in this phase.

## Canonical evaluation

`signals` retains GoldAnalysisCoordinator/GoldHierarchyAnalysis, index primary
positioning validation and crypto canonical stages. Broker candles enter through
the existing independent import review. Missing genuine inputs report
`BLOCKED_AUTHENTIC_INPUTS`; invalid evidence reports `REJECTED_QUALITY`; actual
canonical code paths retain LONG, SHORT or NO_TRADE with their original geometry and
reasons. Fixtures require a separate explicit engineering flag. New futures/options
context is attached to the report and does not change scoring. Broker entries,
stops, targets and risk cannot use translated futures prices. Frozen H1 evidence
is preserved separately; extension touches are not executed-trade outcomes.

## Primary references reviewed on 13 October 2026

[Databento metadata API](https://databento.com/docs/api-reference-historical/metadata)
provides supported-schema discovery and exact pre-request cost estimates; it is not
a per-request settled-billing journal. Its official
[options-on-futures example](https://databento.com/docs/examples/options/options-on-futures-introduction)
confirms GLBX.MDP3 option definitions; its broad examples are not adopted here.
[Statistics schema](https://databento.com/docs/schemas-and-data-formats/statistics)
includes published OI with separate reference/capture clocks. Account entitlement,
exact GC option symbols and actual historical coverage require separate verification.

[CME Gold option Rule 115](https://www.cmegroup.com/rulebook/COMEX/1a/115.pdf)
specifies American exercise into an underlying Gold futures position. Actual native
underlying/expiry metadata takes precedence over a root-name/calendar guess.
No assertion is made that ThetaData or Unusual Whales covers GC futures options.
