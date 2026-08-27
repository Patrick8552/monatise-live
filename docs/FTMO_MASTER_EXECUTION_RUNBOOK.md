# Monatise FTMO master execution runbook

Status: human-approved master-capable code path implemented. Production must remain
fail-closed (kill switch ON, session disarmed, autonomous execution OFF) until a
separately authorized operator completes deployment and live validation.

## Infrastructure decision

A Windows VPS is required. The production broker boundary must be desktop MT5 with the account-bound EA running independently of the Mac. Render remains the durable Monatise control plane; Telegram remains the human approval surface. Neither Telegram nor OpenClaw receives broker credentials or performs broker calls.

Recommended initial host: AWS Lightsail Windows, 2 vCPU / 4 GB RAM / 80 GB SSD, with the region selected only after measuring MT5's displayed ping to the exact FTMO server from candidate regions. AWS currently lists that Windows bundle at USD 44/month with public IPv4. Do not choose a US geolocation for this FTMO MetaTrader deployment. FTMO's VPS guidance explicitly warns users to avoid changing geolocation to the United States when using MetaTrader or cTrader.

The 2 GB bundle can run one MT5 terminal, but 4 GB is the production floor for Windows Update, MT5, logs, antivirus, and the watchdog without memory pressure. Do not colocate OpenClaw on the Windows execution VPS.

Sources:

- https://aws.amazon.com/lightsail/pricing/
- https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html
- https://ftmo.com/faq/can-i-travel-or-use-vpn-vps/
- https://ftmo.com/en/faq/how-do-i-log-in-to-mt5/

## Target architecture

```text
Telegram (private, allowlisted user)
                 |
                 v
Render / Monatise control plane ---- PostgreSQL durable state
                 |                   Redis Telegram leasing
                 | signed HTTPS commands
                 v
Windows VPS -> desktop MT5 -> MonatiseFTMOBridge EA -> FTMO
                 ^
                 | outbound heartbeat, quote, positions, orders, receipts
                 +------------------------------------------------------

Optional Linux OpenClaw Gateway -> read-only/operator API on Render
                                  (never the broker execution kernel)
```

The Mac is development and administration only. Production must continue when it is asleep or offline.

## Responsibility boundaries

- Monatise is the only component allowed to originate a qualified proposal. It
  persists the analysis, strategy evidence, setup expiry, risk structure, and a
  deterministic signal/proposal identity.
- CoinGlass is read-only crypto market intelligence. Its price is an analysis
  reference and is never copied into an FTMO order. A verified registry mapping
  must connect the CoinGlass instrument to an enabled FTMO symbol.
- Telegram is the private, allowlisted human approval surface. Its inline buttons
  carry only a bounded proposal ID; they do not contain price, volume, credentials,
  or an executable order.
- Render revalidates the proposal against a fresh account-bound FTMO heartbeat at
  approval time. BUY uses the current Ask and SELL uses the current Bid. It then
  recalculates geometry, reward/risk, spread, stop distance, volume, drawdown
  capacity, exposure, expiry, and entry deviation before creating a signed command.
- The MT5 EA is the final broker boundary. It repeats account, expiry, symbol,
  trading-mode, volume-step, price-deviation, stop/freeze-distance, daily-loss,
  and one-exposure checks immediately before submission.
- PostgreSQL holds durable proposal/approval/command state and immutable lineage.
  Redis leases and deduplicates Telegram updates. Neither is a source of signals.

The persisted lifecycle is:

```text
AWAITING_APPROVAL -> REVALIDATING -> EXECUTION_QUEUED -> MT5_RECEIVED
-> BROKER_ACCEPTED -> POSITION_OPEN -> POSITION_CLOSED

Any failed gate -> INVALIDATED / REJECTED / EXECUTION_FAILED
Uncertain broker outcome -> RECONCILIATION_REQUIRED (never automatic resend)
```

## OpenClaw decision

Move OpenClaw to a small, separately isolated Linux VPS only if 24/7 operator explanations and monitoring are required. Keep it loopback-bound and access it through Tailscale or SSH; use Gateway authentication. Give it no FTMO password, no bridge HMAC secret, no database write credentials, and no direct MT5 access. An OpenClaw outage must not affect the MT5 bridge.

Primary references:

