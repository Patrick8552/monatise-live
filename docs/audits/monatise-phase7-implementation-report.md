# Phase 7 — Databento basis certification and options integrity

Engineering implemented; genuine market certification remains blocked. Decision:
`NO_TRADE`. This is an offline research extension, with no production activation.

## Starting audit and preservation

Repository: Patrick8552/monatise-live. Starting branch `codex/monatise-phase6`;
starting commit `43d80956dcc5670916863326b7cc91b48887bc0d`. Implementation branch
`codex/monatise-phase7` uses a separate worktree. All previously tracked files
are preserved byte for byte; only Phase 7 modules, tests and audit documents are
added. Frozen H1 selector remains at
`f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35` in its original clean checkout.

| Existing seam | Audit finding and reuse |
| --- | --- |
| `research/databento/acquisition.py`, `live_feed.py`, `live_journal.py` | Exact native identities, cost/cache/credit and bounded live permits already exist; no new downloader or live connector added. |
| `application/gold_basis.py`, `institutional/phase6/basis.py` | Existing median, range, residual and fresh-window calculation retained; Phase 7 adds explicit timezone, precision, identity, independence and uncertainty gates. |
| `research/databento/datasets.py`, `institutional/normalize.py` | Native discovery, metadata, economic contracts reused; unsupported user-defined instruments remain rejected. |
| `institutional/options_coverage.py`, `phase6/acquisition_plan.py` | Small exact selections/requests retained; bounded batching expands strikes/expirations and enforces a global budget. |
| `application/gold_options.py`, `institutional/options.py`, `phase6/options.py` | CRR futures American pricing, IV solver and Black76 remain authoritative model primitives. Existing American IV alone does not validate gamma. |
| `application/gamma_evidence.py` | Existing provider certificates/hierarchy remain untouched. Databento supplies exchange-data research; unavailable production providers are explicit, with no use of their cached snapshots. |
| `application/hierarchy`, `research/gc_fib`, `gc_qualification` | Canonical technical gates and frozen H1 structural selection preserved; archived technical context does not prove current qualification. |
| Risk, approval, broker, kill-switch, production entrypoint | All original files unchanged and covered by full regression; Phase 7 imports no execution or publication adapters. |

## Created files

`monatise/research/institutional/phase7/`: `__init__.py`, `basis.py`, `chain.py`,
`greeks.py`, `scenarios.py`, `gil.py`, `replay.py`, `bootstrap.py`, `runner.py`.
`tests/research/test_phase7.py` adds synthetic engineering fixtures, clearly
separated from genuine private-archive acceptance. This report and
`monatise-phase7-validation.json` contain sanitized audit evidence. No existing
file is modified. Raw licensed records and detailed replay remain private.

## Basis methodology and timestamp findings

Exchange event time, Databento receive time, local availability, raw FXCM time,
precision interval, source hashes, midpoint, spreads, worst-case age and skew
are retained for every pair. Decimal median and existing dispersion/residual
gates are followed by a worst-case envelope across *all* pairs:

`|pair basis − median| + GC half-spread + spot half-spread`
`+ reviewed price-change bound × (age + worst-case skew + clock error)`.

Additional elapsed time enlarges mapped intervals until the earliest pair
expires. A bad member rejects the entire window. Restart recalculates from
observations; serialized certification is not trusted. Exact contract mismatch
or expiry suppresses translation.

| Research policy | Value | Rationale/limit |
| --- | --- | --- |
| Minimum independent pairs | 5 | Existing basis minimum, separate events and spot response hashes; engineering threshold, not an empirical confidence claim. |
| Maximum age / worst-case pair skew | 30 s / 1 s | Inherited bounded research windows; uncertainty intervals, not rounded timestamps, determine skew. |
| Independence separation | 1 s | Prevents repeat polling/event reuse from increasing effective count. |
| Maximum spread / basis range / residual | $1 / $0.50 / $1 per oz | Tightened spread versus existing $5; inherited range/residual gates. |
| Maximum uncertainty | $2 per oz | Conservative research refusal threshold, requiring separate calibration before certification. |
| Conditional time-price drift | $0.01 per oz per second | Explicit unreviewed hypothesis for regression only; no genuine certification without an evidence-backed bound. |

CERTIFIED additionally requires genuine labelled observations, authoritative UTC
for both providers, reviewed local clock/identity/time-price bounds, and all
quality gates. Narrow dispersion or sample count alone cannot certify.

The archived XML has empty root/row attributes and an offset-free `Time` string
at second precision. It contains no authoritative timezone marker. Individual
poll response hashes were saved, but original bytes and HTTP headers for every
poll were not; provenance cannot be strengthened retrospectively. The local
clock review is explicitly unauthenticated SNTP research evidence. Existing
offset bounds are propagated, never upgraded to an authoritative review.

