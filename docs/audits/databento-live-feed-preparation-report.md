# CME live-feed preparation delivery

The reviewed Phase 6 commit `94fd8a7db0abec457a9a6c96d889a3fca288cc52` was
published and its GitHub branch SHA independently checked on 13 October 2026:
[Phase 6 research branch](https://github.com/Patrick8552/monatise-live/tree/codex/monatise-phase6).
Main remains `0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`; the frozen baseline branch
remains `51988f0ced35ee6bbe378174e80b57f2c9943a47`. No merge/deployment or trading
activation. Its sixteen files, accepted historical outputs and billing quarantines
are unchanged by this follow-up.

The [live preparation runbook](../databento-live-feed-preparation.md) records current
prices, schema/tier limits, scope, operator approval requirements and the API. Added
four isolated native capture modules and 58 offline tests. Retired the shared
adapter's legacy Boolean-only streaming entry point. Native definition validation
reuses dataset discovery, reviewed GC economics and existing ES/NQ validation.
Live records reuse AdvancedAdapters. All production analytical, risk, execution,
Telegram and approval consumers remain unchanged; no research package is imported
from a production consumer. No new dependency or infrastructure service.

Fixed gaps: actual GC native-unit/display-factor compatibility, multi-asset exact
scope, replay-control attribution, heartbeat versus market freshness, current native
symbol mapping/definition checks, bounded callback backlog/queue, disconnect/shutdown,
durable original-record journaling, strict replay cursor/hash recovery, one-use live
cost/entitlement permits, rejected-record cursor rollback and quote availability.
Recovery is reviewed and explicit; an error cannot trigger an automatic chargeable
retry or an unreviewed continuity claim. Defaults are a bounded read-only pilot;
production registration and unattended live operation remain separate acceptance.

Final full offline harness: **2,290 passed**, zero failures/errors/skips, **48.63 s**.
Includes the prior 2,232 plus 58 new cases. The first full attempt found two existing
research/production import-boundary failures; the implementation was corrected and
the original tests retained. Final native validation also passed on genuine cached
GCZ6, ESZ6 and NQZ6 definitions, not only SDK-shaped fixtures. Current fixed-point
market prices are not display-factor rescaled. The frozen selector checkout and
baseline branch remain unchanged. [Validation receipt](databento-live-feed-preparation-validation.json)
contains source/test hashes and actual limits.

Authenticated Safari plan inspection confirmed no active subscription, Standard
live trades/top-of-book and excluded live MBP-10/MBO; Plus includes both depth schemas.
Only comparison views were selected; no purchase, contact-sales message, licensing
questionnaire submission or signature. Pricing and eligibility are in the runbook;
private credit balances and conditional cash arithmetic remain private.

Free metadata refreshed GLBX publisher/schema availability. The provider rejected
an unpublished historical date range with HTTP 422 `dataset_unavailable_range`.
Using its latest completed historical day resolved all three exact symbols to their
existing native IDs without partial/missing results. These mappings do not certify
current live IDs/entitlement; live symbol messages and definitions remain gates.
No historical time-series data download, paid retry or live connection was attempted.
**Incremental provider expenditure: $0.** Old ES/NQ billing quarantine and six
reservations remain untouched. Historical estimates never become actual billing.

Remaining steps are concrete: user-authorized subscription/recurring cash price and
personal-license completion; current live metadata/session/cost review and a one-use
pilot permit; genuine latency/gap/recovery/shutdown validation. Broker XAUUSD mapping,
options inputs/Greeks and canonical signal qualification remain independent gaps.
No test establishes profitability, trade certification or production readiness.
New private receipts need a separate later backup checkpoint; the existing encrypted
Phase 1–5 package is preserved. The final delivery reports the follow-up commit SHA
and verifies its GitHub branch after push.
