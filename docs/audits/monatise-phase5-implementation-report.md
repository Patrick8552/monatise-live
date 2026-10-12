# Monatise Phase 5 implementation report

Safely achievable Phase 5 engineering is complete and locally validated. Authentic
GC archive replay is accepted for its captured research window. Genuine ES/NQ definitions, trades and candles were subsequently downloaded and
replayed, with billing admission still quarantined. OG options and broker/crypto
end-to-end acceptance remain blocked by missing inputs. No positive trading result is required
or claimed. No production activation occurred.

## Audit and architecture

The [integration audit](monatise-phase5-integration-audit.md) verifies local Phase 4
baseline `3007cbc96082a0c09078e3160482dcdd4cdd3af1`, ancestry, accepted artifacts and
542 original tracked file hashes. Frozen Gold H1, earlier GC research and sibling
broker research checkouts remain clean at their original commits. Two existing research wrappers and the historical SDK reader resource cleanup
changed; production modules, frozen selector, approvals, broker
execution, GIL hierarchy and previous research outputs are unchanged.

The flow is:

1. Existing guarded acquisition/cache/budget controls or an independently reviewed
   source export establish provenance. New metadata-only tooling can prepare exact
   requests and prices; it cannot acquire data or manufacture approval.
2. Existing native definitions, normalization and source ordinals preserve dataset,
   schema, publisher, contract, ticks, UTC clocks and revisions.
3. Reviewed local broker imports preserve server/specification/session identity and
   original availability. Missing clocks stay missing.
4. Existing captured-window indicators and GoldBasisService calculate observations
   and optional contextual mappings. No new indicator changes production decisions.
5. Existing Gold/index/crypto engines evaluate sufficient reviewed canonical inputs.
   A complete presentation adapter exposes their results with every actionable flag
   false. Fixtures and unavailable authentic paths remain separately labelled.
6. A credential-free guarded subprocess produces two identical versioned replays,
   immutable layers and source/input/runtime/output/quality hashes.

Dataset and schema remain distinct from instrument identity. GLBX.MDP3 is the only
active feed in this work. DBN/Zstandard, existing immutable object storage and the
local SQLite control ledger meet current reproducibility/cache needs. No demonstrated
gap justifies QuestDB, Grafana, Kafka, Redis or another deployment dependency. Existing
PostgreSQL/Redis tests run only in disposable local instances.

## Files and reuse

New source files under `monatise/research/institutional/`:

| File | Purpose |
|---|---|
| broker_import.py | Reviewed bid/ask and five-timeframe broker candle admission |
| cached_bundle.py | Exact local DBN request/hash/definition/billing/receipt admission |
| mapping_report.py | Complete source-bound context mapping report using existing math |
| options_coverage.py | Bounded standard OG selection and published selected-contract OI coverage |
| presentation.py | Complete null-preserving preview and readable research-only text |
| phase5_metadata.py | Pinned SDK exact symbol metadata/cost proposal; no download endpoint |
| phase5_bootstrap.py | Existing isolation guard applied to Phase 5 worker |
| phase5_worker.py | Authentic captured GC acceptance, blocked genuine paths and separate fixtures |
| phase5_runner.py | Versioned source-bound repeated immutable acceptance |
| native_index.py | Exact ES/NQ native USD tick-value convention; no DBN price rescaling |
| native_window.py | Local acquired ES/NQ diagnostics with billing quarantine retained |

The research acquisition transport now closes its lazy SDK reader after a
successful file download. A targeted mock verifies the descriptor closes without
altering native bytes. Modified research wrappers: `signals.py` adds optional canonical detail return;
`runner.py` adds one allowlisted Phase 5 worker entry. Existing defaults are unchanged.
Added `tests/research/test_phase5.py` with 63 offline test cases. Added audit, authentic
data, broker mapping, options readiness, implementation, preview and validation
documents. Raw licensed archives, account observation and detailed outputs are ignored
private files; no credentials are included.

Reused components include DatasetCapability/discover, HistoricalRequest,
SDKHistoricalSource, ResearchLedger, NativeDBNArchive/dbn_records/inspect_request_archive,
ResearchArtifactStore, native contract reconstruction, candle/advanced/statistic
normalizers, institutional indicators, GoldBasisService/ContextMapper, options
join_inputs and American IV model, GoldAnalysisCoordinator/GoldHierarchyAnalysis,
AssetHierarchyAnalysis/primary FlashAlpha validation, crypto production analysis
builder/canonical registrations, CandleEvidence and the existing isolation guard.

## Evidence and results

The [authentic data report](monatise-phase5-authentic-data-report.md) contains the
dataset/schema acceptance matrix, cache and cost result. The
[broker mapping report](monatise-phase5-broker-mapping-report.md) and
[options readiness report](monatise-phase5-options-readiness.md) identify genuine
input dependencies. [Preview examples](../monatise-phase5-signal-preview-examples.md)
show complete output boundaries.

Genuine GC replay retains 1,014 trades, 15 candles and one MBP-1 snapshot in the
October 5 15-minute sample. Normalized GC matches Phase 4. Captured VWAP/profile/POC,
known-side delta, visible best-quote liquidity and sampled volatility retain partial
quality; three unknown-side contracts prevent full CVD. There is no complete-session
or historical point-in-time certification, fabricated spot price or trade win rate.

