# Monatise development continuity through Phase 5

Audited 12 October 2026. Repository: `Patrick8552/monatise-live`. Continue on
`research/databento-cme-foundation`; the last implementation commit is
`3ce3d384df03aeffd90efa79c7cf33bde9f320eb`. The preservation commit containing
this document is the Phase 6 starting point. Read the
[preservation report](audits/monatise-preservation-report.md),
[artifact inventory](continuity/artifact-inventory.json),
[exact acquisition manifest](continuity/acquisition-manifest.json) and
[private evidence recovery instructions](continuity/private-evidence-backup.md)
before acquiring or reconstructing anything.

This is a verified source/research record. It does not establish the currently
deployed version, live accounts, provider subscriptions or permission to trade.
Existing production behavior and all previously tracked files were left intact
by preservation. No main merge, deployment, new market-data download, live
connection, signal publication, approval or order occurred.

## Commit and phase map

There are two historical naming sequences. Earlier **Databento Phase 1/2** and
**broker Phase 3/4** branches precede the later CME foundation/Phase 3A/3B/4/5
sequence. Keep those meanings distinct.

| Milestone | Exact commit | Verified achievement and boundary |
|---|---|---|
| Canonical source baseline | `0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18` | Gold technical shadow, GC/options/basis validators and production safeguards; source identity, not a runtime attestation. |
| Frozen H1 F0 | `f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35` | Causal H1 episode/leg selector, constrained Fibonacci, immutable F0 shadow replay and opt-in shared seams. Preserve its separate checkout. |
| Earlier Databento foundations/acquisition | `0851fb7c7b5340e1e0f8d038e30215d6b15ed2ec` | Publisher identity, registry, guarded historical transport, native archive and replay; includes `6c05d6bd5f202be16ed0fe39729201055b7547fb`. |
| Earlier broker observation archive | `ce1ee530effe68080ac2e81d1a29b80200b0d54b` | Broker identity/observations and causal replay preparation; engineering evidence does not become authentic broker data. |
| Earlier broker retrospective research | `890b8f7deba379931a3ce7df5b6e6fb5760f2d73` | Read-only exporter source, retrospective dataset/F0/price-path infrastructure and tests. No authentic broker acquisition was completed. |
| Earlier native GC diagnostics | `a144db7f89e7bb3bb5748b83660d51243f69dc51` | Native GC identity/economics validation, including `0217211e1fd125cfa8a6baae472071b95b05e38d`; original acquisition/research context retained. |
| CME foundation | `3340bfc5bd136a3b9e51e6185a9f54222c4b4f37` | Dataset discovery, costs/budgets/cache, immutable layers, candles/rolls, advanced adapters and options input foundation. |
| GC qualification / Phase 3A | `0b3050d02afb563385f8a8f9286e2f56d87caeb8` | Actual analytical-engine qualification with native GC inputs and complete cutoff ledger; zero data-admissible cutoffs. |
| GC continuity / Phase 3B | `f784b268257a55fad31b4d85c88e7d75ffefca1a` | Session/gap forensics, bounded recovery planning and independent indicators; no invented gap fills or new acquisitions. |
| Institutional Phase 4 | `3007cbc96082a0c09078e3160482dcdd4cdd3af1` | Reusable multi-asset models/indicators, context mapping, options model diagnostics and isolated canonical previews. |
| Authentic Phase 5 | `3ce3d384df03aeffd90efa79c7cf33bde9f320eb` | Reviewed broker/cache input interfaces, native ES/NQ observations, bounded options coverage, full previews and deterministic isolated acceptance. New ES/NQ billing admission remains quarantined. |

The five earlier research branches are preserved on GitHub under their original
names: `codex/gold-h1-fib-f0-shadow`, `codex/databento-phase1`,
`codex/broker-xauusd-phase3`, `codex/broker-xauusd-phase4` and
`codex/databento-gc-research`. These branches preserve original source history;
they are not merged into the current research branch or main. Earlier broker
archive/retrospective modules are not all present in the current checkout.
Do not silently mix their versions.

