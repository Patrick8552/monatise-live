"""Feature-aware freshness; timestamps and frozen-selector lifetimes stay immutable."""
from dataclasses import dataclass
from enum import StrEnum

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.institutional.models import digest, hash_required
from . import SAFETY

NS = 10**9


class Availability(StrEnum):
    FULL_ANALYSIS = 'FULL_ANALYSIS'
    PARTIAL_ANALYSIS = 'PARTIAL_ANALYSIS'
    CONTEXT_ONLY = 'CONTEXT_ONLY'
    UNAVAILABLE = 'UNAVAILABLE'


@dataclass(frozen=True)
class FreshnessPolicy:
    instrument: str
    feature: str
    preferred_ns: int
    context_limit_ns: int
    evidence_reference: str
    evidence_sha256: str
    pair_tolerance_ns: int | None = None

    def __post_init__(self):
        hash_required(self.evidence_sha256)
        if (not self.instrument or not self.feature or not self.evidence_reference
                or type(self.preferred_ns) is not int or type(self.context_limit_ns) is not int
                or not 0 < self.preferred_ns <= self.context_limit_ns <= 7*86400*NS
                or self.pair_tolerance_ns is not None and
                (type(self.pair_tolerance_ns) is not int or not 0 <= self.pair_tolerance_ns <= NS)):
            raise ValueError('reviewed_feature_specific_freshness_policy_required')

    @property
    def sha256(self): return digest(self)

    def assess(self, *, source_ns, available_ns, now_ns, paired_ns=None, expires_ns=None, clock_review=None):
        for t in (source_ns, available_ns, now_ns): timestamp_ns(t)
        if paired_ns is not None: timestamp_ns(paired_ns)
        if expires_ns is not None: timestamp_ns(expires_ns)
        lower,upper = clock_review.bounds(now_ns) if clock_review else (0,0)
        capture_lower,capture_upper = clock_review.bounds(available_ns) if clock_review else (0,0)
        utc_now = now_ns+max(0,upper)
        utc_capture = available_ns+capture_upper
        age = utc_now-source_ns
        reason, state, sync = None, 'STALE', 'UNAVAILABLE'
        if source_ns > utc_capture or available_ns > now_ns or age < 0:
            reason = 'future_or_unavailable_at_cutoff'
        elif expires_ns is not None and utc_now >= expires_ns:
            reason, sync = 'original_expiry_preserved', 'CONTEXT_ONLY'
        elif self.pair_tolerance_ns is not None and (paired_ns is None or paired_ns > now_ns
                or abs(source_ns-paired_ns) > self.pair_tolerance_ns):
            reason = 'mandatory_quote_pair_not_synchronized'
        elif age <= self.preferred_ns:
            state, sync = 'FRESH', 'TOLERANT_SYNC' if clock_review else 'STRICT_SYNC'
        elif age <= self.context_limit_ns:
            state, sync = 'ACCEPTABLE_DELAY', 'TOLERANT_SYNC'
        else:
            reason = 'feature_freshness_limit_exceeded'
        return dict(status=state, synchronization=sync, age_ns=age, source_ns=source_ns,
            available_ns=available_ns, evaluated_ns=now_ns, expires_ns=expires_ns,
            capture_utc_bounds_ns=(available_ns+capture_lower,utc_capture),
            clock_review_sha256=digest(clock_review) if clock_review else None,
            contextual_eligible=sync in {'STRICT_SYNC','TOLERANT_SYNC'},
            historical_context_eligible=source_ns <= utc_capture and available_ns <= now_ns,
            reason=reason, policy_sha256=self.sha256, **SAFETY)


def inherited_policy(contract, feature, *, timeframe_ns=None):
    """Existing conservative limits. Wider tolerances require explicit reviewed evidence.

    Definitions live until expiry; OI uses its reference/publication cadence;
    candles use two intervals (existing hierarchy policy), not trade heartbeat age.
    No new universal latency allowance is asserted to be empirically calibrated.
    """
    limits = {'trades': 10*NS, 'book': 10*NS, 'options_pricing': 30*NS,
              'open_interest': 4*86400*NS}
    if feature == 'candles':
        if type(timeframe_ns) is not int or timeframe_ns <= 0: raise ValueError('timeframe_required')
        limit = 2*timeframe_ns
    else:
        limit = limits[feature]
    ref = 'inherited:live_models-10s/options-30s/OI-4days/hierarchy-two-intervals-v1'
    return FreshnessPolicy(contract.metadata.raw_symbol, feature, limit, limit, ref, digest(ref),
        NS if feature == 'options_pricing' else None)


def envelope(contract, components, *, mandatory=(), requested=(), now_ns, context_only=False):
    """Availability describes the requested scope, independently of NO_TRADE."""
    success = [k for k, v in components.items() if v.get('available') is True]
    missing = [k for k in dict.fromkeys((*mandatory, *requested)) if k not in success]
    essential = [k for k in mandatory if k not in success]
    status = (Availability.UNAVAILABLE if not success else
              Availability.CONTEXT_ONLY if context_only or essential else
              Availability.PARTIAL_ANALYSIS if missing else Availability.FULL_ANALYSIS)
    value = dict(version='phase9-analytical-availability-v1', availability=status,
        instrument=contract.metadata.raw_symbol, contract=contract.identity,
        dataset=contract.metadata.dataset, provider='Databento', evaluated_ns=now_ns,
        successful_components=success, missing_or_failed_components=missing, components=components,
        contextual_eligible=bool(success), qualification_status='NOT_EVALUATED', decision='NO_TRADE',
        complete_exchange_continuity=False, **SAFETY)
    value['reproducibility_sha256'] = digest(value)
    return value
