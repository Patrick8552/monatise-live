# Phase 7 quote and chain follow-up — research only

Starting commit: `2b50d54a20dd5c05d776c93aaeb88db58dbd90de`.
Isolated branch: `codex/monatise-phase7-quote-chain`.
All 601 tracked Phase 6 files remain byte-identical to
`43d80956dcc5670916863326b7cc91b48887bc0d`. Original Phase 6 and frozen H1
checkouts are clean. This follow-up adds three research helpers and their tests;
production code, provider hierarchy, frozen selector, approvals, risk, secrets,
accounts and deployment remain untouched.

## Genuine scope and freshness

Parent discovery uses OG.OPT and GC.FUT original native definitions, reduces
timestamp-ordered updates/deletions, and excludes multileg spreads before
applying outright identity uniqueness. GCZ6 publisher 1 / ID 41271 is checked
against original native economics. All 3,060 linked standard-monthly OG options
normalize, with both calls and puts at every actual captured strike: November
has 623 strikes from 1,000 to 20,000; December has 907 from 500 to 24,000.
These are observed strike lattices, not synthesized uniform increments.
Catalogue completeness means the captured parent scope only. Gold weekly
roots and options tied to other futures are not included in this model scope;
whole-exchange completeness remains false.

Initial capture preserves 746,801 frames. The final incremental capture adds
91,757 frames, with 10 typed definitions, 24,189 quotes and 27,517 statistics.
Every schema reached ReplayComplete, without slow-reader warning, provider
error or quarantine. Connections are now closed. Final local capture cutoff:
2026-10-13T23:59:39.140092+00:00; latest native provider receive:
2026-10-13T23:59:39.337358+00:00. These clocks are distinct and raw;
this archived cutoff is not a continuously streaming report-issuance quote.
Overlap is deduplicated by native byte hash, keeping first local availability.

At the archived provider-market cutoff, 1,284 selected identities lack
admissible published OI; four additional old zero-OI legs fail the current
freshness gate. 952 lack valid
two-sided quotes. The full rejection ledger also records stale quotes and
option/underlying skew; counts overlap. Missing data never becomes zero gamma.
An included bounded historical recovery requested all 1,284 missing symbols.
It recovered only 18 older identities, 112 OI records, reference October 5–8;
all were stale. It recovered no current OI and left 1,266 without any record
in the historical interval. These older records remain separate evidence.

## Transport and offline replay

New `batched_journal.py` extends the unchanged NativeJournal format with
prevalidated bounded batches, one flush/fsync per batch, and cursor advancement
only after durability. Interrupted/failed writes remain unsealed. Nonblocking
private capture callbacks avoid blocking the streaming event loop. New
`catalog.py` reduces genuine original definitions without relaxing production
discovery. New `full_chain.py` constructs no provider client and reuses current
identity normalization, OI, coverage, pricing and Greek gates. Scope partitions
preserve both expiries and call/put pairs; they do not weaken coverage policy.
Every original native record roundtrips through the DBN decoder. Source hashes,
native manifests, rates and cutoff bind the inputs. Raw licensed data and
credentials stay in private local evidence, outside the commit.

## Timestamp and basis result

All six TradingView FXCM spot candle timeframes were freshly exported using
Safari's explicit UTC / UNIX timestamp export setting. This verifies bar
timestamp convention only. Displayed bid/ask values have no documented quote
event/receive UTC or bounded latency. Temporary Safari developer features were
approved, inspected and restored disabled; Web Inspector was blank/unreadable,
so no provider quote timing was harvested. Local observation time and chart
clock are not assigned to quote events. A read-only time-server query timed
out; no system clock change or offset correction was applied.

Raw local-minus-provider receipts span replay delay and negative clock offsets;
they are preserved rather than presented as a certified clock interval. Basis
status remains REJECTED; no synchronized estimate or uncertainty qualifies.
Existing Decimal median, independent sample, identity, spread, age, interval
skew and reviewed clock/time-price envelope gates remain unchanged. Their
engineering defaults are not a TradingView latency certificate. Qualified
spot context would be native strike minus certified basis, with propagated
uncertainty, followed by separate executable broker validation. Spot mappings,
entries and executable prices remain null; the earlier indicative basis and
entry are excluded from current evidence.