- https://docs.openclaw.ai/vps
- https://github.com/openclaw/openclaw/blob/main/docs/gateway/index.md

## Windows VPS build

1. Create a non-US Windows Server VPS with 2 vCPU, 4 GB RAM, 80 GB SSD, a static IPv4 address, provider firewall, automatic snapshots, and MFA on the cloud account.
2. Restrict RDP to the administrator's current IP or a Tailscale network. Disable public RDP after Tailscale is verified.
3. Apply Windows Update and set the active-hours/restart policy. Never allow an unscheduled restart during a managed position if the watchdog has not been tested.
4. Download desktop MT5 from the FTMO Client Area or MetaQuotes and verify the publisher signature.
5. Sign in using the exact login, master password, and server shown in FTMO Account MetriX. FTMO confirms that the master password is required for trading and that the server must match exactly.
6. Confirm the account currency and save a screenshot with the account number masked.
7. Copy `mt5/Experts/MonatiseFTMOBridge.mq5` into the terminal's `MQL5\Experts\Monatise` directory and compile it in MetaEditor with zero errors and zero warnings.
8. In MT5, add `https://monatise-live.onrender.com` to Tools -> Options -> Expert Advisors -> allowed WebRequest URLs.
9. Attach the EA to a continuously quoted FTMO chart. Configure the expected account, server, currency, symbols, bridge secret, and loss limits. Keep both EA execution inputs `false` for shadow testing.
10. Install the watchdog scripts under `C:\Monatise` and run `Install-MonatiseWatchdog.ps1` as Administrator.

## Render configuration

The repository deploys safe defaults. The first VPS heartbeat requires these secrets/settings:

```text
MONATISE_TELEGRAM_BOT_TOKEN=<dedicated Monatise bot; never Donpbot>
MONATISE_TELEGRAM_BOT_DELIVERY_MODE=dedicated_render_webhook
MONATISE_TELEGRAM_WEBHOOK_SECRET=<random Telegram-compatible secret>
MONATISE_TELEGRAM_CHAT_ID=<private chat ID>
MONATISE_TELEGRAM_ALLOWED_USER_IDS=<numeric Telegram user ID>

FTMO_ACCOUNT_ID=<exact login>
FTMO_SERVER=<exact server>
FTMO_ACCOUNT_CURRENCY=USD
FTMO_TELEGRAM_AUTHORIZED_USER_IDS=<numeric Telegram user ID>
FTMO_BRIDGE_SECRET=<64+ random characters, same value entered in the EA>

FTMO_EXECUTION_ENABLED=false
FTMO_EXECUTION_ENVIRONMENT=demo
FTMO_MASTER_ACCOUNT_APPROVED=false
FTMO_TELEGRAM_EXECUTION_ARMED=false
FTMO_AUTONOMOUS_EXECUTION=false
FTMO_TELEGRAM_CONFIRMATION_REQUIRED=true
FTMO_RISK_FRACTION=0.03
FTMO_MAXIMUM_OPEN_EXPOSURES=1
FTMO_MAXIMUM_ENTRY_DEVIATION_BPS=50
FTMO_MINIMUM_REWARD_RISK=1
FTMO_QUOTE_FUTURE_TOLERANCE_SECONDS=1
```

Donpbot remains on OpenClaw `getUpdates`. The dedicated Monatise bot is the
only bot registered at
`https://monatise-live.onrender.com/api/telegram/webhook`; never configure both
polling and webhook delivery for the same token.

Never send the FTMO password to Render, Telegram, OpenClaw, or the repository. It stays inside desktop MT5's credential store on the Windows VPS.

## Telegram command contract

All control commands require the configured numeric user ID and a private chat. Every trade or management action creates a preview first.

```text
/status
/bridge
/account
/positions
/orders
/trade XAUUSD buy market sl=2490.00 tp=2520.00
/trade XAUUSD buy limit entry=2495.00 sl=2485.00 tp=2520.00
/approve <proposal-id>
/reject <proposal-id>
/close <position-ticket>
/cancel <order-ticket>
/sl <position-ticket> <level>
/tp <position-ticket> <level>
/breakeven <position-ticket>
/arm [seconds]
/disarm
/kill
```

