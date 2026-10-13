# Phase 7 certification follow-up — research only

Starting source: `c6980ad7b39fca215fc0ed1a47f85866110ea331` on
`codex/monatise-phase7`. Follow-up branch: `codex/monatise-phase7-certification`.
All 601 Phase 6 source files remain byte-identical to `43d80956…`. Original
Phase 6 and frozen H1 checkouts remain clean. No production registration,
execution, Telegram, account, risk-limit, secret or deployment changes occurred.

## Resolved and still-unverified gates

| Gate | Outcome |
| --- | --- |
| Existing Databento subscription | User confirmed included live access and authorized proceeding with no additional charges. Fresh historical/LIVE-mode metadata estimates were exactly zero before acquisition. |
| Wider genuine native inputs | Midnight OG definition catalogue: 34,191 definition records, 32,333 unique identities. Successful exact live scopes: 32, then 144 options across two expirations, plus GCZ6. Final current-time scope captured all 145 definitions. |
| UDI normalization | Six original Y-flag outright options admitted through a new hash-bound research adapter. Native bytes and tag 9779 remain unchanged; standard-only production discovery remains unchanged. |
| Dated model rate | NY Fed SOFR source captured with raw JSON/hash/HTTP metadata. Latest observed effective date October 9, 2026, rate 3.87%; flat overnight extrapolation is explicitly a research discount assumption, not an observed term OIS curve. |
| Greek integrity | Existing CRR/IV/Black76 retained; American FD domain fixed across bumps. Mandatory additional CRR checks at 800/1600 steps and 0.5%/0.25% bumps now reject the independent review's unstable ATM case. |
| Genuine model diagnostics | Afternoon: eight nearby options passed under stated assumptions. Final evening capture: six of eight passed; two were suppressed for stale/asynchronous quotes. Remaining contracts' sensitivities are not asserted validated. |
| TradingView candle UTC | Verified directly in Safari's export UI; all six required/regime timeframes freshly exported. Canonical context and price-only structure primitives invoked offline. |
| Certified spot/futures basis | BLOCKED. Safari supplies FXCM bid/ask values, but source quote event/receive timestamps and a reviewed latency bound are unavailable. Candle UTC is not quote-event UTC. Authenticated cross-host clock/drift remains unverified. |
| Complete chain / dealer gamma | BLOCKED. A bounded two-expiry band is not all expiry/strike tails; intraday changes outside the subscribed set and final clearing reconciliation remain unverified. OI does not identify dealer signs. |
| Trade/grid qualification | NO_TRADE. Current M15/M1 price structure conflicts, canonical H1 parent/anchor qualification is unavailable, quote timing/basis fails, and broker/risk/governance are unvalidated. Grid unavailable, allocation 0%. |

## Research adapter and numerical changes

New `phase7/udi.py` accepts only actual native definitions with reviewed
American OG specifications, exact underlying publisher/ID/symbol, USD currency,
100 troy ounces, $0.10 premium tick, original strike/symbol/maturity agreement,
zero legs and the expected American CFI. UDI and UDS are distinct. It uses
existing immutable Contract/InstrumentMetadata classes and never changes the
shared `discover()` acceptance policy. Native Y flags remain in economic terms
and the original record hash. Exact creation-request/SBE packets remain absent;
research convention admission is not a claim those packets were recovered.

