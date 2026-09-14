# Waiting entries and approved pending orders

A confirmed setup outside its entry zone remains qualified. Its observed analytical price, live broker Bid/Ask, fixed permitted zone, planned entry, stop, target ladder, and invalidation level are separate fields. No observed price is clamped or filled from an intended entry.

Manual analysis, scheduled scanners, and Telegram analysis requests can publish a waiting proposal with Approve trade and Reject trade controls. Missing/invalid market observations still block proposals. Temporary broker distance or EA capability failures retain the pending approval decision. Expiry, structural invalidation, risk failures, stale quotes, unavailable sessions, and disabled execution gates remain blocking conditions.

## Approval and order selection

`entry_policy.py` selects the order using the actual executable quote and the fixed planned entry:

| Direction | Planned entry versus executable quote | Pending type |
|---|---|---|
| Buy | Below Ask | Buy Limit |
| Buy | Above Ask | Buy Stop |
| Sell | Above Bid | Sell Limit |
| Sell | Below Bid | Sell Stop |

Immediate market execution is permitted only inside the approved zone. A proposal initially waiting for a pending entry never upgrades to market. The approval text explicitly permits selecting the appropriate limit/stop subtype at the fixed entry after a fresh quote. Equal-price or insufficient-distance placement waits; it does not move the entry.

Stock and native MT5 analysis levels retain their original price units. External derivative levels use a documented observation-to-broker basis conversion, bounded by the existing mapping ratio safeguard. The basis is frozen when the proposal is created. Approval never recenters the zone, SL, TP, or structural invalidation on a newer quote. Broker tick rounding remains necessary, and an entry that cannot be represented inside the zone is rejected. Volume and absolute risk may decrease on revalidation but cannot increase beyond the reviewed limits. All original target destinations remain fixed.

A definitive price refusal before submission can produce one separate pending proposal with a new manual approval, retaining the original entry, SL, targets, risk ceiling, and deadline. Existing uncertain-submission and replacement-origin protections remain enforced. A broker ticket, submission attempt, ambiguous acknowledgement, or possible fill prevents a replacement.

## Pending-order cancellation

New managed pending orders require EA **1.21**, `pending_entry_version=2`, and broker support for `ORDER_TIME_SPECIFIED`. Unsupported brokers/EAs retain the waiting proposal but cannot place it. Managed pending orders never fall back to GTC or day expiry.

The initial command carries three separate timestamps: the original setup deadline, a **20-second local eligibility lease**, and a **30-minute maximum broker expiry**. The broker deadline is fixed at approval and capped by any earlier setup, source, target-plan, or active-arm expiry. The default operator proposal validity remains 30 minutes; earlier analytical expiries are never extended. Each authenticated heartbeat checks approval, account binding, current analysis and hierarchy evidence, target/structural invalidation, market sessions, quote freshness, spread, risk capacity, conflicting exposure, protection levels, and target-management permissions. Existing working pending orders may approach their entry without failing the *new-order placement-distance* rule.

The server signs a nonce-bound lease manifest tied to the configured account/server/currency. Each row carries `ticket|local_lease_until|broker_deadline`. The EA refreshes its durable local permission without extending broker lifetime. It may shorten the broker expiry when source validity is shortened; it never changes entry, SL, TP, or size. Both deadlines are bounded by the signed approval. Omitted/revoked orders are cancelled. Revocation is durable and cannot be reversed by a later healthy heartbeat. Rejected/frozen cancellation attempts remain revoked and are retried. Heartbeats report the actual native order expiry, and an expiry exceeding the approved deadline is rejected.

If the control-plane connection fails while the EA can still trade, the local 20-second lease expires and the EA requests cancellation. If the EA stops or the broker connection is unavailable, the fixed broker expiry is the fallback: **the order may remain active until its approved deadline, up to 30 minutes**. This replaces the previous 20-second native-expiry fallback at the user's request. EA restart/deinitialization revokes owned managed pending orders. Cancellation remains authorized with new-entry gates disabled, subject to actual MT5 trading permission and broker acceptance. A filled order is never converted into an automatic position-close request. Cancellation/fill races and broker stop-order slippage remain broker behavior; this implementation does not promise instantaneous deletion or guaranteed stop-order fill prices.

The EA uses its magic number and `MNP:<command-prefix>` ownership marker; unrelated orders are untouched. The durable command journal, separate original deadline, proposal CAS, signed command identity, and uncertain-submission reconciliation prevent duplicate orders. A missing acknowledgement can be reconciled from the authenticated pending-order heartbeat.

## Rollout and checks

Deploy the backend and install the compiled EA 1.21 plus all three `.mqh` includes. Version mismatches block new managed pending execution during rollout. Existing execution gates and risk configuration remain unchanged. Do not enable managed pending execution on a broker that lacks specified expiration.

Tests cover all four order types across crypto/stocks/indices, waiting Telegram controls, real-price preservation, risk/SL/TP immutability, late price refusal, repeated approval, uncertain submission, hierarchy/signal invalidation, expiry, cancellation eligibility, partial exposure, and fill races. A portable harness runs the actual EA pending lifecycle functions against a simulated broker, including signed reply rejection, shortened expiry, restart, offline expiry, cancellation retry, and ownership isolation. MetaEditor compilation verifies the complete EA.