## Canonical architecture and reusable components

| Responsibility | Source and reuse contract |
|---|---|
| Shared analysis | `monatise/engines/` and `application/hierarchy/`: structure/pivots, liquidity, sweeps, displacement/reclaim, zones, regime, Fibonacci, risk and target validation. Reuse actual engines rather than a parallel trading engine. |
| Gold/XAUUSD | `application/gold_analysis.py`, `gold_sessions.py`, hierarchy candles/risk/targets: H4 advisory, H1 direction, M15 causal setup/structural stop, later M5 confirmation, M1 refinement. See [canonical Gold source contract](xauusd-canonical-analysis.md). |
| Indices/stocks | `AssetHierarchyAnalysis`, exact FTMO registry and provider evidence; validated primary FlashAlpha positioning remains mandatory for index paths. Native ES/NQ research observations do not bypass it. |
| Cryptocurrency | `application/production_analysis.py`, `dynamic_analysis.py`, canonical registrations and CoinGlass adapters. Existing engine/source and fail-closed contracts remain authoritative. Phase 5 has no sufficient authentic crypto acceptance dataset. |
| Production controls | `application/ftmo_master.py`, `ftmo_execution.py`, `risk_policy.py`, hierarchy approval/lifecycle, `live/`, Telegram publication and signed MT5 bridge. Research never invokes or relaxes these. Existing deploy/runbooks are historical source, not instructions to deploy. |
| GC definitions/replay | `adapters/databento_gold.py`, `databento_identity.py`, `research/databento/registry.py`, `gc_fib/native_contract.py`: exact dataset/publisher/economic venue/contract, native timestamps/bytes and revision/roll handling. |
| Research acquisition/storage | `research/databento/acquisition.py`, `controls.py`, `archive.py`, `replay.py`: exact requests, reliable cost preflight, cache overlap checks, one-use durable reservations, quarantined failures, immutable native/normalized/derived layers. SQLite/local files meet current needs; earlier PostgreSQL CAS integration remains preserved. |
| GC qualification/continuity | `research/gc_qualification/`, `gc_continuity/`: bounded prefixes, session admission, actual-engine delegation, complete decisions and forensic evidence. Preserve rejection denominators. |
| Multi-asset observations | `research/institutional/models.py`, `normalize.py`, `native.py`, `native_index.py`, `native_window.py`, `cached_bundle.py`: immutable contract/source identity, separate clocks and source ordinals, exact cache/billing gates. |
| Indicators | `research/institutional/indicators.py`, `research/databento/advanced.py`: trade-only volume/VWAP/profile/POC, supported aggressor delta/CVD, visible book quantities/imbalance and sampled volatility. Capture scope/confidence/parameters and missing inputs remain explicit. |
| Context mapping | Existing `GoldBasisService` plus institutional `ContextMapper`/`mapping_report.py`: synchronized observations, source-bound reports, uncertainty/expiry and exact roll identity; context only. |
| Options | `application/gold_options.py`, institutional `options.py`/`options_coverage.py`: standard OG exact underlying/expiry/strike/C-P metadata, independent quote/OI/rate clocks, American IV diagnostics and selected-contract coverage. |
| Isolated acceptance | `research/institutional/phase5_runner.py`/bootstrap/worker: credential-free interpreter, network/process/production denial, pinned sources, two identical versioned replays and separate engineering examples. |

Gold CHoCH/failed-reclaim/structure outputs belong to existing engine contracts;
passing tests do not validate a new discretionary pattern. MBP-10/MBO interfaces
are engineering-tested and disabled by default. Individual MBO events are
preserved, but certified book recovery/queue reconstruction is not implemented.
Visible resting liquidity is neither executed volume nor institutional intent.
No infrastructure gap justified adding QuestDB, Grafana or Kafka. Existing
PostgreSQL/Redis usage is retained; preservation added no dependency.

## Genuine observations and frozen findings

