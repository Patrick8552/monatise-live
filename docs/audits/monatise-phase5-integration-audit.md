# Phase 5 integration audit

Read-only audit completed before source changes. Local branch is
`research/databento-cme-foundation`, clean at Phase 4
`3007cbc96082a0c09078e3160482dcdd4cdd3af1`. Verified ancestry includes Phase 3B
`f784b268…`, Phase 3A `0b3050d…`, foundation `3340bfc…`, production-source baseline
`0f12862…`. Phase 4 source hashes match acceptance. These are local source identities,
not a claim about current deployed production. Frozen/earlier checkouts and their
identities are recorded in the private baseline; no user changes were overwritten.

## Reuse and actual gaps

| Component | Existing interface reused | Phase 5 gap / change |
|---|---|---|
| Institutional observations/indicators | institutional.models/normalize/indicators | Exact native terms, executed VWAP/profile/POC, unknown sides, visible book, OI clocks and volatility already exist; no replacement calculations |
| GC authenticated archives | institutional.native.process_gc | Genuine scoped data available; retrospective admission and continuity remain uncertified |
| ES/NQ | databento.datasets.discover; institutional.normalize | No accepted exact authentic definitions/observations; Safari catalog confirms ESZ6/NQZ6 product listings, not native IDs/economics; add reviewed cached bundle admission and metadata-only SDK proposals |
| Historical cost/cache | databento.acquisition, controls, archive | Existing guarded one-use requests/cache overlap/budgets; credit observed privately in authenticated Safari, numeric ceiling and exact SDK estimates/entitlements unavailable; no receipts or downloads |
| Broker identity/history | research/broker_xauusd.models; application.gold_sessions; hierarchy.broker_candles | Existing Gold identity/manual plans, reviewed calendars and candle service; missing isolated multi-asset bid/ask import with server/spec/source proof |
| Basis | application.gold_basis.GoldBasisService; institutional.mapping.ContextMapper | Reuse math/provider binding; add broker/server namespace, optional receipt semantics, tick/spec/session validation, complete mapped-level report and cutoff rejection |
| Options | databento.options, institutional.options, application.gold_options | Standard OG model/input joins exist. Native OG chain/quotes/OI/rates absent; add bounded exact-definition selection and coverage/OI-concentration interface; keep American gamma null |
| Canonical Gold/index/crypto | institutional.signals; GoldAnalysisCoordinator; AssetHierarchyAnalysis; build_production_analysis_run | Preserve canonical rules. Add complete research presentation and blocked authentic evaluations; fixture results remain separate |
| GIL/risk/approval/execution | gamma_evidence, hierarchy.risk, ftmo_master, ftmo_execution, trade_publication | Unchanged; no runtime/provider connection, approval, publication or execution instance |
| Isolation/provenance | institutional.isolation; ResearchArtifactStore; source_hashes | Reuse credential-free guarded subprocess, immutable layers and repeated byte comparison |

Local sibling broker research `monatise-broker-xauusd-phase4` has a
BrokerObservationArchive and retrospective candle replay, not a bid/ask tick import.
Its `pilot-verified/long-dataset.json` explicitly says ENGINEERING_SYNTHETIC.
The October 11 FTMO acquisition report records acquisition blocked, not genuine
historical broker samples. The production trace is a code audit, not a tick export.
None supplies synchronized October 5 GC/ES/NQ-to-broker observations.

## Broker runtime boundary

`hierarchy/broker_candles.py:BrokerCandleService.fetch` requires an authenticated
master/healthy bridge and writes a candle request to its store. The MT5 bridge
`SendRequestedCandles` uses CopyRates; current execution quotes use SymbolInfoTick.
This is not a research-only local historical bid/ask export endpoint. Reusing the
live bridge would require separate account access and production-store permission,
neither authorized here.

An existing isolated source-only `MonatiseGoldHistoricalExport.mq5` was found in
the October 11 acquisition output. It binds account/server/symbol/page/range and
uses CopyRates without order calls; it was not run here. It exports candles, not
historical bid/ask ticks. A separately authorized operator needs an authenticated
terminal, read permissions, reviewed broker clock/session/specification metadata,
bounded export scope and source/capture evidence. Do not start the trading EA to
obtain research data. No account credentials are loaded or requested in plaintext.

MetaQuotes documents [CopyTicksRange](https://www.mql5.com/en/docs/series/copyticksrange)
as millisecond-indexed, inclusive at both boundaries, with partial-buffer/time-out
errors. [MqlTick](https://www.mql5.com/en/docs/constants/structures/mqltick) contains
bid/ask and time_msc; it does not supply a contemporaneous client receipt timestamp.
Importer scopes remain half-open UTC and never invent that receipt or a historical
server offset. A current quote is not a historical tick archive.

## Proposed source changes and acceptance boundaries

Add research-only import, cached-bundle, options coverage, mapping-report and complete
presentation adapters within the existing institutional package. Reuse all native
normalization, indicator, basis and decision functions. Add a separately versioned
Phase 5 runner using the same isolation guard. Existing production and Phase 3 source
files stay unchanged. Two Phase 4 research wrappers gain an optional canonical-result
return and an allowlisted Phase 5 bootstrap; defaults preserve existing behavior.
Genuine GC processing is repeated; ES/NQ/OG and authentic
end-to-end broker/crypto paths are explicitly blocked when sufficient real inputs
are absent. Native IDs, account entitlement, exact estimates and request-level cash
exposure remain unknown. No live subscriptions, new infrastructure or policy amendments.

Tests must cover native provenance/identity/revisions, broker/server/spec/tick/session
clocks and receipt absence, mappings at the real cutoff, options selection/OI publication
and incomplete-chain rejection, canonical positive fixtures and genuine missing inputs,
null geometry, readable non-executable previews and deterministic isolated repeats.

## Connected Databento account inspection

The plugin directory returned no Databento connector; the user then authorized
Safari. Its existing authenticated session was inspected on billing, usage and the
ES/NQ/OG catalogs. No API key, payment information or account identity was copied
to reports. A private account observation records credit, aggregate usage and
the absence of a provider account spending limit. Aggregate usage is insufficient
to settle individual archived requests.

ESZ6 and NQZ6 are listed with December 18, 2026 expiration dates as of October 11.
That is catalog evidence, not native definition acceptance. Standard OG is listed
as Gold options on futures with 35,956 catalog rows; a broad product download would
include far more instruments than the selected research question.

The portal's observed request builder selects products and ten-minute endpoints.
A 15:00–15:20 acquisition can retain its full archive while deriving the unchanged
15:00–15:15 research window. Product-level selection does not meet the exact-contract
requirement. No request was submitted. The new metadata-only SDK interface supports
exact raw-symbol resolution and quotes for both windows, but no secure SDK credential
is available to this shell. Schema listings do not establish entitlement.

## Subsequent acquired-data validation

The user supplied a working SDK credential, authorized the needed ES/NQ downloads
up to available credit, and explicitly authorized saving the credential for future
use. Six exact native archives were acquired (one definition, trades and 15 one-minute
candles per contract). Exact IDs and native economics are now verified. Data stays
under billing quarantine because account-level rounded usage is not per-request
settlement. See the authentic data report for final counts and cost evidence.

An actual ES definition exposed the display factor on the native tick-value field.
The new native-index validator checks amount/display against tick times contract
size and leaves normalized DBN market prices untouched. A successful SDK file
reader leak was also fixed and covered by a mocked regression. Three existing
research files changed in total; no production or frozen selector file changed.
