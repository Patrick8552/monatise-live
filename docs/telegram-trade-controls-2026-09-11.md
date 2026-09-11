# Telegram trade controls investigation — 11 September 2026

## Canonical baseline and production evidence

The source is Patrick8552/monatise-live, based on origin/main
`98a800384508c9a4f9611b312a059cb968113954`. The authenticated Render service
`srv-d8ha3tvlk1mc73e9k7vg` reported the same deployed revision. Changes were
prepared in an isolated worktree, not an older local clone.

Read-only production inspection found a healthy Telegram webhook/worker and live
MT5 bridge. Actual quote keys are XAUUSD, US100.CASH and US500.CASH (the latter
two preserve the broker's `.cash` names in their quote metadata). All three had
fresh quotes during inspection. Recent scanner rejections included US100 spread
limits and XAU/USD / US500 exposure limits. Other gold crosses also had mapping
failures. These are different failure classes; adding buttons would incorrectly
bypass risk or quote validation.

Historical comparison:

* US500 proposal `b060137a099d`, created 10 September 18:26:35 UTC, has Telegram
  message 727 and a reconciled execution; the management proposal associated
  with message 736 was also recorded. Their publication audits lacked durable
  analysis/signal links.
* XAUUSD scanner proposal `5d33209bd93a`, created 11 September 09:11:42 UTC,
  was persisted and reconciled but has no saved Telegram message ID. Other
  scanner proposals show the same missing ID. Missing IDs prove a persistence
  gap, not that Telegram omitted the keyboard for every such message.
* Recent context notifications followed rejected quote/risk validation, including
  exposure and spread restrictions. Previously these were all presented as
  quote-unavailable failures. A Telegram UI fault was not established.

## Regression and fix

`889dd62` introduced a silent notifier fallback from an approval-capable send to
plain text when the transport lacks keyboard support. `8d08883` added a scanner
publication path with a further plain-text fallback and without saving the
returned Telegram message ID. `dd9b03a` correctly withheld controls when execution
gates were blocked, but the presentation remained too similar to an executable
preview. Its safety gates are preserved.

All production proposal publishers now use a shared boundary:

1. Require persisted analysis, qualified signal and proposal identities.
2. Validate pending/unexpired/non-superseded state, actual mapped MT5 quotes,
   quote timestamp, market session, risk, spread and execution gates.
3. Persist a send intent bound to the configured chat.
4. Render from the durable proposal and send both labelled inline controls,
   with the stable proposal ID in each callback.
5. Require Telegram's returned keyboard and persist its message ID.

Blocked publications explicitly start with
`CONTEXT ONLY — NOT AN EXECUTABLE TRADE`, include a machine-readable omission
reason, and omit actionable order fields/commands. Executable plain-text
fallbacks are forbidden. Uncertain sends require reconciliation instead of
blind retries; a known message whose persistence fails has controls retracted.
Approval is blocked until its required publication record is complete.

Callback routing preserves chat identity and validates the authorized user,
stored chat and exact Telegram message ID before resolving a proposal. Proposal
updates use version comparisons. Approval claims the proposal before writing a
command; the MT5 bridge additionally requires a completed, matching approval
record. Rejection, duplicate approvals and partial writes cannot leave an
unapproved command deliverable. Existing fresh-quote refresh, expiry, manual
approval, account identity, risk and broker gates remain in place.

Structured lifecycle diagnostics include source IDs, symbols, quote age, risk,
proposal/publication state, keyboard presence, message ID and failure reason.
Scanner health separates context publications from executable proposals.

## Files and validation

Production files: `trade_publication.py`, `workflows.py`, `deployment.py`,
`ftmo_master.py`, `production.py`, `telegram_analysis.py` under
`monatise/application/`.

Regression coverage in `tests/test_trade_publication.py` independently exercises
XAU/USD → XAUUSD, US100.cash → US100.CASH, and US500.cash → US500.CASH through
real service validation, persistence, the Telegram HTTP payload, both callbacks,
webhook queue routing and a simulated bridge handoff. It also covers missing,
stale, future and mismatched quotes; persistence failures before/after sending;
wrong user/chat/message; expired/rejected/superseded proposals; concurrent
approval/rejection; duplicate approvals; and an incomplete command transaction.

Existing transport, master-service and webhook tests were updated. Six unrelated
live-service tests failed on both the unchanged baseline and the patch because
they inherited today's CPI blackout. Their fixture now uses a fixed non-event
time; the production calendar guard is unchanged.

Local full suite: **1028 passed, 12 skipped**. The skips require PostgreSQL/Redis
integration test URLs; CI provides those services. Production deployment and
controlled Telegram checks must be reported separately from local simulation.

## Operational notes

No existing position was changed during investigation. Read-only records show
XAUUSD ticket 291873315 was reported closed at 12:30:03 UTC on 11 September;
there were zero Monatise close commands that day. After the user reconnected
the VPS, MT5 History confirmed the 0.05-lot buy opened at 4344.74 and closed
at 4303.87 at 15:30:02 broker time (12:30:02 UTC). The exit deal comment was
`[sl 4317.71]`: a broker stop-loss execution, with 13.84 adverse price slippage.
Trading P/L was -204.35 USD, plus 0.15 USD commission on each side. The target
was 4457.28. This was not a close instruction from this debugging session.

Do not loosen spread/exposure gates to produce test buttons. Do not submit a
live approval merely to validate a handoff. The local three-symbol tests prove
the command path without a real broker order. Telegram API keyboard semantics:
https://core.telegram.org/bots/api#inlinekeyboardmarkup