Every authentic broker preview is `BLOCKED_AUTHENTIC_INPUTS`. GC native context is
available but genuine broker candles are absent. Index positioning remains mandatory;
authentic ES/NQ observations cannot bypass it. Native crypto inputs are insufficient.
No fixture is accepted as genuine. Controlled Gold LONG and SHORT paths pass tests;
engineering indices and crypto return NO_TRADE in the acceptance examples. These are
code-path results, not historical trades or model performance.

Source/runtime/input hashes and byte-identical output evidence are in private
`phase5-acceptance-v5/` and [validation JSON](monatise-phase5-validation.json).

| Evidence | SHA-256 |
|---|---|
| Replay output, both runs | `70a320f2c96aa72c71c4dcf2fb3f4cb3eb53017c0cb588770c3b5f392b73fbc2` |
| Normalized GC, unchanged from Phase 4 | `2c9d0fb72a2a04ed5dc635010c652bc9aac05a562f737883445da7433ccc67ba` |
| Phase 5 request/input | `6a43e6e372068be8f2ae42b91651e1100125a7d700c37e83822de72e68dd0d75` |
| Full regression XML | `ba20d5a36916f8d825d4e231c00a9d586c12baeae04ced520a62c0330b42ed41` |

Runtime: Python 3.14.6, databento 0.87.0, databento-dbn 0.70.0. The final offline suite
passed **2,123 tests**, including **63 new tests**, with zero failures/errors/skips
and no regressions. Tests cover import clocks/UTC/ticks/source reviews, retrospective
availability, all three mappings, stale/future/provider/session/duplicate rejection,
native cache billing/hash/identity/completion gates, OG metadata/OI/conventions,
metadata request construction/cost mocks, canonical positive/negative paths,
index primary-provider enforcement, credential removal, isolation and repeatability.
Existing advanced adapters, budget/cache/quarantine and frozen-selector suites pass.

Six exact historical requests were completed through the shared durable ledger and
one-use permits: ESZ6 / publisher 1 / instrument 10252 and NQZ6 / publisher 1 /
instrument 261401. Definitions precede the sample; trades and OHLCV cover October 5
15:00–15:15 UTC. ES has 9,094 trades / 31,453 executed contracts and NQ has 7,750
trades / 11,704 contracts, plus 15 candles and one definition each. Both have zero
missing sample candles and zero unknown-side contracts. Captured VWAP/profile/POC,
delta/CVD and sampled volatility remain partial-window diagnostics. MBP-1, depth,
MBO and options were not downloaded.

The complete six-request estimate was **$0.026535756885**. The account's rounded
usage increased from $1.54 to $1.56; precise per-request billing and credit allocation
remain unresolved. Cash was unauthorized and the observed current cash balance
remained zero. The shared research budget now records the user's available-credit
ceiling, and six $1 reservations remain until actual billing is reconciled. These
reservations are permits, not six-dollar charges. Existing unknown GC billing and
cache provenance were preserved. The isolated replay itself makes zero network calls.

The ES definition's first download succeeded; a validation comparison initially
omitted the display factor on its tick-value field. The corrected exact rule is
`min_price_increment_amount / display_factor = min_price_increment * contract_size`.
This affects native tick-value interpretation only, never DBN market prices.
The cached ES definition was reused; no paid request was retried. A stopped local
resume bookkeeping error also made no new data request. These records remain saved.

Native ES/NQ diagnostics and their normalized hashes are included in the identical
replays, but **research admission stays disabled pending billing reconciliation**.
This is neither a broker strategy result nor a point-in-time trading certificate.
The SDK credential was supplied and saved for future use in an ignored private file
with permissions 600; no credential was committed or included in worker environments.

## Limitations and separate next steps

1. Reconcile the six requests against definitive provider usage/billing records.
   Preserve actual usage and credit separately, then explicitly review admission.
   Genuine definitions/economics and exact IDs are already verified; no redownload is needed.
2. For any additional data, quote exact requests, inspect cache/overlap, refresh account
   credit/expiry and establish zero-cash protection. Apply the recorded credit-only
   ceiling and bind request-specific one-use receipts before any nonzero acquisition.
   API 15-minute scope is preferred; a reviewed 20-minute portal scope can be sliced
   to the unchanged research window. A broad product request remains unsuitable.
3. Provide genuine reviewed broker exports and synchronized quotes, including server,
   sessions, UTC and original capture availability. Live login, bridge/store writes
   and terminal operations need separate authorization. Missing historical receipt
   timestamps cannot be invented. Continuous five-timeframe import currently rejects
   natural session gaps; expanded calendar-aware transport needs explicit validation.
4. For authentic OG research, select a bounded exact underlying/expiry/strike set,
   then supply quotes, published OI, rates and reviewed exercise/settlement conventions.
   American gamma remains uncertified; complete-chain/signed GEX/flip research is a
   separate modelling dependency. GIL provider hierarchy remains unchanged.
5. The guard is defense in depth for trusted research code, not a hostile-code OS
   sandbox. Canonical input review is a trust boundary, not an authenticity oracle.
   Context mappings and captured indicators are never certified execution inputs.
6. Live subscriptions/streaming, production deployment, Telegram publication or
   approval generation, trading-policy changes and order execution require separate
   explicit authorization and acceptance. This commit does not activate them.

The local implementation commit hash is reported in the final delivery and the
private Git receipt after commit. Nothing was pushed or deployed.
