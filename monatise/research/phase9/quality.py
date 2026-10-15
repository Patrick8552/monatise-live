"""Bounded per-contract/schema screening on canonical observations, never price repair."""
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from monatise.research.institutional.models import MarketObservation, digest, number, hash_required
from . import SAFETY


@dataclass(frozen=True)
class PlausibilityPolicy:
    product: str
    floor_ticks: int
    scale: Decimal
    maximum_spread_ticks: int
    review_reference: str
    source_sha256: str
    window: int = 128
    warmup: int = 8

    def __post_init__(self):
        hash_required(self.source_sha256)
        if (self.product not in {'GC','ES','NQ','OG'} or not self.review_reference
                or any(type(v) is not int or v <= 0 for v in (self.floor_ticks,self.maximum_spread_ticks,self.window,self.warmup))
                or not 3 <= self.warmup <= self.window <= 4096 or number(self.scale) < 3):
            raise ValueError('reviewed_instrument_plausibility_policy_required')

    @property
    def sha256(self): return digest(self)


class PriceGuard:
    """Median/MAD increments: rejected spikes never train the rolling threshold.

    First prices require a reviewed independent anchor. A legitimate discontinuity
    may be quarantined; admitting a new anchor is an explicit provenance-bound
    review, never an automatic fallback to the suspicious price.
    """
    def __init__(self, contract, policy, *, anchor, anchor_ns, anchor_sha256):
        hash_required(anchor_sha256)
        from monatise.adapters.databento_identity import timestamp_ns
        timestamp_ns(anchor_ns)
        if contract.metadata.product != policy.product:
            raise ValueError('instrument_policy_mismatch')
        self.contract, self.policy = contract, policy
        self.last = number(anchor, positive=True)
        if self.last % contract.tick_size: raise ValueError('anchor_off_tick')
        self.anchor_ns, self.anchor_sha256 = anchor_ns, anchor_sha256
        self.changes = deque(maxlen=policy.window)

    def inspect(self, prices, event_ns):
        if not prices: return None
        if event_ns < self.anchor_ns: return 'price_precedes_reviewed_anchor'
        values = [number(p, positive=True) for p in prices]
        changes = list(self.changes)
        center = median(changes) if changes else Decimal(0)
        mad = median([abs(x-center) for x in changes]) if changes else Decimal(0)
        bound = max(self.contract.tick_size*self.policy.floor_ticks,
                    center+self.policy.scale*Decimal('1.4826')*mad)
        if any(abs(p-self.last) > bound for p in values): return 'suspicious_price_discontinuity_requires_review'
        return None

    def commit(self, price):
        price = number(price, positive=True)
        self.changes.append(abs(price-self.last)); self.last = price


