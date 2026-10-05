# XAU/USD certification record — October 5, 2026

The user authorized continued implementation, certification, merge and deployment, superseding the initial brief's branch-only restriction. This record distinguishes offline verification from external certification. Gold analytical approval, publication, pending eligibility and execution remain disabled. The separate existing manual trade path keeps its existing protections.

## Completed offline verification

Before the session additions, the optional Databento SDK and isolated PostgreSQL/Redis produced **1,741 passed, zero skipped**. The earlier PR CI run produced **1,739 passed, two skipped**, plus successful Docker paper smoke, responsive UI and Lighthouse checks. The 14 original local database integration skips were exercised successfully with isolated services; they were not Databento failures.

After the additions, **1,756 passed, zero skipped in 27.45s**:

```sh
uv sync --extra dev --extra gold-data
MONATISE_TEST_DATABASE_URL=postgresql://<local-test-user>@127.0.0.1:55439/monatise_certification \
MONATISE_TEST_REDIS_URL=redis://127.0.0.1:56389/15 \
MONATISE_ENVIRONMENT=test uv run pytest -q -rs
uv run python -m compileall -q monatise
uvx ruff check monatise/application/gold_analysis.py monatise/application/gold_sessions.py tests/test_gold_sessions.py
```

No paid data endpoints or production storage were used. CI now installs the pinned optional SDK and reports skip reasons. Local testing verifies both the actual DBN SDK record format and database-backed recovery/restart behavior.

## Additional implementation

`GoldSessionCalendar` accepts an explicit `gold-broker-sessions-v1` manifest, bound to account/server/XAU/USD, source/version, bounded UTC validity, contiguous historical offset eras and explicit UTC session intervals. Broker bars are aligned to broker wall-clock boundaries, never the US equity calendar. Raw historical `t_broker` timestamps are normalized by their actual era. Ambiguous fall-back times and nonexistent spring-forward times are rejected. Expected finalized bars account for supplied holidays, weekends and maintenance intervals; truncated bars and clock transitions cannot qualify fixed-duration evidence.

The transport independently checks manifest identity, current UTC offset and current session close, preserves the manifest fingerprint/source/version, and retains request/replay/CAS validation. No manifest means the existing uncertified current-offset route remains blocked from analytical qualification. A manifest is reviewed input, not proof its external source is correct; authoritative broker records must still be obtained and verified.

EA 1.24 advertises history capability 3 and sends raw `t_broker` alongside the legacy adjusted timestamp. Gold v2 remains accepted for uncertified shadow assessment; reviewed normalization requires v3. Index v1/v2/v3 remain supported. EA 1.24 adds `InpHistoryOnly`: when true, init/deinit/timer skip pending guards, heartbeat skips pending manifests, and order validation/polling are vetoed independently. This avoids cancelling existing pending orders during read-only certification. Normal-mode safeguards are unchanged. The server retains history-only status and suppresses execution readiness even if a payload claims trading permission. Native extracted final-order validation tests verify the history-only veto, but are not full MQL5 compilation.

## External blockers, observed in the UI

- Render sign-in succeeded, but the existing workspace reports suspension for non-payment. The owner cannot settle the bill at present. No payment, replacement infrastructure purchase, environment edit or deployment was attempted.
- Windows App's saved **Monatise OVH VPS** could not establish Remote Desktop and displayed error **0x204**. This does not prove Render caused the VPS outage. MetaEditor compilation and EA installation cannot be completed until the VPS is reachable.
- The user identified the FTMO session as a prop account and explicitly authorized EA installation. It has not been accessed or modified. Future attachment must use `InpHistoryOnly=true`, with independent execution/master flags false; no live order is needed.
- Databento GLBX.MDP3 live/commercial/derived-output entitlement is unconfirmed. No subscription, licensing terms or paid stream were requested.

## Remaining work; no full/live certification claim

Authoritative broker calendar calibration and live signed history capture, complete production GC discovery/status/replay-watermark/correction/reconnect ownership, American Greek/model uncertainty and Gold GIL/weekly chains, runtime basis wiring and durable dependency/pending revocation, and lawful comparative ablations remain incomplete. The full positive real-engine qualification fixture remains open; current real-engine setup/trigger integration correctly rejects insufficient TP1 RR. Those dependencies remain unavailable and do not gain approval authority from this merge.

Merge of this shadow implementation does not activate Gold orders. Render deployment and actual broker/Databento certification must resume after the concrete blockers are resolved. Preserve disabled Gold analytical controls and all account/risk/quote/replay safeguards. See `docs/xauusd-operator-release.md` for safe rollback.