FXCM's [statement-time documentation](https://www.fxcm.com/markets/help/execution-why-does-my-trade-execution-price-not-match-what-i-am-seeing-on-the-chart/)
describes account statements/chart settings; it does not establish the timezone
of RatesXML3. The provider's indexed
[ForexConnect getting-started document](https://fxcm-api.readthedocs.io/en/latest/_downloads/de56a4fa625e8218b13a2ac1e89cf975/Getting_Started-fc.pdf)
describes the public XML endpoint and a 30-second update cadence; direct retrieval
currently returns 404, and no XML UTC guarantee was established. An archived
observed faster update cadence is not a timezone guarantee. No authenticated
FXCM API quote stream was captured or assumed. TradingView downloaded candles
remain technical context; candle closes do not supply synchronized two-sided
spot quote midpoints or executable broker Bid/Ask.

The genuine historical regression reproduces ten pairs, median **+$23.20/oz**,
range **$0.36**, and conditional envelope **±$0.69242433393/oz**. State:
**INDICATIVE**. This envelope is conditional on the unverified UTC interpretation,
the assumed drift bound and recorded clock bounds; it is not a certified interval
or a statistical confidence interval. Timestamp ambiguity has no defensible
finite unconditional error bound here. The historical basis is not valid for
the rest of the session or for current trading.

## Options scope, acquisition and conventions

Native replay checks all 42 definition frames, 24,004 quote frames and 2,790
statistics frames, including controls/mappings, against original hashes and DBN
byte roundtrip. Capture was at 2026-10-13 15:02:49.281566 UTC; outputs explicitly
label it historical, not a newly connected live feed.

The scope contains eight option identities, four strikes, one expiration and
one exact underlying. Only six options pass the existing standard-OG definition
normalizer: both 4,200-strike native definitions have
`user_defined_instrument=Y`. Their raw quotes/OI remain observable and auditable;
they are not admitted to validated standard-chain calculations. A user-defined
flag does not establish a spread or invalidate genuine exchange publication;
it requires a separate reviewed normalization convention. The earlier summary
omitted this field; Phase 7 reads the actual native record instead.

Native `display_factor` is 0.01 for these options and 0.1 for the future.
DBN fixed-point prices are divided by 1e9 once; display factor is retained as
metadata, not multiplied into an already normalized market quote. Existing
institutional normalization is used rather than changing the legacy production
normalizer's display-factor assumptions. See
[Databento fixed-point field explanation](https://databento.com/blog/definition-schema-updates-may).

[CME Gold Option Chapter 115](https://www.cmegroup.com/rulebook/COMEX/1a/115.pdf)
specifies American exercise into the underlying futures and USD/oz quotation.
Multiplier/tick/underlying are checked against native definitions and the
[Gold Futures rules](https://www.cmegroup.com/rulebook/COMEX/1a/113.pdf).
The selected $25 gaps are not proof of an exchange strike listing increment;
that convention remains unreviewed. Native OI reference/publication/availability
are distinct; the selected OI is referenced to October 12 and published October
13. No missing OI becomes zero.

Expanded planning supports at most six expirations, 32 strikes per expiration
and 384 exact requests, reusing existing four-strike/eight-contract seams. Global
deduplication, cached manifests, reliable provider estimates, entitlement,
licensing, verified credit, zero-cash protections and request-specific paid
approval remain required. The planner cannot download, reserve or spend a
permit. No new data was acquired in Phase 7.

Coverage requires an exact independently reviewed catalog hash, calls and puts,
enough expirations/strikes, exact underlying economics, available quotes/OI and
reviewed conventions. `REVIEWED_SCOPE_COVERED` describes that explicit scope;
it never claims a complete exchange-wide chain. The October 13 result is
**INSUFFICIENT_CHAIN_COVERAGE**, including rejected definitions, unknown catalog,
unreviewed strike increment, missing expiration breadth and insufficient strikes.

## Greek validation and gamma methodology

Existing IV and futures-martingale CRR pricing are reused. American numerical
sensitivities use odd/even CRR averages at 200/400 steps and independent implicit
Euler obstacle finite differences at 400/800 space/time steps. Each model uses
two futures bump sizes (2%/1%). European analytics are checked against two
finite-difference bumps (0.2%/0.1%). Vega uses symmetric volatility differences;
theta uses symmetric ACT/365F calendar time and is quoted per day. Every curve
point revalidates, with exact instrument, strike, kind, style and cutoff binding.
Counterfactual curve premiums are explicitly model-generated, never market quotes.

Research comparison tolerance is 15% relative plus small absolute floors:
price $0.20/oz, delta .02, gamma 1e-6, vega .05, theta .005/day. This is a
documented engineering refusal policy, not institutional accuracy certification.
Unsupported premium bounds, unavailable rates/conventions, nonphysical Greeks,
failed convergence or repricing return REJECTED and null Greeks. Successful
outputs say MODEL_GENERATED_NOT_EXCHANGE_PUBLISHED and numerical-research
confidence. No model Greek is called exchange published.

Synthetic ATM example F=K=100, ACT/365F T=1, r=.01, IV=.2 validates European
analytic/finite-difference sensitivities and American CRR/independent-FD
sensitivities. The American gamma estimate is approximately .019856; diagnostic
gamma spans approximately .019803–.022080 and meets the stated research tolerance.
Zero-rate American FD also agrees with the European reference within the tested
price tolerance. Genuine October 13 Greek results are all REJECTED: no dated
hash-bound rate input was captured. Rates/volatilities are not invented.

Unsigned gamma-weighted OI is separate from explicit hypothetical per-leg signs.
Scenario exposure units are `gamma × OI × multiplier × F² × .01`: delta-notional
change per 1% futures move, not observed dealer P&L. Roots use bracketed
reevaluation/bisection to a $0.10 interval, with no global uniqueness claim.
Grid nodes at zero or flat-zero ranges do not prove sign transitions. Grid
coverage and validated American sensitivities are required. Volatility is a
declared sticky-strike assumption; shock dynamics and dealer hedges are unknown.
Call, put and combined OI concentrations are labelled selected-scope observations,
never automatically gamma walls. Independently reviewed adverse evidence may
veto a technical hypothesis; hypothetical signs do not boost direction.

No authoritative dealer gamma flip, signed dealer GEX or confirmed institutional
positioning can be published from this capture. Genuine scenario calculations
remain blocked by coverage, conventions and missing rates/validated gamma.

## Mapping, technical qualification and decision

Native futures strike, estimated spot equivalent and executable broker quote
are separate fields. Only CERTIFIED basis may produce qualified *context*
mapping; even that cannot authorize execution. Indicative intervals propagate
the conditional envelope and remain explicitly unqualified. The previously
referenced GC 4,200 level maps historically to approximately 4,176.80 with a
conditional interval approximately 4,176.1076–4,177.4924. This is a generic native
level translation, not validation of the two rejected option definitions and
not a spot entry. Actual executable broker price remains null.

Archived H1/M15/M5 and other downloaded TradingView snapshots retain source
hashes, completed-candle counts, indicator context, swing candidates and FVGs.
They do not establish hash-bound canonical H1 structural anchors, M15/M5 entry
confirmation, liquidity/volume qualification, current risk/reward, broker
Bid/Ask or execution governance. Those gate failures are listed individually.
Options alone cannot create LONG/SHORT. Databento is the research exchange-data
source; preserved production providers are explicitly unavailable, with no
FlashAlpha snapshot used in this research. Genuine decision: **NO_TRADE**,
grid_setup null, entry_levels null, expiry immediate, execution/GIL disabled.

## Replay and verification

Original requested text/JSON evidence exists locally and is hash-bound, not
recreated. Two fresh `-I` subprocesses with stripped credential environment
produce byte-identical replay artifacts; source files and evidence hashes remain
unchanged. Immutable artifact publication reuses the existing research store.
Missing files, hash/count mismatches, truncated frames and incomplete runs fail
closed. Genuine acceptance is separate from synthetic pytest fixtures.

Run `python -m pytest -q tests/research/test_phase7.py` for synthetic engineering
checks. Run `python scripts/test_cme_offline.py --output <fresh-private-directory>
--h1-checkout <frozen-checkout>` for the complete regression with disposable
PostgreSQL/Redis. Genuine acceptance uses:

```text
python -m monatise.research.institutional.phase7.runner
  --capture <original-native-capture-directory>
  --basis-reference <original-basis-and-options.json>
  --technical-reference <original-verified-context.json>
  --user-evidence-json <original-databento-options-basis-evidence-2026-10-13.json>
  --user-evidence-text <original-monatise-databento-options-basis-2026-10-13.txt>
  --output <fresh-private-directory>
```

Final exact test totals, runtimes, acceptance hashes and preservation evidence
are in `monatise-phase7-validation.json`. Reproduction requires the existing
private native archives and compatible pinned Databento/DBN runtime; public
synthetic tests require no credentials or market-data acquisition.

## Blockers, costs and next phase

Certification needs authoritative timestamped two-sided spot quotes with full
raw/HTTP provenance, reviewed clock and empirically justified time-price bounds;
a reviewed exact multi-expiry options catalog/strike convention; resolution of
the native user-defined definitions; fresh quotes and published OI across that
scope; dated rates; independently validated American sensitivities; and separate
broker/canonical technical qualification. OI still cannot supply dealer signs.

Phase 7 incremental acquisitions, provider charges, credit consumption and cash
spend: **zero**. Earlier subscription costs and unresolved prior-phase billing
reservations are not changed or asserted settled. No execution, approval,
deployment, secret, account, risk-limit or frozen-selector changes were made.

Recommended Phase 8: genuine-input certification and independent quantitative
review, starting with timestamp authority and contract normalization. Review a
costed cached-first multi-expiry plan before any new paid request, then calibrate
basis/Greek refusal thresholds on held-out observations. Production activation
requires a separate decision after all canonical and broker gates pass.
