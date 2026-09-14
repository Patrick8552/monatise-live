# EA 1.22 — authoritative trade accounting

Source commit: `8e53fcfbef225a35852a43640079800f74414810`.

Compiled with the installed MetaEditor64 compiler: **0 errors, 0 warnings**.

SHA-256 of `mt5/Experts/MonatiseFTMOBridge.ex5`:

`1f600c5ccc3366bf0ca196baad706c8e86f656dd919c3919d7ac987ff4ca66ad`

The heartbeat adds `deal_history_version: 1` and per-position `deal_history_coverage`. Position history includes entry costs, all exits, broker profit, commission, swap, fees, SL/TP and reasons. Accounting no longer depends on multi-TP being enabled. Partial or incomplete history cannot be reported as a completed trade.

Deploy the committed binary with the existing EA inputs. Preserve approval, risk, heartbeat, symbol, pending-expiry and local cancellation-lease settings. Verify version 1.22, identity, heartbeat and history coverage after loading. No live test order is needed for this upgrade.

Backend validation: 1,463 tests passed with isolated PostgreSQL and Redis. Historical messages are not replayed automatically. Missing entry history remains unresolved; ambiguous Telegram sends are retained for reconciliation instead of automatically duplicated.
