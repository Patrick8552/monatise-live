# Phase 3A implementation report

Native GC analytical qualification is implemented in an isolated research package.
The real-data window produces **zero admissible analytical candidates** under the
declared conservative continuity requirements. This is a data-admission result,
not a strategy win/loss result. No fills, trade outcomes or account performance are
calculated. Incremental Databento usage and credit consumed are **$0**.

## Audit and implementation

All three expected checkout identities and clean working trees were verified before
edits: current implementation `3340bfc5bd136a3b9e51e6185a9f54222c4b4f37`, frozen
selector `f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35`, earlier research
`a144db7f89e7bb3bb5748b83660d51243f69dc51`. Production-source baseline remains
`0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`.

The completed Phase 3 audit and existing CME implementation documentation/acceptance
were reviewed. The audit correctly identified usable price engines and native archives,
an XAUUSD-only coordinator/seed boundary, compatible preparation seams only in the
frozen checkout, incomplete retrospective modules in this checkout, partial quote
coverage, historical availability assumptions and unresolved continuity.

New modules under `monatise/research/gc_qualification/`:

| File | Responsibility |
|---|---|
| `models.py` | Typed native contract/quotes and immutable hashes; no broker lot sizing |
| `prepare.py` | Audited manifest/archive/request checks, definition reconstruction, native minute/derived lineage, session status matching and as-of quote sampling |
| `adapter.py` | Bounded prefixes, expected-session/gap admission, actual Gold evaluator delegation, target-independent preparation and canonical native-tick target planning |
| `worker.py` | Every-cutoff ledger, advisory frozen associations, stable candidate identifiers and separate unadmitted price diagnostics |
| `bootstrap.py`, `isolation.py` | Source-pinned `-I` interpreter, minimal environment, network/process/read/write guards |
| `runner.py`, `__init__.py` | Explicit offline CLI, two-run equality, quarantine and immutable publication |

Also added `tests/research/gc_qualification_fixtures.py`,
`tests/research/test_gc_qualification.py`, the
[architecture/runbook](../gc-historical-qualification.md), this report and saved
machine acceptance evidence. Existing production files, acquisition controls and
the frozen selector are unchanged. No database infrastructure is introduced.

Reused components include `NativeDBNArchive`, native request inspection, GC identity/
candles/snapshots, native definition reconstruction, pinned source verification,
`ResearchArtifactStore`, actual Gold/hierarchy/structure/liquidity/sweep/reclaim/zone
engines, `prepare_entry_stop`, `_gold_stop_values`, `PreparedRiskInputs.complete`,
canonical target production/selection and evidence-bundle validation. The production
Gold coordinator and XAUUSD-only frozen seed are not repurposed for GC.

## Authentic source and compatibility evidence

Reverification covers 24 complete DBN archives and 6,563,434 records: 23 definitions,
34,209 OHLCV minutes, 428,821 trades, 6,100,133 MBP-1 records and 248 status records.
Every archive and acquisition manifest binds to the audited acceptance hashes and
native exact request coverage. All 34,207 admitted normalized minutes and 9,768
derived bars are checked against actual native prices, volumes, identities, clocks
and child-source hashes. The two excluded minutes and 21 missing-or-no-trade minutes
are preserved rather than filled. Prior quarantined acquisitions remain excluded.

GCZ6 retains publisher 1, instrument 41271 and XCEC. Its native definition validates
0.1 USD/oz tick, 100 oz multiplier, 10 USD monetary tick and actual December 29,
2026 18:30 UTC expiration. Native record hash is
`f21ec23e0d01b0e2ca358e42cdef33aec556ecb9376606316ca50b42ee6db85f`.
No display factor is applied again and no XAUUSD mapping is created.

Availability is explicitly `RETROSPECTIVE_ASSUMED_AVAILABILITY`, not point-in-time
receipt certification. Definition/status knowledge and source continuity remain
uncertified. Quote event/receive/admission/retrieval clocks and invalid/stale BBO
rejections are retained. The price quantum equals the verified exchange tick;
existing buffer/allowance values remain unchanged.

Exact broker/production parity is blocked. The runbook lists native identity/volume/
units, retrospective admission, observed exchange spread, native target tick/rounding
and target-independent preparation differences. Controlled tests match canonical
entry, structural stop, allowances and context outputs, while explicitly verifying
the expected target-price difference. No method or threshold is altered to force
historical qualification.

## Real historical result

Window: October 5 00:00 through October 7 19:30 UTC, exclusive, selected from admitted
quote coverage before candidate evaluation. First cutoff is October 5 00:01:10;
last is October 7 19:29:10. Closed/unavailable cutoffs remain in the complete grid.

