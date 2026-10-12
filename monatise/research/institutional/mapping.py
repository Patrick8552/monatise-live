"""General contextual mapping around existing GoldBasisService calculations."""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from monatise.application.gold_basis import GoldBasisService
from monatise.adapters.databento_identity import timestamp_ns
from .models import Contract, MarketObservation, digest, hash_required, number, encode

RELATIONSHIPS = {"GC":"XAU/USD", "ES":"US500.cash", "NQ":"US100.cash",
                 "CL":"USOIL.cash", "YM":"US30.cash", "RTY":"US2000.cash"}


def dt(ns):
    return datetime.fromtimestamp(ns//10**9, UTC).replace(microsecond=(ns%10**9)//1000)


@dataclass(frozen=True)
class MappingPolicy:
    reference: str
    maximum_age_ns: int = 30*10**9
    maximum_skew_ns: int = 10**9
    minimum_samples: int = 5
    maximum_dispersion: Decimal = Decimal(".5")
    maximum_residual: Decimal = Decimal(1)

    def __post_init__(self):
        if (not self.reference or type(self.minimum_samples) is not int or not 5 <= self.minimum_samples <= 128
                or type(self.maximum_age_ns) is not int or not 0 < self.maximum_age_ns <= 30*10**9
                or type(self.maximum_skew_ns) is not int or not 0 <= self.maximum_skew_ns <= 10**9):
            raise ValueError("bounded_reviewed_mapping_policy_required")
        number(self.maximum_dispersion, positive=True)
        number(self.maximum_residual, positive=True)


@dataclass(frozen=True)
class BrokerQuote:
    instrument: str
    provider: str
    currency: str
    bid: Decimal
    ask: Decimal
    event_ns: int
    receive_ns: int
    admission_ns: int
    source_sha256: str
    evidence_kind: str
    price_unit: str

    def __post_init__(self):
        for t in (self.event_ns, self.receive_ns, self.admission_ns): timestamp_ns(t)
        hash_required(self.source_sha256)
        if (not self.instrument or not self.provider or self.currency != "USD" or not self.price_unit
                or not self.event_ns <= self.receive_ns <= self.admission_ns
                or number(self.bid, positive=True) > number(self.ask, positive=True)
                or self.evidence_kind not in {"AUTHENTIC_ARCHIVED_RECORD", "ENGINEERING_SYNTHETIC"}):
            raise ValueError("observed_broker_quote_required")


class ContextMapper:
    def __init__(self, *, contract, broker_instrument, policy):
        if (not isinstance(contract, Contract) or contract.asset_class != "futures"
                or RELATIONSHIPS.get(contract.metadata.product) != broker_instrument
                or not isinstance(policy, MappingPolicy)):
            raise ValueError("reviewed_economic_relationship_required")
        self.contract, self.broker_instrument, self.policy = contract, broker_instrument, policy
        self.math = GoldBasisService(minimum_samples=policy.minimum_samples,
            maximum_age=timedelta(microseconds=policy.maximum_age_ns//1000),
            max_skew=timedelta(microseconds=policy.maximum_skew_ns//1000),
            max_dispersion=policy.maximum_dispersion, max_residual=policy.maximum_residual)
        self.sources = []
        self.kind = None
        self.broker_provider = None

    def add(self, futures, broker, *, now_ns, session_start_ns, session_end_ns, session_reference):
        try:
            for t in (now_ns, session_start_ns, session_end_ns): timestamp_ns(t)
            if (not isinstance(futures, MarketObservation) or futures.schema != "mbp-1"
                    or futures.contract != self.contract or not isinstance(broker, BrokerQuote)
                    or broker.instrument != self.broker_instrument
                    or self.broker_provider not in {None, broker.provider}
                    or not session_reference or futures.contract.currency != broker.currency
                    or futures.contract.price_unit != broker.price_unit
                    or not session_start_ns <= min(futures.event_ns, broker.event_ns)
                    or not now_ns < min(session_end_ns, self.contract.metadata.expiration_ns)
                    or futures.source.evidence_kind != broker.evidence_kind
                    or self.kind not in {None, broker.evidence_kind}
                    or abs(futures.receive_ns-broker.event_ns) > self.policy.maximum_skew_ns
                    or any(not 0 <= now_ns-t <= self.policy.maximum_age_ns
                           for t in (futures.receive_ns, broker.event_ns))
                    or max(futures.source.admission_ns, broker.admission_ns) > now_ns):
                raise ValueError("mapping_identity_session_clocks_or_availability_invalid")
            top = futures.payload[0]
            if top[0] is None or top[3] is None or min(top[1],top[4]) <= 0:
                raise ValueError("two_sided_futures_quote_required")
            self.math.add(contract=digest(self.contract), broker_bid=broker.bid, broker_ask=broker.ask,
                futures_bid=top[0], futures_ask=top[3], broker_at=dt(broker.event_ns),
                futures_at=dt(futures.receive_ns), now=dt(now_ns))
            self.kind = broker.evidence_kind
            self.broker_provider = broker.provider
            uncertainty = (number(top[3])-number(top[0])+broker.ask-broker.bid)/2
            self.sources.append(dict(futures_sha256=digest(futures), broker_sha256=broker.source_sha256,
                futures_mid=(number(top[0])+number(top[3]))/2, broker_mid=(broker.bid+broker.ask)/2,
                uncertainty=uncertainty, oldest_ns=min(futures.receive_ns,broker.event_ns),
                session_end_ns=session_end_ns, session_reference=session_reference,broker_provider=broker.provider))
            self.sources = self.sources[-128:]
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            self.math.samples.clear()
            self.sources.clear()
            self.kind = None
            raise

    def estimate(self, *, now_ns, futures_level=None):
        try:
            timestamp_ns(now_ns)
            if now_ns >= self.contract.metadata.expiration_ns:
                raise ValueError("contract_expired")
            data = (self.math.estimate(contract=digest(self.contract), now=dt(now_ns))
                    if futures_level is None else self.math.map_level(futures_level,
                    contract=digest(self.contract), now=dt(now_ns)))
            fresh = [s for s in self.sources if 0 <= now_ns-s['oldest_ns'] <= self.policy.maximum_age_ns
                     and now_ns < s['session_end_ns']]
            if len(fresh) < self.policy.minimum_samples:
                raise ValueError("insufficient_fresh_session_compatible_samples")
            expiry = min(self.contract.metadata.expiration_ns,
                         *(min(s['oldest_ns']+self.policy.maximum_age_ns,s['session_end_ns']) for s in fresh))
            if expiry <= now_ns:
                raise ValueError("mapping_expired")
            uncertainty = data['uncertainty']+max(s['uncertainty'] for s in fresh)
            original = number(futures_level, positive=True) if futures_level is not None else None
            mapped = original-data['basis'] if original is not None else None
            if mapped is not None and mapped-uncertainty <= 0:
                raise ValueError("mapped_level_invalid")
            return encode(dict(status="MAPPING_CONTEXT_ESTIMATE", contract=self.contract.identity,
                broker_instrument=self.broker_instrument,broker_provider=self.broker_provider,
                observed_futures_mid=fresh[-1]['futures_mid'],
                observed_broker_mid=fresh[-1]['broker_mid'], observed_basis=fresh[-1]['futures_mid']-fresh[-1]['broker_mid'],
                basis=data['basis'], uncertainty=uncertainty, stable=True, expiration_ns=expiry,
                sample_count=len(fresh), futures_level=original, mapped_low=mapped-uncertainty if mapped else None,
                mapped_high=mapped+uncertainty if mapped else None, evidence_kind=self.kind,
                source_provenance=fresh, policy=self.policy,
                methodology="existing-median-basis-plus-observed-half-spread-bound-v1",
                limitation="Contextual estimate; uncertainty is an observed bound, not a statistical confidence interval.",
                context_only=True, execution_price_authority=False))
        except (ValueError, ArithmeticError, TypeError):
            return dict(status="MAPPING_UNAVAILABLE", contract=self.contract.identity,
                broker_instrument=self.broker_instrument, basis=None, mapped_low=None, mapped_high=None,
                reason="insufficient_valid_synchronized_observations", context_only=True, execution_price_authority=False)