GLBX.MDP3 is the only feed actually exercised here. Dataset means feed origin,
schema means record granularity and symbol means exact instrument/contract.
Other dataset extension slots are not implemented feeds or granted entitlements.

* **GCZ6:** publisher 1, instrument 41271, economic venue XCEC, USD per troy ounce,
  tick 0.1, size 100 ounces and monetary tick $10. Twenty-four complete native
  archives contain 23 definitions, 34,209 OHLCV minutes, 428,821 trades,
  6,100,133 MBP-1 records and 248 status records. Twenty-one unresolved minute
  gaps, excluded/revised observations and two failed quarantined acquisitions
  remain recorded. The exact warmup/evaluation/partition requests are in the
  [acquisition manifest](continuity/acquisition-manifest.json).
* **ESZ6:** publisher 1, instrument 10252, XCME, USD/IPNT, tick 0.25, contract
  size 50. **NQZ6:** publisher 1, instrument 261401, XCME, USD/IPNT, tick 0.25,
  size 20. Each has one definition and fifteen complete sample minute candles.
  Trades total 9,094 ES and 7,750 NQ in 5 October 2026 15:00–15:15 UTC.
  These are genuine partial-window diagnostics with unreconciled billing;
  admission and institutional scoring remain disabled.
* Native DBN market prices are already fixed-point normalized. Do not multiply
  them again by display factor. Native tick economics require
  `min_price_increment_amount / display_factor = min_price_increment * contract_size`.
  The corrected ES/NQ interpretation reused the cached ES definition; no paid
  download was retried.

The frozen expanded GC replay still records **557 assessments, 69 valid
constrained Fibonacci assessments and 12 distinct valid H1 episodes**. The 69
include warmup/exploratory observations; an earlier evaluation-only subset is
22 of 112. None is a verified trade, win, profitability result or win rate.
Original raw first-touch slots were null. Later analytical qualification has
4,049 scheduled/unavailable cutoffs and zero data-admissible cutoffs. Its 3,929
unadmitted engine diagnostics cannot qualify trades. The missing September 21
04:00–08:00 UTC H4 bucket has 239 native minutes; the 04:37 minute is unresolved
Class E. That finding is not a universal prohibition on independently reviewed
new scopes.

Phase 4 and Phase 5 captured GC normalization is unchanged. Captured GC sample
indicators are partial; three unknown-side contracts prevent full CVD. Fifteen
minutes of ES/NQ data cannot establish complete H1/H4 history or a full session.
Native prices stay native. Broker XAUUSD and index CFD prices must come from
genuine reviewed broker observations. Five synchronized fresh pairs and a
validated methodology are required for contextual basis mapping; no synthetic
spot or broker price is manufactured from futures.

See [replay hashes and evidence inventory](continuity/artifact-inventory.json).
The Phase 5 logical input digest is `6a43e6e372068be8f2ae42b91651e1100125a7d700c37e83822de72e68dd0d75`;
the serialized private `input.json` file digest is
`9e42a4f371969b39d3bef76c19668897ffa7086ed15ec885878b86aa157ee10c`.
They hash different representations. The saved Phase 5 validation's
`input_sha256` is the logical digest, not a byte hash of that file.

## Decisions and boundaries to retain

* Freeze `gold-fib-h1-structural-leg-v1` and its original expiry, causal H1
  origin/first-impulse endpoint, canonical confidence/2-ATR/age/distance gates,
  unchanged structural stop and nearest-objective RR guards. No M15 anchor,
  older-leg fallback or threshold relaxation to force qualification.
* Keep raw 1.272/1.414/1.618 slots, final validated targets and observed prices
  distinct. A touch is an observation; legitimate entry/stop/exit/fill/cost rules
  are prerequisites for a strategy outcome.
* GIL hierarchy remains **FlashAlpha primary**, **ThetaData validation where
  coverage applies**, **Unusual Whales independent confirmation where coverage
  applies**. GC futures-option coverage of the latter two is unverified.
  Databento supplies raw exchange observations, not precomputed GEX, gamma flips
  or dealer inventory. GIL remains disabled in the GC-only F0 experiment.
