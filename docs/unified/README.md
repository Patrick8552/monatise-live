# Offline use and reproduction

This module is an opt-in shadow research tool. It is not wired to production analysis, Telegram, broker approval or live data collection. It does not read a data API key or buy/download data.

From the prepared worktree, with an existing Python environment containing pytest and Databento DBN file-reading support:

```sh
python -m pytest tests/research/unified -q
```

Private archive integration tests are enabled only when the already-existing manifests/data are available:

```sh
MONATISE_UNIFIED_MANIFEST_ROOT=/absolute/path/to/manifests python -m pytest tests/research/unified -q
```

Inventory and replay:

```sh
python -m monatise.research.unified inventory --manifest /absolute/path/to/native-manifest.json --output /absolute/path/to/inventory.json
python -m monatise.research.unified replay --manifest /absolute/path/to/native-manifest.json --database /absolute/path/to/state.sqlite --output /absolute/path/to/replay.json
```

The second command uses unresolved `Policy()` by default, so action is blocked with POLICY_NOT_READY. To evaluate documented exploratory hypotheses, supply a frozen policy JSON; do not treat that as production readiness:

```sh
python -m monatise.research.unified compare --manifest /absolute/path/to/event-time-manifest.json --policy /absolute/path/to/policy-executed_bar_participation.json --flow-policy /absolute/path/to/policy-aggressor_robust.json --database /absolute/path/to/comparison.sqlite --output /absolute/path/to/comparison.json --split-ns 1793721600000000000
```

This comparison includes A-only, B-only, C-only, unified dominance and the registered earliest-trigger baseline for the bar-participation variant, plus a separate unified robust-aggressor variant. They share immutable feature computation, never mutable experiment state. The initial split is retrospective, not untouched OOS. Do not reuse a database with a changed policy, source manifest or code hash; use an explicitly new experiment/database and record the trial.

Source manifests bind native definition and preflight files, full historical response receipts, raw capture receipts/hashes, source controls, calendars, news coverage/availability, clock mode and any modeled spread. Relative examples do not grant data access. Runtime source files remain private, read-only inputs. No package install or data-acquisition command is performed by this CLI.

Read the `decisions`, `observations`, `events`, `opportunities`, `classifications`, `selections`, `outbox` and `position_events` tables for the complete audit trail. Selected plans are immutable. Outbox records are local-only; acknowledgement does not send a message or order.

The BTC-only Databento review and updated source/outcome modes are documented in `btc-databento-guidance-2026-11-04.md`. `readiness` inspects an existing BTC manifest without acquiring data. `compare` now honors `--start-ns`/`--end-ns` and records the bounded evaluation window. Explicit `NATIVE_L1` outcomes require observed quote coverage; no OHLC fallback is allowed in that mode. Selected plans freeze the complete policy and contract identity for outcome evaluation.

Installed validation environment used Python 3.14, Databento 0.90.0 and DBN v3 support. The repository's existing production/optional dependency pins were not changed. Compatibility beyond the tested environment is not claimed.
