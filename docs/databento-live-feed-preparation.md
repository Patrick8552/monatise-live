# Databento CME live-feed preparation

Prepared on 13 October 2026 from Phase 6 commit
`94fd8a7db0abec457a9a6c96d889a3fca288cc52`, on `codex/monatise-phase6`.
This is a separately authorized read-only research capture interface. It is not
registered with application engines, trading, approval, Telegram or deployment.
No subscription was purchased and no live connection was opened during preparation.
The separately authorized [native live pilot](audits/databento-live-pilot-report.md)
subsequently verified Standard live access on the same date. This preparation record
does not describe the account's current activation status.

## Current price and appropriate initial scope

| CME plan | Published monthly price | Contract | Relevant live scope |
|---|---:|---|---|
| Standard | $199 | Monthly | Trades, MBP-1 and L0; excludes live MBP-10/MBO |
| Plus | $1,750 plus applicable license fees | Annual | Includes live MBP-10/MBO |
| Unlimited | $4,500 plus applicable license fees | Annual | Extensive historical coverage plus live depth |

Sources: [current pricing](https://databento.com/pricing),
[June 2026 price update](https://databento.com/blog/updates-to-subscription-pricing)
and the authenticated Safari plan comparison inspected on this date. Standard
covers CME, CBOT, NYMEX and COMEX, including futures/options. Its personal license
includes up to two devices; eligibility still requires the provider questionnaire.
The user declared private personal use. Standard is the initial candidate for
GC/ES/NQ trades and top-of-book. Depth remains disabled in this implementation.

Signup credit can offset eligible first-month subscription charges; it does not
cap spending or cover ongoing renewals. See the
[credit policy](https://databento.com/docs/faqs/usage-pricing-and-data-credits).
Account balances and conditional first-month arithmetic remain in private receipts.
Taxes, final credit application and license eligibility need checkout verification.
Monthly subscription purchase and recurring cash authorization are separate from
previous historical-credit permission. No checkout, license signature or sales
message was submitted.

## Implementation and preserved boundaries

Added four isolated modules in `monatise.research.databento`:

- `live_models.py`: exact GC/ES/NQ scope, native economic validation and current
  publisher/schema catalog, reviewed session, duration, byte/record limits and
  subscription/license/cost-bound operator permits. A SQLite permit is consumed
  once before client creation/subscription; failures never renew it automatically.
- `live_state.py`: per-schema/instrument native event/tied-record cursors, replay
  prefix verification, numeric symbol mapping, native definitions, control handling,
  data freshness, two-sided quote availability, backpressure/error quarantine.
- `live_journal.py`: private framed original DBN-record bytes with actual local
  capture clocks/ordinals, fsync before cursor advancement, hashes/counts, immutable
  sealing and independent verification. Unsealed/quarantined files remain excluded.
- `live_feed.py`: explicit SDK transport using the pinned versions, one schema per
  connection, bounded callbacks/queue, disconnect watchdog, cleanup and private
  receipts. No background activation or automatic reconnection.

The old `DatabentoGoldAdapter.stream` Boolean-only path is retired and fails before
client creation. This prevents bypassing live plan/cost/metadata gates while keeping
production free of research imports. Its offline definitions, replay, snapshot and
existing tests retain their behavior. No other previously tracked file is changed.

Native GC validation accepts actual TRYOZ, quantity 100, tick 0.1 and tick amount /
display factor = USD tick value; it does not rescale DBN trade/quote prices. Existing
ES/NQ native index validation and dataset discovery are reused. Selected raw symbols,
publisher/instrument IDs and expirations remain exact; there is no automatic roll,
continuous/parent/ALL_SYMBOLS subscription, options chain, MBO or depth request.

Default schema scope is definition/trades/MBP-1. Default capture is 300 seconds;
explicit scopes support up to one day within a reviewed session and immutable
record/byte limits. It is not an unattended production service. Candle aggregation,
options analytics and canonical trading remain in their existing isolated paths;
new live data does not silently enter them or become broker XAUUSD prices.

## Protocol, recovery and data-quality rules

A separate connection for each schema avoids assigning an ambiguous replay-complete
message to the wrong subscription. All connections select the same exact native IDs.
Definition replay requests the available exact-contract definition history (`start=0`);
market schemas use the approved start or reviewed per-instrument recovery cursors.
No broad product replay is made.

Heartbeat/acknowledgement/replay-completed codes have separate roles. Heartbeats prove
connection activity only; they cannot make an old quote or execution fresh. Native
symbol mappings bind numeric input to either the exact reviewed raw exchange symbol
returned by the actual gateway or the same numeric identity, with active intervals.
Errors, unknown controls, slow-reader warnings, overflow, future/invalid clocks,
changed contract economics, session expiry and lost connections stop/quarantine
usable context. All definitions and schema replay watermarks must pass before fresh
captured context is reported. That status is not exchange continuity or trading
certification. Unknown aggressor fields remain unknown.

Recovery follows the documented per-instrument event timestamp plus tied-record count.
It also checks original record hashes in the replayed prefix. Identical native bytes
at distinct positions are preserved as legitimate separate executions. Rejected
records do not advance the accepted cursor. Duplicate replays can restore a fresh
quote/definition state without counting the same executed volume twice. Recovery
needs a new explicit permit and independent source/cursor review; no automatic retry.
Operators must respect the provider's reconnect delay/rate limits and confirm current
replay availability. Raw records persist before accepted cursor updates. Each capture
stores actual availability independently of original exchange/capture timestamps;
intraday replay does not invent historical local availability.

Reviewed [live protocol and recovery](https://databento.com/docs/api-reference-live/basics/recovering-after-a-disconnection)
and [connection limits](https://databento.com/docs/api-reference-live/basics/connection-limits).
Pinned SDK source confirms `subscribe` opens the connection. Live preparation does
not call that method against the provider. Schema listing is not live entitlement.

## Using the prepared interface

Import `CMELiveCapture`, `LiveScope` and `LivePermit` from the research package.
Construction is offline and does not read keys. To run a separately approved pilot:

1. Verify a current active plan/license, personal-use eligibility, final recurring
   price/taxes, device/session availability and explicit cash approval.
2. Refresh free publisher/schema and symbol metadata. Validate exact native
   definitions, contract economics/expiry, clocks and reviewed sessions. Keep source
   hashes and live mapping checks; cached historical identity alone is insufficient.
3. Create a specific operator-reviewed scope and fresh permit binding that scope,
   entitlement, lineage, license, total monthly cost and approved monthly budget.
   These references are trust boundaries, not proof generated by the code.
4. Call the capture interface with the existing secure key, a private new output
   directory and durable permit ledger. The default queue is 2,048 records. A failed
   attempt requires reviewed provenance/health and a new permit before recovery.
5. Verify each sealed journal and capture-level receipt, measure genuine latency and
   gaps, and review shutdown/recovery under real conditions before certification.

Keys are explicit private arguments, never stored in receipts or logged error text.
Provider errors are recorded as codes/types; no raw credential-bearing error bodies
are printed. Data remains local and licensed; only sanitized implementation/results
belong in Git. Production activation, trading-policy changes, broker bridge access,
Telegram publication and orders still need separate authorization.

## Evidence and remaining dependencies

Mocked native definitions/market/control messages test all three products, genuine
fixed-point conventions, one-use budgets, replay controls/cursors, unknown/error
messages, stale/locked quotes, clock/session/roll failures, hash tampering, incomplete
journals, disconnect/backpressure shutdown and the legacy-route gate. No test opens
a provider connection or uses production credentials. The complete repository suite
and frozen-selector checks are recorded in the companion validation report.

Fresh free metadata observed publisher 1 / GLBX.MDP3 / GLBX and all supported schemas.
A current-day symbol request returned HTTP 422 `dataset_unavailable_range`. The
request was corrected to the provider's latest completed historical day, 11–12
October (end exclusive): GCZ6=41271, ESZ6=10252, NQZ6=261401, with no partial/not-found
symbols. This confirms recent historical identity, not current live entitlement or
mapping. No time-series data was acquired and no billing quarantine was released.

The authenticated portal showed no active plan. Remaining activation requirements:
subscription/license completion by the user, final price/credit/cash authorization,
current exact metadata/definitions/session review, then an explicitly permitted
real pilot. Genuine live latency, disconnect/recovery and sustained durability have
not been certified by these offline tests. The Phase 1–5 encrypted backup is intact;
new private reports require a later separate backup checkpoint.

## Explicit clock uncertainty for research

The genuine pilot exposed a local clock behind provider clocks. The default remains
strict cross-host ordering with no tolerance. An optional `ClockReview` can bind a
specific independently reviewed offset interval and source hash into `LiveScope`
and its one-use permit. It expires within five minutes, bounds the absolute offset
to one second and initial interval width to 500 milliseconds, and carries an explicit
bounded drift allowance. Missing, expired or contradictory reviews fail closed.

Original provider event/receive times and the original local capture clock remain
unchanged. Normalized records also carry UTC capture bounds and the review hash.
Future records outside those bounds reject; freshness uses the worst age, and capture
duration, records and fresh context cannot extend through the reviewed session end.
No OS clock setting is modified. Public unauthenticated SNTP diagnostics can support
this bounded research experiment; they do not certify production timing or latency.