* American Greek stability/certification, signed exposure assumptions and
  complete-chain coverage remain missing. Selected published OI is not a complete
  chain or dealer positioning; missing OI stays null, including incomplete subtotals.
* Native event/receive, original observation availability, retrieval and local
  admission clocks stay separate. Final historical download vintage is
  retrospective assumed availability, never live point-in-time certification.
* Every new acquisition needs a fresh exact-scope estimate, local/overlap cache
  review, license/credit/expiry/budget review and request-bound authorization.
  Credit is tracked separately from API spending/cash. Estimates/reservations
  are not settled charges. Unknown billing keeps admission/reservations pending.
  This preservation task spends zero provider credit and downloads no new data.
* Existing source review inputs are a trust boundary. The research guard is
  defense in depth for trusted code, not a hostile-code OS sandbox.

The [archived design index](research-archive/README.md) preserves the original H1
specification and an older empty extension-study protocol. Those dated documents
contain proposed features and old readiness statements. Use this continuity
record and actual source commits to determine what was later implemented.

## Reproduction and Phase 6 requirements

1. Clone/fetch the preserved research branch and pin its preservation commit.
   Fetch the exact frozen branch and create a detached read-only source checkout:

   ```sh
   git fetch origin codex/gold-h1-fib-f0-shadow
   git worktree add --detach work/gold-h1-f0 f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35
   ```

   Do not merge the frozen branch into main. Use its pinned path only through the
   existing research interfaces. Earlier broker source is on its original branches.
2. Reuse `pyproject.toml`/`uv.lock`, including optional `gold-data` SDK 0.87.0.
   Acceptance used databento-dbn 0.70.0 and Python 3.14.6; CI declares Python 3.12.
   Preserve the runtime version with each replay, rather than assume identical
   cross-version behavior. Existing safe test command, with local service binaries:

   ```sh
   .venv/bin/python scripts/test_cme_offline.py \
     --output private-reports/phase6-tests-v1 --h1-checkout work/gold-h1-f0
   ```

   It creates disposable loopback PostgreSQL/Redis and a paper server, strips
   credentials and stops services. Never substitute production DSNs.
3. Recover private evidence from the authenticated encrypted snapshot, then
   recheck all source/request/native/replay hashes. GitHub alone cannot reproduce
   licensed native replays. Configure restored paths explicitly; do not download
   replacement data merely because a machine's path differs. Acquisition results
   with incomplete transport or unknown billing keep their quarantine status.
4. Start Phase 6 with definitive per-request GC/ES/NQ billing reconciliation and
   off-device backup/key escrow verification. Do not retry or redownload any of
   the thirty complete archives. Acquire only demonstrated uncovered scope under
   fresh cost/credit-only authorization and reliable account-side protection.
5. Obtain reviewed genuine broker exports: server/instrument/specifications,
   historical session/DST calendar, original availability and synchronized
   Bid/Ask where required. The current continuous five-timeframe importer rejects
   natural session gaps; any calendar-aware expansion requires validation.
6. Investigate Class E GC omissions independently using permitted cached/status
   evidence; preserve prior results and do not synthesize candles. Lock any
   performance cohort and fill/cost model before evaluating strategy outcomes.
7. Supply a bounded reviewed OG underlying/expiry/strike set, published OI,
   quotes/rates and exercise/settlement assumptions for options research. Certified
   American Greeks, signed GEX/flip or GIL integration remain separate work.
8. Depth/MBO acquisitions, live entitlements/streams/reconnect ownership,
   production certification, deployment, Telegram changes, execution/risk changes
   and trading activation each require their own explicit authorization and
   acceptance. No preservation approval grants those permissions.

No claim is made that every historical prototype or external cloud artifact was
audited. The bounded local discovery, reviewed branch coverage, private backup
status and remaining gaps are recorded in the preservation report.
