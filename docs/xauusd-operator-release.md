# XAU/USD operator and release notes

The user authorized merging and deployment on October 5, 2026. Keep Gold analytical publication and execution disabled until the outstanding live certification is completed. The new route is shadow-only with no activation knob. Manual operator-entered trades and previously approved management retain the existing broker checks.

## Local reproduction

- `uv sync --extra dev`: normal installation; optional SDK is unnecessary for other markets.
- `uv sync --extra dev --extra gold-data`: pinned SDK for offline DBN-record compatibility tests.
- `uv run pytest -q`: full Python suite. Postgres/Redis integration tests need dedicated test URLs, never production URLs.
- `uv run pytest -q tests/test_gold_technical_first.py tests/test_databento_gold.py tests/test_gold_options.py`: deterministic Gold fixtures.
- `uv run python -m compileall -q monatise`: import/syntax validation.

Fixtures are synthetic/reference mathematics, not licensed historic performance data. No lawful historic comparative sample was supplied, so no ablation, profitability or provider-superiority result is claimed.

## Required capability and separately authorized certification

1. GitHub access is restored and PR #125 is available for review. Reconcile a changed upstream HEAD without force-pushing. CI is local/offline testing, paper Docker smoke and UI validation; this branch does not alter CI, Render, deployment or secrets.
2. Compile/review EA 1.24 in MetaEditor and test history capability 3 on an isolated account. The existing v1 index transport stays supported. Certify exact account/server/broker symbol, signing/replay, point/tick units and session close.
3. Configure a reviewed broker schedule using `MONATISE_GOLD_SESSION_MANIFEST`. The implemented schema `gold-broker-sessions-v1` binds account/server/XAU/USD, source/version, bounded UTC validity, contiguous UTC offset eras and explicit UTC trading intervals. Supply authoritative broker DST/holiday/maintenance data; do not copy the synthetic test schedule. EA 1.24 sends `t_broker` independently of the legacy adjusted `t`; the server normalizes each historical timestamp by its era. Ambiguous/nonexistent broker wall times, expired schedules, missing raw times, current-offset mismatch and session mismatch fail closed. The schema is demonstrated in `tests/test_gold_sessions.py`. Without a manifest, the current-offset path remains uncertified and cannot qualify. Verify actual broker close/finalization semantics before live certification.
4. Obtain a separately approved Databento GLBX.MDP3 COMEX entitlement and verify dataset/publisher metadata. Check commercial/non-display/redistribution and derived-output permissions. Do not assume personal or historical access permits customer-facing live streams. This work purchased nothing and accepted no exchange terms.
5. Finish production definition discovery, contract-roll selection, session/status ingestion, complete replay watermark, trade correction and reconnect/backoff handling. Wire one owned stream/cache into the coordinator; never one stream per scan. Test backpressure/gaps using isolated replay before paid live use.
6. Finish American Greek numerical certification, complete OG/weekly convention coverage, point-in-time chain/OI publication normalization, signed-model assumptions and Gold GIL integration. Keep unsupported analytics null and dependent strategies disabled.
7. Wire contract-specific basis sampling and persistent dependency/proof invalidation into the existing control plane. Test restart, supersession, final delivery and managed pending revocation before adding any execution path.
8. Add a full positive end-to-end real-engine qualification fixture and live-replay certification beyond the current positive real setup/trigger plus negative RR integration. Run comparative ablations only on lawful identical point-in-time periods with costs and out-of-sample checks.
9. Review/authorize technical-only policy activation **separately**, retain all existing risk ceilings and native quote/approval protections, and then follow the repository release process. Passing offline tests is not deployment or certification.

## Safe rollback

Pause Gold trade-publication paths before reverting a deployed implementation. Do not revert into an options-only Gold approval path while publication remains active. The broad existing futures scanner can be paused with `MONATISE_FTMO_FUTURES_SCAN_ENABLED=false`; coordinate the effect on indices. Keep kill-switch/manual approval/account identity/risk safeguards in force. Verify no old Gold signal can publish approval controls or obtain a managed pending lease after rollback. No rollback or production configuration change was performed here.

## Current certification and deployment status

On October 5, 2026, all existing tests passed with the optional SDK and isolated local PostgreSQL/Redis: 1,741 passed, zero skipped before the schedule additions. Final results for the schedule/history-only additions are recorded in `docs/audits/xauusd-certification-2026-10-05.md`. PR #125's first CI run passed Python (1,739 passed, two environment skips), paper Docker smoke, responsive UI and Lighthouse checks.

Render's existing workspace is suspended for non-payment. Deployment cannot be completed until the owner restores it; no billing transaction was attempted. Windows App's saved Monatise OVH VPS failed to connect with error 0x204. The prop account has not been accessed, the EA has not been compiled/installed, and no orders were placed. Databento live/commercial entitlement is unconfirmed.

For later read-only prop-account certification, set `InpHistoryOnly=true`, `InpExecutionEnabled=false` and `InpMasterAccountApproved=false` before attaching EA 1.24. History-only mode skips command polling, pending manifests and all pending guards on init/deinit/timer, so it does not cancel or manage existing pending orders. Existing normal-mode guards are preserved. Do not claim source contract tests are MetaEditor compilation.
