# Phase 4 — isolated broker Gold historical research foundations

Status: engineering implementation complete; authentic acquisition is not authorized or performed. This branch must not be merged/deployed as a trading integration. The H1 selector remains `gold-fib-h1-structural-leg-v1`; GIL-dependent arms remain disabled.

## Verified sources and isolation

| Source | Verified commit | Result |
|---|---|---|
| GitHub main, checked before development and again afterward | `0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18` | No newer remote main changes found |
| Phase 3, `codex/broker-xauusd-phase3` | `ce1ee530effe68080ac2e81d1a29b80200b0d54b` | Clean source; parent of this isolated branch |
| Phase 2 dependencies | `0851fb7c7b5340e1e0f8d038e30215d6b15ed2ec` | Existing Python 3.12.14 runtime reused; pip check passed |
| Isolated H1 research | `f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35` | Clean pinned checkout; no selector/PIT runner changes |

Development branch: `codex/broker-xauusd-phase4`. No production files, execution EA, provider configuration, risk limits, approval routes, source contracts, dependency manifests or production database migrations changed. No broker credentials, broker connections, historical downloads, polling, Telegram actions, orders, deployments, merge, push or Databento purchases were used.

The H1 research checkout already contains opt-in analytical helpers. Phase 4 does not copy or cherry-pick them into production. A separate Python `-I` subprocess loads the verified pinned checkout, extends only its research-package search path with the Phase 4 modules, and runs the new retrospective adapter. Its environment contains only PATH/LANG; no DSN, API key or broker settings are forwarded. This is a code/transport isolation boundary, not an OS network sandbox. Source review and tests establish that the invoked analytical path has no broker/publication transport.

## Existing components reused

- `monatise/application/hierarchy/broker_candles.py:50`, `BrokerCandleService`: verified registered-instrument/account-bound recent-window infrastructure. Its live request/response interface is unchanged and is not called by this task.
- `mt5/Experts/MonatiseFTMOBridge.mq5:1241`: existing recent `CopyRates(symbol, frame, 0, limit, rates)` infrastructure. The new standalone script reuses native MqlRates/CopyRates semantics without changing this EA or its commands.
- `monatise/application/gold_analysis.py:19`, `GoldPolicy`: canonical technical Gold requires broker candles. GC and options are separate explicit contracts, not implicit substitutes.
- `monatise/application/gold_analysis.py:44`, `sweep_reversal`, and `GoldLayerEvaluator`: unchanged H1 directional authority, M15 causal Gold pattern, M5 trigger, M1 entry and M15 stop preparation. H4 remains advisory.
- `monatise/application/gold_sessions.py:26`, `GoldSessionCalendar`: identity, sessions, historical offset eras, native wall-clock normalization and latest expected closed candle.
- `monatise/application/hierarchy/candles.py`, `CandleBoundaryNormalizer`: canonical candle boundaries, geometry/content hashes and default grace. The new dataset derives the grace from this component, currently ten seconds.
- `monatise/engines/market_structure/engine.py`, `MarketStructureEngine`: authentic structural/pivot objects; no independently invented pivot algorithm.
- `monatise/engines/fibonacci_liquidity/engine.py`: existing Fib validation, confluence, constrained anchors and raw extension calculations via the pinned H1 checkout.
- Phase 3 `BrokerIdentity`, `BrokerObservationArchive`, `PostgresDocumentStore`, immutable research schema and admission receipts.
- Pinned H1 `CaptureGoldLayerEvaluator`, `H1ParentSnapshot`, `GoldSetupSeed`, episode adapter/selector, `H1FibF0`, minimum-RR/nearest-objective validation and clustered diagnostics. All run unchanged.

No separate Exness historical API was found in the reused broker-candle service. Native broker Gold names such as XAUUSDm can be explicitly represented; that does not verify Exness coverage or authorize connecting to it.

## Exact added and modified files

Modified research files:

- `monatise/research/broker_xauusd/models.py`: adds `UNKNOWN_OR_UNVERIFIED`.
- `monatise/research/broker_xauusd/replay.py`: prevents unknown evidence from being PIT-eligible and adds an explicit blocker. Historical/PIT proof requirements remain restrictive.
- `monatise/research/broker_xauusd/archive.py`: supports an opt-in selective admitted reader; existing stores retain their original namespace-read behavior.