class QualityGate:
    """Source-position idempotence; identical exchange events at new positions count.

    Never infer gaps from filtered CME packet sequences. Transport gap notices
    invalidate only dependent schema/instrument outputs until reviewed recovery.
    """
    def __init__(self, contract, policy, *, anchor, anchor_ns, anchor_sha256, capacity=50000):
        if type(capacity) is not int or not 1 <= capacity <= 100000: raise ValueError('bounded_quality_capacity_required')
        self.contract, self.policy, self.capacity = contract, policy, capacity
        self.guard = PriceGuard(contract, policy, anchor=anchor, anchor_ns=anchor_ns, anchor_sha256=anchor_sha256)
        self.guards = {}
        self.positions, self.last_events, self.last_received = {}, {}, {}
        self.latest, self.faults, self.quarantine = {}, {}, deque(maxlen=256)
        self.reviews = deque(maxlen=64)
        self.fault_event_ns = {}
        self.accepted = deque(maxlen=capacity)

    def reject(self, value, reason):
        self.faults[value.schema] = reason
        self.fault_event_ns[value.schema] = min(self.fault_event_ns.get(value.schema,value.event_ns),value.event_ns)
        self.quarantine.append(dict(source=value.source, reason=reason, record_sha256=value.source.record_sha256,
            raw_source_reference_required=True, policy_sha256=self.policy.sha256))
        return dict(accepted=False, duplicate=False, reason=reason, **SAFETY)

    def ingest(self, value, *, now_ns):
        if not isinstance(value, MarketObservation) or value.contract != self.contract:
            raise ValueError('exact_canonical_contract_required')
        signature = digest(value)
        prior = self.positions.get(value.source.position)
        if prior is not None:
            if prior != signature: return self.reject(value, 'source_position_revision')
            return dict(accepted=False, duplicate=True, reason='same_source_position', **SAFETY)
        if len(self.positions) >= self.capacity: return self.reject(value, 'quality_capacity_exceeded')
        self.positions[value.source.position] = signature
        if value.source.admission_ns > now_ns: return self.reject(value, 'not_available_at_cutoff')
        if (value.event_ns < self.last_events.get(value.schema, 0)
                or (value.receive_ns or value.event_ns) < self.last_received.get(value.schema, 0)):
            return self.reject(value, 'out_of_order_event_or_receive_timestamp')
        prices = []
        if value.schema == 'trades': prices = [value.payload[0]]
        elif value.schema.startswith('ohlcv-'):
            prices = [Decimal(p)/10**9 for p in value.payload[2:6]]
        elif value.schema in {'mbp-1','mbp-10'}:
            top = value.payload[0]
            if top[0] is None or top[3] is None or min(top[1],top[4]) <= 0:
                return self.reject(value, 'one_sided_or_empty_book')
            bid, ask = number(top[0], positive=True), number(top[3], positive=True)
            if bid >= ask: return self.reject(value, 'crossed_or_locked_book')
            if (ask-bid)/self.contract.tick_size > self.policy.maximum_spread_ticks:
                return self.reject(value, 'suspicious_spread')
            prices = [bid, ask]
        guard = self.guards.setdefault(value.schema, PriceGuard(self.contract,self.policy,
            anchor=self.guard.last,anchor_ns=self.guard.anchor_ns,anchor_sha256=self.guard.anchor_sha256))
        reason = guard.inspect(prices, value.event_ns)
        if reason: return self.reject(value, reason)
        # Schema-dependent guards avoid quote movements contaminating trade volatility.
        if prices: guard.commit(prices[-1])
        self.last_events[value.schema] = value.event_ns
        self.last_received[value.schema] = value.receive_ns or value.event_ns
        self.latest[value.schema] = value; self.accepted.append(value)
        return dict(accepted=True, duplicate=False, reason=None,
            plausibility='WARMUP' if len(guard.changes) < self.policy.warmup else 'ADAPTIVE',
            policy_sha256=self.policy.sha256, **SAFETY)

    def review_recovery(self, schema, *, anchor, anchor_ns, anchor_sha256, review_reference, expected_fault_sha256):
        """Explicit reviewed discontinuity/transport recovery; old rejects stay rejected."""
        if not review_reference or schema not in self.faults or digest(self.faults[schema])!=expected_fault_sha256:
            raise ValueError('current_fault_bound_recovery_review_required')
        new_guard=PriceGuard(self.contract,self.policy,anchor=anchor,anchor_ns=anchor_ns,anchor_sha256=anchor_sha256)
        if anchor_ns<self.last_events.get(schema,0):raise ValueError('recovery_anchor_precedes_accepted_state')
        self.guards[schema]=new_guard
        self.latest.pop(schema,None)
        self.faults.pop(schema)
        self.fault_event_ns.pop(schema,None)
        self.reviews.append(dict(schema=schema,anchor_sha256=anchor_sha256,review_reference=review_reference,
            prior_fault_sha256=expected_fault_sha256,anchor_ns=anchor_ns))

    def transport_gap(self, schema, reason, *, event_ns=None):
        self.faults[schema] = 'transport_gap:'+reason
        self.fault_event_ns[schema] = min(self.fault_event_ns.get(schema,event_ns or 0),event_ns or 0)

    def health(self, *, now_ns, policies, schemas):
        result = {}
        for schema in schemas:
            value = self.latest.get(schema)
            if value is None:
                result[schema] = dict(available=False, reason=self.faults.get(schema,'no_valid_observations'))
                continue
            policy = policies[schema]
            source = value.payload[1] if schema.startswith('ohlcv-') else value.payload[2] if schema=='statistics' else value.event_ns
            review=value.source.clock_review
            if review is not None:
                try:review.bounds(now_ns)
                except ValueError:review=None
            timing = policy.assess(source_ns=source, available_ns=value.source.retrieval_ns,
                now_ns=now_ns, expires_ns=self.contract.metadata.expiration_ns,clock_review=review)
            fault = self.faults.get(schema)
            result[schema] = dict(available=timing['contextual_eligible'] and not fault, reason=fault or timing['reason'],
                freshness=timing, event_ns=value.event_ns, receive_ns=value.receive_ns,
                capture_ns=value.source.retrieval_ns, source_sha256=value.source.record_sha256,
                coverage='CAPTURED_SUBSET_CONTINUITY_UNCERTIFIED')
        return result
