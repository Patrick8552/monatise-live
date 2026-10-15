Phase 9 genuine soak campaign
==============================

Authorized scope: existing Standard CME live subscription only; GCZ6, ESZ6 and
NQZ6; definition, trades, OHLCV-1s and OHLCV-1m. No purchases, upgrades, paid
historical acquisition, production deployment, trading or Telegram publication.
Frozen H1 and trade/GIL qualification remain unchanged.

Calendar and evidence boundaries
--------------------------------

The October 15 session is already in progress. Its remainder is calibration data,
not a complete-session soak. The targeted next complete session is October 15,
2026 22:00 UTC through October 16 21:00 UTC (23:00 through 22:00 Africa/Lagos).
Pre-open connections and a maximum 30-second research drain cover both edges.
CME's regular hours/holiday calendar and SER-8788 (equity halt elimination) are
reviewed references. GC is the standard futures contract, not 24/7 1-ounce Gold.
Fresh account entitlement and zero-incremental-cost evidence are required before
opening each scope. No stale receipt is silently refreshed by changing its date.

Collection uses the existing typed persistent service with pinned source files,
private rotating journals/spools and durable local analytical candle output.
Progress records retain health, component faults, source counters, publication
counts, clock reviews and elapsed times. On a fault, raw evidence is preserved;
no interrupted session is reclassified as uninterrupted. A machine/network outage,
missed opening or failed integrity check prevents a full-session reliability claim.
There are no blind reconnects. A fresh reviewed recovery must retain the gap and
its original failure outcome.

The initial nine policies remain the baseline during collection. Quarantined
observations never silently retrain them or qualify a trade. Candidate calibration
is separate and cannot register a production provider or alter frozen H1/GIL.

Prespecified calibration windows
---------------------------------

* Training: October 15 03:45 UTC inclusive through 12:00 exclusive.
* Same-day holdout: October 15 12:00 UTC inclusive through 20:45 exclusive.
* Independent session holdout: October 15 22:00 through October 16 21:00 UTC.

Do not refit from either holdout. Keep contract/schema scopes independent, native
price/quantity units exact and adjacent increments intact. Sparse sample selection
must not turn skipped-price movement into a supposed single execution increment.
Exclude structurally invalid records; quarantined training observations require
source-bound review before use. Report held-out rejects and unknown ground truth;
short coverage does not certify opens, news, gaps or rolls. Candidate promotion is
research-only and requires explicit source/economic-scope/holdout review.

Long-run fixes and checks
-------------------------

Candle publication rebuilds only unpublished parent windows and validates new
bar lineage together, avoiding session-history reaggregation on every tick.
Independent clock renewal runs concurrently with native processing, preserving
the old contemporaneous review for queued captures. An opt-in research drain
(default zero, bounded to 120 seconds; campaign uses 30) admits late delivery of
pre-close events while the market event-time cutoff and session-ended health stay
unchanged. It does not extend evidence expiry or trading qualification.

Initial checks: 2,515 full-suite tests passed without failures/skips, including
new incremental-publication, delayed-clock-refresh and closing-bar-drain cases.
The full-session outcome remains pending genuine acquisition and integrity,
publication, coverage and independent holdout verification.

Local resource policy: at least 64 GiB free, at most 64 GiB campaign physical data,
8 GiB native bytes per stream/spool, bounded segments and rolling analysis memory.
SQLite/index/WAL overhead counts toward the physical campaign budget. A temporary
process-bound idle-sleep assertion may keep acquisition running; no persistent
power preference or production service registration is changed. The Mac must
remain powered, online and available for local follow-up checks.