| Measure | Count |
|---|---:|
| Scheduled cutoffs | 4,049 |
| Data-admissible cutoffs | 0 |
| Unavailable cutoffs | 4,049 |
| Admitted but analytically rejected cutoffs | 0 |
| Qualified LONG observations / distinct candidates | 0 / 0 |
| Qualified SHORT observations / distinct candidates | 0 / 0 |
| Qualified waiting-for-entry observations | 0 |
| Distinct analytical candidates | 0 |
| Existing frozen H1 episodes linked across observations | 5 |
| Admitted M15 setups / M5 triggers | 0 / 0 |
| Admitted target/RR rejections | 0; target qualification was not reached |
| Cutoffs with transport freshness rejection | 269 |
| Cutoffs with incomplete market evidence | 4,049 |
| Instrument-assumption admission rejections | 0 |
| Explicitly unadmitted actual-engine diagnostics | 3,929 |

All 3,929 open-session cutoffs include a missing expected H4 bucket within the
configured history. That missing bucket is September 21 04:00 UTC, still inside
the maximum 200-bar H4 lookback. Expected H1 omissions affect every open-session
cutoff as well. M15, M5 and M1 omissions overlap at 2,729, 2,035 and 435 cutoffs.
The remaining 120 decisions are closed/unreviewed-session rejections. Rejection
categories overlap and must not be added as independent candidate counts.

The adapter does not shorten history, fill empty bars, revise H4 anchoring or
extend expiry to bypass these observations. The actual engines execute only as
unadmitted price diagnostics: 3,225 provide context states; 704 stop at the original
Gold parent/pattern expiration gate. Among context-producing diagnostics, M15 is
`watching` at 1,575 and `no_setup` at 1,650; no confirmed M15 setup is exported.
These observations cannot certify what repaired/complete data would produce.

The earlier 557 H1 assessments, 69 valid constrained Fibonacci assessments and 12
distinct valid episodes remain intact. The five linked episodes here describe
associations in a different subset; they are not five trades. Frozen anchors and
extensions are advisory and are never an added Gold entry condition.

## Validation, costs and acceptance status

The new suite passes 33 tests. Controlled positive LONG/SHORT fixtures run actual
analytical engines through native units, zones, structural stops, canonical nearest
objectives and normalized multi-target RR. Negative tests cover missing/invalid
sweeps, displacement/retests, triggers, zones, stops, RR, quotes, closures, missing
minutes and expiry. Tests cover future perturbation, delayed confirmation/chronology,
revisions/duplicates, frozen future anchors, repeated-candidate counting, canonical
component parity, source changes, quarantine and isolation guards.

The full credential-free repository regression suite passes **1,981 tests**, zero
failures/errors/skips, using disposable local UTF-8 PostgreSQL/Redis. The unchanged
frozen-selector suite passes **53 tests**, zero failures/errors/skips. Temporary
services stop after the harness completes. No tests incur Databento charges.

Two full final-source replays passed byte-for-byte equality before immutable
acceptance. Their status and hashes are recorded in
[machine acceptance evidence](gc-qualification-validation.json); private
licensed inputs and ledgers remain under `private-reports/gc-qualification-acceptance-v1/`.
Development probes are explicitly superseded and quarantined. No production
activation, publishing, approval, broker execution, push or deployment occurs.

Ledger SHA-256:
`7adea734578fc03768fb49840705df0c5f1a9e1258c6a0a8c6ee2ad33f37e5ed`.
Prepared-input SHA-256:
`036eba3d67420b80d5e3f6ea5d4c03f24bbf4c58cfc6e4d6e3e14778101849a3`.
New source files remain bound to their recorded individual hashes. The implementation
is saved as a local Git commit; its identity is provided with the task completion.

Cache action is reuse of verified admitted archives. No cost estimate or API
acquisition is needed for this run. Existing successful manifest estimates sum
to 1.488967996091 USD; old actual billing remains unknown. Existing credit/spend
accounting and quarantine mechanisms are not changed. General credit authorization
is acknowledged; any future purchase still requires an exact scope, reliable
estimate, cache/overlap review and explicit bounded budget under those controls.

## Limitations and next steps

1. Investigate missing/no-trade minute evidence and its derived H1/H4 consequences
   using existing archives first. Reacquiring the same OHLCV range cannot be assumed
   to create genuinely absent records. No synthetic recovery is authorized.
2. Any proposed shorter contiguous history, alternative closure/no-trade aggregation,
   H4 anchoring or freshness interpretation must be documented and reviewed as a
   separate data/research-policy change. The current conservative admission is
   deliberately explicit and does not claim exact historical production parity.
3. New historical quotes after October 7 19:30, replacement/expanded data windows,
   definition continuity or new datasets require concrete scopes, fresh estimates,
   applicable entitlements and bounded budget/receipts. Credit permission alone
   does not establish those request-specific controls.
4. Historical receipt/revision certification, broker XAUUSD comparison and any fill,
   exit, fee, account-sizing or outcome study require suitable independent evidence
   and separately specified methods. Current candidate output cannot establish
   trade win rates or FTMO performance.
5. Live data integration, production activation, GIL changes, trading policy,
   deployment, broker connectivity, publishing and approvals remain separately
   authorized work. This implementation provides no automatic activation path.