Qualified scanner proposals are delivered with `APPROVE TRADE` and `REJECT TRADE`
inline buttons. Telegram callback updates are authenticated by the webhook secret,
restricted to the configured private chat and user ID, strictly parsed, durably
deduplicated, and then routed through the same `/approve` or `/reject` service path.
Approval never bypasses the kill switch, temporary arm, account binding, or fresh
quote revalidation.

Duplicate Telegram updates are deduplicated in Redis. A deterministic command ID is derived from the proposal. The EA journals that ID before its broker call and uses the same ID in the order comment. A repeated network delivery therefore reconciles the journal entry; it does not submit a second order.

## Master activation gates

Do not activate these gates until the demo checklist below has evidence. Activation requires all of them simultaneously:

```text
FTMO_EXECUTION_ENABLED=true
FTMO_EXECUTION_ENVIRONMENT=master
FTMO_MASTER_ACCOUNT_APPROVED=true
FTMO_TELEGRAM_EXECUTION_ARMED=true
FTMO_AUTONOMOUS_EXECUTION=false
FTMO_TELEGRAM_CONFIRMATION_REQUIRED=true
```

The EA also requires `InpExecutionEnabled=true` and `InpMasterAccountApproved=true`. A temporary `/arm` session is still mandatory. The durable kill switch defaults to ON; resetting it is an out-of-band administrative operation, never a Telegram command.

The live per-trade ceiling is percentage-only: keep the EA at
`InpRiskFraction=0.03` and `InpMaximumOpenExposures=1`. The obsolete `$5`
per-trade and `$10` temporary daily caps are removed. The exposure slot counts
both live positions and pending orders. The Render control plane rechecks the
slot and broker-reported daily/total loss capacity when a proposal is created
and again immediately before command creation; the EA repeats both checks
against broker state immediately before submission.

After every other gate is configured, the audited reset command is:

```text
python scripts/ftmo_control_admin.py reset-kill --actor <operator-id> --confirmation I_ACKNOWLEDGE_FTMO_KILL_RESET
```

The reset leaves execution disarmed. `/arm` is still required and expires automatically.

## Required shadow and demo evidence

Record timestamped evidence for every item before master activation:

- Windows VPS remains online with the Mac asleep.
- Desktop MT5 reconnects after a VPS reboot and the watchdog detects the process.
- Exact account/server/currency binding succeeds; each deliberate mismatch fails.
- EA heartbeat, terminal permission state, positions, orders, XAUUSD Bid/Ask, and symbol specification appear in `/bridge`.
- Telegram XAUUSD previews use the heartbeat's FTMO Bid/Ask, not GC futures or another broker.
- Crypto proposals preserve both CoinGlass analysis provenance and the independent
  FTMO Bid/Ask execution snapshot; unsupported or ambiguous mappings fail closed.
- Approval after a material price move, expiry, invalid entry zone, or degraded
  reward/risk invalidates the proposal and creates no command.
- Market, limit, and stop BUY/SELL demo orders reconcile to one broker ticket.
- Broker receipts record requested price, fill price, slippage, executed volume,
  actual SL/TP, retcode, ticket, and observation time against the immutable lineage.
- SL, TP, close, cancel, and breakeven demo operations reconcile.
- Duplicate callback and duplicate command delivery create one economic action.
- A network timeout after submission becomes `broker_uncertain`; no new command is created.
- Render, Telegram, OpenClaw, MT5, and network outage tests fail closed.
- Stale quote, excessive spread, account mismatch, expired proposal, risk limit, daily loss capacity, kill switch, and expired arm all reject.
- Existing broker-side SL/TP remains present during upstream outages.

Until all items pass, `/approve` must remain blocked from broker submission.

## Rollback

1. Send `/kill`; verify `/status` shows kill switch ON and armed false.
2. Set `FTMO_EXECUTION_ENABLED=false` and `FTMO_TELEGRAM_EXECUTION_ARMED=false` on Render.
3. Set both EA execution inputs false or remove the EA from the chart. Do not remove broker-side SL/TP from existing positions.
4. Preserve PostgreSQL audit/proposal/command records and the EA common-files journal.
5. If the new Render release is implicated, redeploy the last verified commit. Do not retry a `broker_uncertain` command; reconcile it against MT5 history first.
6. Confirm there are no pending commands and manually supervise any existing broker positions.