Added:

- `monatise/research/gold_retrospective/__init__.py`: fixed source/policy identifiers.
- `acquisition.py`: bounded calendar-derived page planning, local export inspection, exact-wire custody and offline archive import.
- `dataset.py`: coverage, frozen download vintages, historical units review, explicit availability assumptions and integrity checks.
- `runner.py`, `bootstrap.py`: pinned-source subprocess isolation.
- `worker.py`: separate causal retrospective replay, setup capture, frozen F0 assessment and lifecycle exclusions.
- `outcomes.py`: independent hypothetical reference-price path evaluation.
- `comparison.py`: canonical/raw-Fib/resolved-F0 comparisons and clustered summaries.
- `storage.py`: opt-in selective research-table reader.
- `benchmark.py`: bounded read measurements.
- `cli.py`: explicit offline plan/inspect/import/dataset/replay/outcome commands.
- `research/mt5/MonatiseGoldHistoricalExport.mq5`: standalone manual script source. Not compiled, installed or run.
- `research/phase4_engineering_pilot.py`: reproducible synthetic pilot and optional private PostgreSQL benchmark.
- `tests/research/test_gold_retrospective.py`, `tests/research/test_gold_retrospective_postgres.py`: 51 new tests.
- This report/runbook.

The module names listed without a directory are under `monatise/research/gold_retrospective/`.

## Acquisition and provenance

`acquisition_plan` requires an exact broker/account/server/native Gold symbol, reviewed symbol mapping reference and reviewed calendar. It supports all five native timeframes, at most 31 days per plan and at most 240 bars per page. Pages split at sessions and historical offset eras before conversion to broker wall epochs. Each page includes expected native opens, exact bounds and an immutable ID. Connection/download/execution flags remain false.

The standalone MT5 script requires manually entered account/server/symbol/page/date bounds and a separate approval reference. It refuses unexpected identity, non-Gold symbol prefixes, unsupported timeframe, excessive span, excessive rows and an existing destination file. It calls the date-range overload once, preserves native broker timestamps, OHLC (17 significant digits), tick volume, real-volume metadata and spread points. It records CopyRates count/error, SERIES_FIRSTDATE, terminal capture time and current unit metadata. There is no login, retry timer, trade, execution command or automatic transport. An approval-reference string is an audit field, not an independent authorization verifier.

