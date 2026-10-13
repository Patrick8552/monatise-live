"""Provenance-aware certification around the existing midpoint basis service.

Unknown timezones may only produce *conditional* indicative estimates. A
second-precision timestamp denotes an interval, not an exact UTC instant.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from monatise.application.gold_basis import GoldBasisService
from ..models import digest, encode
from . import SAFETY

SECOND = 10**9


@dataclass(frozen=True)
class Timestamp:
    nominal_ns: int
    lower_ns: int
    upper_ns: int
    raw: str
    source: str
    source_sha256: str
    utc_authority_reference: str | None = None
    precision_ns: int = 1

    def validate(self):
        if (any(type(n) is not int or n <= 0 for n in
                (self.nominal_ns, self.lower_ns, self.upper_ns, self.precision_ns))
                or not self.lower_ns <= self.nominal_ns <= self.upper_ns
                or self.upper_ns - self.lower_ns < self.precision_ns - 1
                or not self.raw or not self.source
                or len(self.source_sha256) != 64
                or any(c not in '0123456789abcdef' for c in self.source_sha256)):
            raise ValueError('invalid_timestamp_provenance')


@dataclass(frozen=True)
class Quote:
    contract: str
    publisher: str
    instrument_id: int
    bid: str
    ask: str
    event: Timestamp
    provider_receive_ns: int
    available_ns: int
    source_sha256: str
    evidence_kind: str


@dataclass(frozen=True)
class BasisPolicy:
    reference: str
    expected_gc_contract: str
    expected_gc_id: int
    expected_gc_publisher: str = 'GLBX.MDP3/XCEC'
    expected_spot_publisher: str = 'FXCM/RatesXML3'
    minimum_samples: int = 5
    maximum_age_ns: int = 30 * SECOND
    maximum_skew_ns: int = SECOND
    minimum_independent_separation_ns: int = SECOND
    maximum_spread: str = '1'
    maximum_range: str = '.5'
    maximum_residual: str = '1'
    maximum_uncertainty: str = '2'
    price_change_bound_per_second: str = '.01'
    timing_bound_review_reference: str | None = None
    clock_review_reference: str | None = None
    clock_error_bound_ns: int = 0
    identity_review_reference: str | None = None

    def validate(self):
        if (not self.reference or not self.expected_gc_contract or self.expected_gc_id <= 0
                or type(self.minimum_samples) is not int or not 3 <= self.minimum_samples <= 128
                or self.maximum_age_ns <= 0 or self.maximum_skew_ns < 0
                or self.minimum_independent_separation_ns <= 0 or self.clock_error_bound_ns < 0
                or any(not Decimal(s).is_finite() or Decimal(s) <= 0 for s in
                       (self.maximum_spread, self.maximum_range, self.maximum_residual,
                        self.maximum_uncertainty, self.price_change_bound_per_second))):
            raise ValueError('invalid_reviewed_basis_policy')


def _time(ns):
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ns // 1000)


def certify(pairs, *, policy: BasisPolicy, cutoff_ns: int):
    """Fail closed on any invalid member; re-evaluate after restart/expiry.

    Decimal median, range and residual gates reuse GoldBasisService. Bounds
    additionally cover all residuals, both half-spreads and reviewed time/age
    drift. These are conditional worst-case envelopes, not statistical CIs.
    """
    policy.validate()
    result = dict(status='REJECTED', basis=None, uncertainty=None, conditional_uncertainty=None,
                  qualified_spot_mapping=False, pairs=[], rejection_reasons=[],
                  cutoff_ns=cutoff_ns, policy=asdict(policy), **SAFETY)
    result['input_sha256'] = digest(dict(pairs=pairs, policy=policy, cutoff_ns=cutoff_ns))
    if type(cutoff_ns) is not int or cutoff_ns <= 0 or not 1 <= len(pairs) <= 128:
        result['rejection_reasons'] = ['bounded_causal_quote_pairs_required']; return result
    service = GoldBasisService(minimum_samples=policy.minimum_samples,
        maximum_age=timedelta(microseconds=policy.maximum_age_ns // 1000),
        max_skew=timedelta(microseconds=policy.maximum_skew_ns // 1000),
        max_dispersion=Decimal(policy.maximum_range), max_residual=Decimal(policy.maximum_residual))
    reasons = set(); seen_gc=set(); seen_spot=set(); seen_spot_hashes=set(); previous=None; authentic=True
    try:
        for gc, spot in pairs:
            for q in (gc, spot):
                q.event.validate()
                prices = [Decimal(q.bid), Decimal(q.ask)]
                if (any(not p.is_finite() or p <= 0 for p in prices) or prices[0] > prices[1]
                        or prices[1] - prices[0] > Decimal(policy.maximum_spread)):
                    raise ValueError('invalid_crossed_incomplete_or_wide_quote')
                if (q.evidence_kind not in {'AUTHENTIC_ARCHIVED_RECORD', 'ENGINEERING_SYNTHETIC'}
                        or q.source_sha256 != q.event.source_sha256
                        or not q.event.nominal_ns <= q.provider_receive_ns
                        or q.provider_receive_ns > q.available_ns + policy.clock_error_bound_ns
                        or q.available_ns > cutoff_ns + policy.clock_error_bound_ns
                        or cutoff_ns - q.event.lower_ns > policy.maximum_age_ns
                        or q.event.upper_ns > cutoff_ns + policy.clock_error_bound_ns):
                    raise ValueError('stale_future_or_unavailable_quote')
                authentic &= q.evidence_kind == 'AUTHENTIC_ARCHIVED_RECORD'
                if not q.event.utc_authority_reference: reasons.add('timestamp_timezone_not_authoritative')
            if (gc.contract != policy.expected_gc_contract or gc.instrument_id != policy.expected_gc_id
                    or gc.publisher != policy.expected_gc_publisher or spot.contract != 'XAUUSD'
                    or spot.publisher != policy.expected_spot_publisher or spot.instrument_id != 0):
                raise ValueError('contract_or_publisher_mismatch')
            skew=max(abs(gc.event.lower_ns-spot.event.upper_ns), abs(gc.event.upper_ns-spot.event.lower_ns))
            if skew > policy.maximum_skew_ns: raise ValueError('uncertainty_adjusted_skew_exceeded')
            if (gc.event.nominal_ns in seen_gc or spot.event.nominal_ns in seen_spot or spot.source_sha256 in seen_spot_hashes
                    or (previous is not None and min(gc.event.lower_ns-previous[0],
                        spot.event.lower_ns-previous[1]) < policy.minimum_independent_separation_ns)):
                raise ValueError('duplicate_or_dependent_quote_pair')
            seen_gc.add(gc.event.nominal_ns); seen_spot.add(spot.event.nominal_ns); seen_spot_hashes.add(spot.source_sha256)
            previous=(gc.event.lower_ns, spot.event.lower_ns)
            service.add(contract=gc.contract, broker_bid=spot.bid, broker_ask=spot.ask,
                        futures_bid=gc.bid, futures_ask=gc.ask, broker_at=_time(spot.event.nominal_ns),
                        futures_at=_time(gc.event.nominal_ns), now=_time(cutoff_ns))
            gc_mid=(Decimal(gc.bid)+Decimal(gc.ask))/2; spot_mid=(Decimal(spot.bid)+Decimal(spot.ask))/2
            result['pairs'].append(dict(gc=encode(gc), spot=encode(spot), basis=str(gc_mid-spot_mid),
                gc_mid=str(gc_mid), spot_mid=str(spot_mid),
                gc_spread=str(Decimal(gc.ask)-Decimal(gc.bid)), spot_spread=str(Decimal(spot.ask)-Decimal(spot.bid)),
                maximum_timestamp_separation_ns=skew, gc_age_upper_ns=cutoff_ns-gc.event.lower_ns,
                spot_age_upper_ns=cutoff_ns-spot.event.lower_ns))
        estimate=service.estimate(contract=policy.expected_gc_contract, now=_time(cutoff_ns))
        centre=estimate['basis']
        envelope=max(abs(Decimal(p['basis'])-centre)
            +(Decimal(p['gc_spread'])+Decimal(p['spot_spread']))/2
            +Decimal(policy.price_change_bound_per_second)*Decimal(
                p['maximum_timestamp_separation_ns']+max(p['gc_age_upper_ns'],p['spot_age_upper_ns'])
                +2*policy.clock_error_bound_ns)/SECOND for p in result['pairs'])
        if envelope > Decimal(policy.maximum_uncertainty): raise ValueError('basis_uncertainty_excessive')
        if not policy.timing_bound_review_reference: reasons.add('unreviewed_time_price_change_bound')
        if not policy.clock_review_reference: reasons.add('authoritative_local_clock_review_missing')
        if not policy.identity_review_reference: reasons.add('instrument_identity_review_missing')
        if not authentic: reasons.add('synthetic_fixture_cannot_certify_genuine_basis')
        result.update(status='INDICATIVE' if reasons else 'CERTIFIED', basis=str(centre),
            conditional_uncertainty=str(envelope), uncertainty=None if reasons else str(envelope),
            observed_range=str(max(Decimal(p['basis']) for p in result['pairs'])-min(Decimal(p['basis']) for p in result['pairs'])),
            expires_ns=min(min(g.event.lower_ns,s.event.lower_ns) for g,s in pairs)+policy.maximum_age_ns,
            qualified_spot_mapping=not reasons, evidence_kind='AUTHENTIC_ARCHIVED_RECORD' if authentic else 'ENGINEERING_SYNTHETIC',
            rejection_reasons=sorted(reasons), uncertainty_kind='conditional_worst_case_envelope')
    except (ValueError, TypeError, ArithmeticError) as exc:
        result['rejection_reasons']=[str(exc)]
    return result


def map_level(level, *, contract, basis, now_ns):
    native=Decimal(str(level))
    if not native.is_finite() or native <= 0: raise ValueError('positive_native_level_required')
    result=dict(native_gc_level=str(native), native_gc_contract=contract,
                estimated_spot=None, spot_interval=None, qualified_spot_mapping=False,
                actual_executable_broker_price=None, **SAFETY)
    if (contract != basis.get('policy',{}).get('expected_gc_contract')
            or basis.get('status') == 'REJECTED' or basis.get('basis') is None
            or not basis.get('cutoff_ns',0) <= now_ns < basis.get('expires_ns',0)):
        result.update(status='UNAVAILABLE', rejection_reasons=['basis_rejected_expired_or_contract_mismatch']); return result
    qualified=basis['status']=='CERTIFIED' and basis.get('qualified_spot_mapping') is True
    centre=native-Decimal(basis['basis']); uncertainty=Decimal(basis['conditional_uncertainty'])
    uncertainty+=Decimal(basis['policy']['price_change_bound_per_second'])*Decimal(now_ns-basis['cutoff_ns'])/SECOND
    if centre-uncertainty <= 0: raise ValueError('invalid_mapped_interval')
    result.update(status='CERTIFIED_CONTEXT_MAPPING' if qualified else 'INDICATIVE_ONLY',
                  estimated_spot=str(centre), spot_interval=[str(centre-uncertainty),str(centre+uncertainty)],
                  qualified_spot_mapping=qualified, basis_input_sha256=basis['input_sha256'],
                  rejection_reasons=[] if qualified else basis['rejection_reasons'])
    return result