CME describes dynamically created outright option strikes coexisting with
exchange-listed strikes in its
[UDI documentation](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457703567/User%2BDefined%2BInstruments%2B-%2BUDI)
and [official COMEX-channel advisory](https://www.cmegroup.com/notices/electronic-trading/2016/08/20160829.html).
American exercise and underlying month rules follow
[Chapter 115](https://www.cmegroup.com/rulebook/COMEX/1a/115.pdf).
Strike-grid research is supported by the
[Rule 300.20 filing](https://www.cmegroup.com/content/dam/cmegroup/market-regulation/rule-filings/2023/9/23-328_3.pdf)
and actual native catalogue; selected $25 gaps were not treated as the listing
increment. No catalogue enumeration grants complete current exchange coverage.

The independent review supplied before this decision found smaller-bump lattice
gamma divergence in a synthetic ATM case that the original gate accepted. The
new gate rejects it with `fine_bump_lattice_gamma_instability`. It cannot pass
because prices agree. Fixed FD domain removes one unintended mesh-change source;
this is not a claim of a fully audited American LCP production solver. Genuine
outputs remain MODEL_GENERATED_NOT_EXCHANGE_PUBLISHED and research-tolerance
validated, with all rates, IV, bump and mesh diagnostics retained.

The rate source is the
[New York Fed reference-rate API](https://markets.newyorkfed.org/api/rates/secured/sofr/last/5.json).
SOFR uses ACT/360; the explicitly assumed flat simple discount factor is
converted to a continuous ACT/365F annual rate for each option term:
`log(1 + SOFR * days / 360) / (days / 365)`.
The [NY Fed publication policy](https://www.newyorkfed.org/markets/reference-rates/additional-information-about-reference-rates)
explains business-day/holiday handling and potential revisions. Retrieval time
is availability evidence, not an invented exact publication timestamp.

## Acquisition, source integrity and cost

Source scope is GLBX.MDP3/XCEC, exact GCZ6 and selected OG identities.
Every successful quote/statistics stream is exact-ID scoped. Definitions,
quotes and published OI retain native bytes, clocks, hashes, quantities and
reference/publication/availability distinctions. Existing NativeJournal handles
durable framing/sealing and rejects quarantined groups; every record roundtrips
through the pinned DBN decoder. Catalogues/quotes remain private, not in Git.

Two early broad capture attempts quarantined on queue overflow and a provider
slow-reader/skipped-record error. Their data is excluded. Exact-scope writes
were moved off the event loop; subsequent explicitly started bounded captures
succeeded. There is no automatic reconnect/retry. The only historical data
request was an included zero-estimate midnight definition catalogue; a one-use
attempt receipt prevents replaying that acquisition automatically.

An initial live-capture escalation was automatically rejected because live cost
had not been independently established. Free LIVE-mode estimates and the user's
explicit subscription confirmation supported the later allowed capture. No paid
request, plan upgrade, subscription purchase or payment was submitted. Metadata
`mode` is deprecated in this SDK, and estimates are not hard provider charge
caps; the subscription confirmation and reviewed current cycle are retained.
Expected incremental usage/credit/cash is zero under that included subscription;
actual invoice reconciliation is not independently asserted. Earlier billing
reservations remain untouched. See
[Databento plan coverage](https://databento.com/pricing/).

## Final rerun and deterministic validation

Final native capture as-of: **2026-10-13 22:38:09.442307 UTC**. Counts: 145
definitions, 5,752 quote records and 32,513 statistics records (typed counts;
framed control/mapping counts are retained separately). All 144 option
definitions normalize, including six UDIs. All 144 have published OI in the
declared scope. Thirty-two legs fail evening quote quality/freshness/skew gates;
no stale leg becomes a current model or zero exposure.

Final model diagnostic subset is eight exact nearby options, with six passing
and two rejected. This is deliberately a bounded validation subset, not a
complete chain's Greek calculation. No signed dealer GEX, authoritative gamma
flip/wall or options-derived spot entry is produced. No earlier indicative
$23.20 basis or $4,176.80 mapping is carried forward as current evidence.

`phase7/certification.py` reads only sealed private journals and dated inputs;
it constructs no provider client. It reuses normalization, OI, coverage, Greek
and research-GIL seams, binds source-code hashes, and leaves execution/GIL flags
false. Two independent offline runs produce identical current replay bytes.
The detailed local deliverables contain native source hashes and the complete
input/rejection ledger, separate from source-code engineering tests.

Final tests: **2,391 passed, zero failures/errors/skips** in the complete
disposable PostgreSQL/Redis/frozen-H1 suite. Targeted synthetic engineering
tests: **76 passed**. Whole-suite regressions cover unchanged production guards;
synthetic passing fixtures never certify real market inputs.

The normalized user report includes exact issue/expiry times, refreshed UTC
1H/15M/5M/1M/Daily/4H candle contexts, all twelve indicator roles plus additional
observed scripts, raw grid actions, unavailable fields and a research-only
NO-TRADE/grid-unavailable decision. Full Gold execution engine was not invoked;
the component invocations are named explicitly. No frozen H1 selector changes
or fabricated broker prices, volumes, anchors or entries were made.

## Remaining prerequisites

TradingView is the user-selected FXCM spot source. Its candle UTC label and
local observation receipt do not establish the event time of the displayed
bid/ask; no legitimate bounded synchronization certificate follows from them.
Finishing that gate requires a source providing documented quote-event/receive
times and bounded latency, plus a reviewed cross-host clock/drift policy.
Only then can basis/uncertainty and qualified context translation be recomputed.

Full-scope Greek/surface and expiry-tail coverage, live quote eligibility,
OI clearing finality and independently evidenced positioning must remain
separate from aggregate published OI. Broker price, canonical technical
qualification, portfolio sizing, 2:1 permitted-fill R:R and execution governance
still must pass before any grid can qualify. More quotes or narrow dispersion
cannot substitute for any missing certification prerequisite.