CopyRates itself may initiate broker history downloads, return partial available history or fail under terminal/broker history limits. Running this script therefore still needs separate exact acquisition authorization. See [MetaQuotes CopyRates](https://www.mql5.com/en/docs/series/copyrates) and [MqlRates](https://www.mql5.com/en/docs/constants/structures/mqlrates).

Offline inspection reports account/symbol/range mismatch, malformed OHLCV, missing/duplicate/unordered bars, off-grid/native timestamp errors, terminal errors, unknown history start and truncation. Missing history is retained and reported; replay fails closed on required gaps. It is never filled from synthetic candles or GC.

Import preserves the original file bytes as base64 plus SHA-256 in append-only custody, then records parsed native rows in the existing archive. Local receive is sampled after reading; capture is preserved as supplied. Archive admission is post-write and immutable. Exact-byte reimports retain first receive/admission and are one observation; changed exports form distinct vintage IDs. An orphan can be explicitly retried with its original metadata. Evidence-class/source-reference conflicts fail closed. Invalid input is quarantined and cannot feed analysis.

Evidence classes are acquisition/trust labels, not self-authenticating claims:

| Class | Treatment |
|---|---|
| ENGINEERING_SYNTHETIC | Artificial fixture only |
| RETROSPECTIVE_HISTORICAL_DOWNLOAD | Download vintage; original observation/finalization unavailable; independent source review required before market replay |
| POINT_IN_TIME_OBSERVATION | Existing restrictive preparation path; capture proof still requires independent review |
| UNKNOWN_OR_UNVERIFIED | Quarantine/descriptive evidence; never PIT/F0 admission |

Terminal TimeGMT depends on the terminal host's clock/time settings and is not independently authenticated UTC. Historical native candle offsets come from the reviewed era schedule, never today's broker offset. Ambiguous fall-back wall times fail closed. Capture, receive and admission ordering is validated but does not prove clock accuracy. See [MetaQuotes TimeGMT](https://www.mql5.com/en/docs/dateandtime/timegmt). Wire hashes protect integrity after receipt, not authenticity of the account or source.

Current point/tick/spread metadata is explicitly capture-date metadata. Replay requires a separate broker-identity-bound historical units manifest with dated reviewed eras. A positive native M1 spread field can supply a bar-level estimate using reviewed historical point units; it is not an executable quote or cost model. Missing/zero spread is unavailable for genuine research. Explicit engineering spread assumptions are synthetic-only.

## Separate retrospective replay contract

`build_dataset` selects the latest admitted version per native timeframe/open at a frozen archive cutoff. Revisions, exclusions, provenance and original clocks remain explicit. Conflicting revisions sharing an admission timestamp are excluded until a later unambiguous vintage exists. Forming-at-capture rows cannot become finalized history. Dataset windows are bounded to 90 days and 200,000 rows.

A genuine retrospective dataset requires an independent review reference bound to source-batch hashes, row hashes, units hash and calendar fingerprint. This binding records human/source review; it is not a cryptographic source attestation. There are no reviewed genuine records from this task.

Assumed historical availability is scheduled close plus the canonical grace. Original observation availability and original finalization observations remain null. The normalized engine input's two-confirmation flag is explicitly an assumption about a final download vintage, not two observed captures. Output retains the engine checksum/internal label while prominently marking retrospective assumed availability and `pit_verified=false`.

The worker enumerates all expected M1 decision times, including missing data, with at most 5,000 decisions per run and no silent sampling. Each decision sees only the known native prefix, restricted to the existing engine history limit. Latest expected bars and internal session-grid gaps are checked. Closure gaps are legitimate calendar gaps; missing regular bars revoke eligibility. Input histories and available cutoffs are hashed in every admission. Required histories derive their minimum size from existing RegimeRequest/LiquidityRequest defaults.

The parent snapshot, active H1 episode association, confirmed A/B pivots, first impulse endpoint, 2-ATR rule, structure confidence, anchor age, target distance ceilings, confluence, spacing and nearest-objective/minimum-RR rules are unchanged. There is no M15 anchor or alternative/older H1 fallback. Lower timeframes retain setup, trigger, entry and structural-stop roles.

One original assessment is retained per setup association. H1 anchors and original candidate provenance remain frozen. Rejected and target-independent seeds remain included. Parent-direction loss, M15 supersession, original expiry and required-data loss bound the research lifecycle; data failures reset cached usable contexts. The existing canonical evaluator determines structure/setup state. The outcome evaluator separately observes the original stop threshold. No new discretionary invalidation or stop rule is added.

Important limitation: final-vintage OHLC can contain historical revisions that were not known live. Causal candle/pivot access within that vintage does not establish verified live point-in-time causality. The original observation archive runner is unchanged and still rejects retrospective evidence. Genuine PIT readiness is blocked by missing original availability/finalization/authenticity evidence.

## Outcome policy: gold-price-path-reachability-v1

This is a price-path observation model, not a strategy execution model. It does not assume entry was filled, position sizing, pending-order fill, partial realization, slippage, commissions or profits.

For each retained seed it evaluates the original entry/stop reference until original expiry or first recorded invalidation. Native M1 bars crossing assessment/expiry boundaries are excluded. Missing bars are reported; partial windows do not imply known first-event order. Same-bar TP/SL is explicitly ambiguous. Duplicate/off-calendar/invalid native bars fail closed.

LONG ordered-quote exits inspect Bid; SHORT exits inspect Ask. Optional quote inputs require source references, finite Bid/Ask and unique ordered timestamp/sequence keys. A reference does not attest stream completeness, which stays explicitly unknown. An observed tick does not prove a fill or complete expiry coverage.

Raw 1.272/1.414/1.618 thresholds, including rejected candidates, are observed separately from resolved F0 targets and canonical final targets. A high/low threshold crossing is not proof of an exact print or executable fill. Stop-before-target, observed target-before-stop, ambiguity, missing/no path, wrong side and unavailable candidate identities are explicit. No target is invented when a plan is absent.

MFE/MAE are maximum observed price excursions from a hypothetical entry over the defined window, expressed in USD and original R. They are not executed-trade MFE/MAE, and incomplete paths give lower bounds. Raw touches after an observed stop are retained as raw path information but classified stop-first. Session/regime groups and H1 episode clusters retain all seeds; clustered counts are not independent trade samples. Missing M1 decision times remain in the denominator. Session counts refer to reviewed sessions intersecting the assessment window, not warm-up history or proven real trading activity.

## ENGINEERING TEST RESULTS

Final focused run: **99 passed**, zero skips (11.47 seconds). This comprises the existing 48 archive cases and 51 Phase 4 additions, including actual private PostgreSQL process restart, selective reader equality, append-only guards inherited from Phase 3, offline CLI import, research dataset preparation and future-price perturbation isolation.

Full final Phase 4 regression: **1,962 passed, 14 skipped**, zero failures (43.83 seconds). JUnit artifact records every case. Skips are existing environment-dependent integration cases: seven application persistence PostgreSQL/Redis cases, one live-user PostgreSQL case, one multi-TP local PostgreSQL case and five webhook PostgreSQL cases. Their explicit test service URLs were not configured. Private research PostgreSQL tests ran successfully; no production service URLs were supplied.

Unchanged pinned H1 suite: **53 passed**, zero skips (44.81 seconds), including selector latency/geometry/range/age, causal pivots, original expiry, constrained-path/default parity, zero/one/two/three-target behavior, duplicate/freeze/governance and network isolation checks.

A separate read-only default fingerprint compared Phase 4 canonical default outputs with the pinned H1 checkout for synthetic LONG and SHORT inputs. Canonical result, default Fib assessment, default target evidence and structural-risk outputs were byte-identical. LONG SHA-256: `aaf39a7c2511566979581c2f17ee36c2cbcbaa9bbd8059c6ba9a06dc3046762d`; SHORT: `c2561c31323f021ce7e804f5e204f548fabb10de1ddbb01d467e6c7f2c723643`. Hashes are also in `default-parity-results.json`. This supports unchanged default behavior for those fixtures, not proof of every possible input.

During development, assertions exposed the legitimate nearest-objective rejection, a metadata/coverage reporting edge case and a PostgreSQL driver percent-placeholder issue. They were corrected without changing the selector/gates. A private restart test harness was interrupted once because its server inherited captured output pipes; a dedicated restart log fixed it. An empty libpq service argument was also removed; the CLI instead refuses inherited PG environment settings and disables password-file lookup. The final runs above are clean.

### Synthetic F0 pilot

Four independently labeled artificial cases, each assessed at 2026-10-05 15:04:10 UTC. These dates are fixture timestamps, not downloaded market history. The artificial calendar includes 24-hour engineering sessions and is not a broker schedule.

| Case | Seeds | Active episode | A valid | B valid | Constrained Fib valid | Final eligible targets | Outcome |
|---|---:|---:|---:|---:|---:|---:|---|
| LONG | 1 | 1 | 1 | 1 | 1 | 0 | NEAREST_OBJECTIVE_RR_REJECTED |
| SHORT | 1 | 1 | 1 | 1 | 1 | 0 | NEAREST_OBJECTIVE_RR_REJECTED |
| Unconfirmed B | 1 | 1 | 1 | 0 | 0 | 0 | B_UNCONFIRMED_AT_PARENT_CUTOFF |
| Origin latency | 1 | 1 | 1 | 0 | 0 | 0 | H1_LEG_GEOMETRY_REJECTED |

Both valid legs have USD 80 range, H1 ATR 9.75, range 8.205128 ATR. LONG anchors are A=2450 / B=2530; SHORT is the reflected A=2550 / B=2470. Confirmed B latency is 10,810 seconds (the original right-window confirmation plus grace). LONG raw candidates are 2551.76 / 2563.12 / 2579.44; SHORT 2448.24 / 2436.88 / 2420.56. Their reference distances are USD 46.76 / 58.12 / 74.44 and raw RR about 2.381 / 2.959 / 3.790. Three raw candidates pass initial candidate admission in each valid case, then the nearer-objective gate rejects the final ladder. Canonical also rejects for TP1 RR; neither arm has a final target plan. The candidate identities and decision rejection remain explicit.

Across these separate cases: four seed events; four identified case-specific H1 clusters; four valid A; two valid B; one B-latency rejection; one geometry rejection; two valid constrained assessments; four zero-target results; no one/two/three-final-target result; two nearest-objective rejections. The small pilot has zero 2-ATR, confidence, age, expiry or distance-ceiling rejections. Those gates are tested in the unchanged H1 suite; zero pilot counts are not estimated market rates. Cases must not be pooled as independent market samples.

Pilot input includes roughly 65 H1 and native fixture histories for the other four timeframes. Its wider warm-up coverage report intentionally exposes missing M1/M5/M15 history rather than synthesizing it. The assessment uses complete required trailing histories. No subsequent M1 bars exist after the pilot decision; reachability, MFE/MAE, expiry success and profitability therefore remain unavailable. Standalone synthetic outcome tests exercise stop-first, same-bar ambiguity, missing/partial paths and ordered Bid/Ask separately.

## AUTHENTIC MARKET-DATA RESULTS

**No authentic broker records acquired.** Broker/account/native symbol, genuine available history, historical date/timeframe coverage and broker-specific history limits remain unavailable. No broker calendar or historical unit eras have been certified for a real acquisition. No actual MT5 script compile/export has occurred.

## RETROSPECTIVE RESEARCH RESULTS

The separate mode is engineering-ready for a reviewed authentic download vintage. No real-market retrospective selector availability, target eligibility/reachability, session/volatility differences, stop-first frequency or MFE/MAE distribution can be reported yet. There is no performance evidence or policy-improvement claim. The final synthetic pilot is not retrospective market validation.

## VERIFIED POINT-IN-TIME RESULTS

No verified PIT market dataset or result exists from this task. The existing runner/source checks remain unchanged. Actual historical availability/finalization cannot be recovered from a download merely by assuming close-plus-grace. Source authenticity, clock calibration and independently verified original observations remain blockers.

## Archive scalability

A bounded private PostgreSQL workload stored 100 synthetic batches × 60 M1 rows, selecting ten at a cutoff. Table plus indexes occupied 1,286,144 bytes. Ten selected batches serialized to 495,980 JSON bytes. Three measured samples per reader:

| Reader | Median | Minimum | Maximum |
|---|---:|---:|---:|
| Original namespace scan | 53.283 ms | 53.262 ms | 53.899 ms |
| Selective admitted join | 5.415 ms | 5.388 ms | 5.486 ms |

Exact batch equality was asserted. Median ratio was about 9.84× for this workload. This is not a broker throughput, long-term scaling or production performance claim. Repeated artificial OHLC compresses unusually well; the workload excludes extra wire-custody documents. Do not project its compressed bytes per row directly onto genuine data.

The justified change is an opt-in join over receipts and batches in the existing research table, filtered by typed UTC admission cutoff. Existing namespace/key primary keys are reused. No new table, index, partition, migration, QuestDB or Grafana was introduced. Incomplete orphan batches stay excluded; selected receipts/body/raw hashes are revalidated. The database was actually restarted in a private test, then hashes/records were re-read unchanged.

Growth risks remain overlapping history vintages, JSON duplication and exact-wire custody/base64 overhead. Actual later acquisition should measure total namespace/custody bytes, selected/read amplification and p95 over representative large workloads before new indexes/partitioning. These are deferred workload decisions, not current additions.

Backup recommendation: dedicated research database/native export snapshots plus hash manifests; test restore into a fresh research cluster and revalidate admission/body/wire hashes and dataset outputs. No automatic retention deletion or backup service was configured. PostgreSQL append-only triggers protect ordinary UPDATE/DELETE/TRUNCATE, not privileged administrator bypass or physical tampering; hashes require an independently retained trusted manifest to detect coordinated rewriting. WORM, signed capture attestation, external time attestation and backup/restore automation are not implemented.

## Operator workflow and next milestone

Use the existing Phase 2 Python runtime; no dependency installation is needed. From this branch:

```text
python -m monatise.research.gold_retrospective.cli --help
python -m monatise.research.gold_retrospective.cli plan --identity IDENTITY.json --calendar CALENDAR.json --mapping-reference REVIEW_REFERENCE --start UTC_START --end UTC_END --output NEW_PLAN.json
```

Extract one exact page into PAGE.json. Before any terminal use, obtain approval identifying broker, account/server, native Gold symbol, exact UTC range, reviewed historical offsets/sessions and manual one-shot MT5 export method. The current plan is not authorization. Compile/review the source in the approved terminal only after that authorization; do not attach it to the execution EA. Run one approved page with explicit bounds and transfer its export manually. Review partial history and broker limits before requesting any retry.

Offline steps, with fresh output names:

```text
python -m monatise.research.gold_retrospective.cli inspect --identity IDENTITY.json --calendar CALENDAR.json --page PAGE.json --export EXPORT.json --output QUALITY.json
python -m monatise.research.gold_retrospective.cli archive-import --identity IDENTITY.json --calendar CALENDAR.json --page PAGE.json --export EXPORT.json --source-reference REVIEW_REFERENCE --local-pg-socket LOCAL_RESEARCH_SOCKET --port PORT --database RESEARCH_DB --user RESEARCH_USER --output IMPORT_RECEIPT.json
python -m monatise.research.gold_retrospective.cli dataset --identity IDENTITY.json --calendar CALENDAR.json --start UTC_START --end UTC_END --cutoff FROZEN_ARCHIVE_CUTOFF --units HISTORICAL_UNITS.json --source-review SOURCE_REVIEW.json --evidence-kind RETROSPECTIVE_HISTORICAL_DOWNLOAD --local-pg-socket LOCAL_RESEARCH_SOCKET --port PORT --database RESEARCH_DB --user RESEARCH_USER --output DATASET.json
python -m monatise.research.gold_retrospective.cli replay --input REPLAY_REQUEST.json --h1-checkout PINNED_H1_CHECKOUT --output REPLAY.json
python -m monatise.research.gold_retrospective.cli outcomes --replay REPLAY.json --dataset DATASET.json --output OUTCOMES.json
```

`archive-import` optionally accepts a separately reviewed `--capture-calendar` when present-day capture lies outside historical calendar coverage. The local research schema must already be provisioned; the CLI does not run migrations. It accepts only an existing explicit Unix socket, never a production DSN, and refuses inherited PG environment variables. It uses no password file. No CLI command can connect to a broker or download market data.

First prepare an immutable draft dataset by omitting `--source-review`. Independently review its actual export/account provenance, source batches, rows, calendar and historical units. A review manifest contains `review_reference`, `source_batches_sha256=digest(draft['source_batches'])`, `rows_sha256=digest(draft['rows'])`, `unit_manifest_sha256=digest(draft['unit_manifest'])` and the draft's `calendar_fingerprint`. Merely generating these hashes is not source review. Rebuild under the same frozen cutoff with that manifest into a new filename; the worker refuses the unreviewed genuine-data draft.

Identity JSON uses BrokerIdentity fields `broker`, `account_id`, `server`, `broker_symbol` and canonical `symbol="XAU/USD"`. Historical units JSON has schema `gold-historical-units-v1`, that exact identity, and `eras` with UTC `from`/`until`, reviewed positive `point`/`tick_size` and `review_reference`. Broker calendar JSON remains the existing `gold-broker-sessions-v1` reviewed account/server/symbol/offset/session contract. No real values for these manifests were fabricated during Phase 4.

Replay request contains the full dataset plus `assessment_start`, `assessment_end` (exclusive) and optional `maximum_decisions`. The first research window must include sufficient prior native warm-up and subsequent price-path coverage through expiry; otherwise exclusions must remain visible. Record the full cohort/window before reviewing outcomes. Do not cherry-pick successful episodes or revise v1 during the run. Any alternative definition becomes a separately approved v2 on the same fixed cohort.

Reproduce synthetic engineering artifacts with:

```text
PYTHONPATH=. python research/phase4_engineering_pilot.py --h1-checkout PINNED_H1_CHECKOUT --output NEW_OUTPUT_DIRECTORY --benchmark
```

The benchmark flag uses an existing local PostgreSQL installation to create/stop/delete a private temporary cluster. The pilot's test fixtures are deliberately artificial; the script must not be used as a source of broker data.

Next milestone: separately authorized bounded authentic export and source/calendar/units review, then a preregistered v1 retrospective cohort with full expiry/outcome coverage and episode clustering. Preserve FlashAlpha as the GIL primary provider and keep all GIL target modifications disabled. Databento GC remains a separate futures dataset; it cannot substitute for broker XAUUSD. Continuous observation/PIT acquisition, fills/cost modeling and production integration each require separate work and authorization.