## OI, models and gamma

Observed OI subtotals are calls 426,770 and puts 161,284. The reference-October-12
legs sum to November calls 102,646 / puts 64,288 and December calls 324,124 /
puts 96,996. They match the dated FINAL bulletin 196
([CME metals options reference](https://www.cmegroup.com/daily_bulletin/current/Section64_Metals_Option_Products.pdf)).
This is an aggregate reference comparison only: no missing native record is
filled as zero and no row-level clearing finality is certified. CME explicitly
restricts website data to reference use rather than live-MDP validation
([reference policy](https://www.cmegroup.com/market-data/daily-bulletin.html)).

Eight nearby diagnostics pass the existing American CRR/IV and independent
implicit-obstacle finite-difference research tolerances at the archived
provider-market cutoff. Remaining 3,052 sensitivities are not computed or
validated. Model Greeks are not exchange-published. Rate assumption is dated
NY Fed SOFR 3.87%, effective October 9, extrapolated flat with ACT/360 discount
and continuous ACT/365F per-term conversion; no term OIS curve is asserted.
800/1,600-step and 0.5%/0.25% bump convergence gates remain active. No claim of
wall-clock freshness or complete American production-solver certification.

OI is observable outstanding contracts, not dealer signs. A documented
scenario could sum sign times OI times multiplier times gamma, with explicit
units and a reviewed surface; unknown inventory and incomplete eligible
sensitivities block chain-level GEX, gamma flip/wall and spot-entry conclusions.
Observed OI rankings are native GC concentration context, never gamma walls.

## Technical rerun and decision

Pure context and price-only structure components ran offline on fresh FXCM
exports. Full production Gold engine and frozen H1 selector were not invoked.
H1, M15 and M5 compact context all trend down; Daily trends down, H4 remains
structurally conflicted. M15/M5 are transition/conflicted; M1's price-only
bullish proxy does not confirm the higher-timeframe short hypothesis. No newly
confirmed BOS/CHoCH, canonical causal H1 anchors or aligned M1 trigger qualify.
Absent spot volume, session/broker boundary, source quote timing and portfolio
inputs remain explicit. Canonical required grid actions are normal/normal/
normal before veto overlays, not permission to activate a grid. The user report
contains all twelve indicator roles, additional custom router, source values,
formula distinctions, completed-bar clocks, coverage ledger, risk and expiry.

Decision NO-TRADE; grid UNAVAILABLE, recommended allocation 0%, no valid entry
plan. Exact issuance and immediate expiry appear in the final user report.
The frozen H1 two-hour lifetime does not create a qualified causal parent.

## Validation and cost

Complete suite: 2,411 passed, zero failures/errors/skips; 59.906 seconds.
Targeted engineering suite: 96 passed, including 20 new helper tests.
The initial full-suite harness lacked the installed CLI in PATH; its single
packaged-CLI failure is retained privately. Correcting only the disposable
test harness PATH produced the final passing suite. No production change was
made to fix that environmental failure. Synthetic fixtures test engineering;
two independent genuine offline replays are byte-identical, hash
`787b98c957ba27cbf60ab2213f0c91bddfc4cc9e548f618dfcbbd1604ab40a9f`. The public validation JSON retains test,
source, input and native-manifest hashes and preservation results.

User-authorized existing included Databento subscription used. LIVE-mode
preflight estimates and exact historical recovery estimate were zero. Bounded
one-use requests reuse cache and do not automatically retry. No purchase, plan
upgrade, payment or additional paid acquisition was made. Expected incremental
cost/credit use is zero under that subscription; actual invoice reconciliation
is unverified. SDK estimates are not hard charge caps; any future new paid
product still requires explicit approval.

Next certification stage needs documented FXCM quote-event/receive times and
reviewed clock/latency bounds, explicit coverage for additional Gold families,
missing-OI publication/finality semantics, a eligible surface, and separately
labelled inventory evidence/scenarios. The next technical run must still pass
canonical H1, confirmation, session/event, broker, risk and permitted-fill R:R
gates. No order, alert, approval, kill switch, Telegram control, account setting,
production risk limit, secret or deployment was changed.
