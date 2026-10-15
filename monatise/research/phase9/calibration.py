"""Chronological calibration and untouched holdout validation, never trade gates."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from statistics import median

from monatise.research.institutional.models import digest, number
from .quality import PlausibilityPolicy, PriceGuard


def prices(value):
    if value.schema=='trades':return (number(value.payload[0],positive=True),)
    if value.schema.startswith('ohlcv-'):return tuple(Decimal(p)/10**9 for p in value.payload[2:6])
    if value.schema in {'mbp-1','mbp-10'}:
        b,a=value.payload[0][0],value.payload[0][3]
        if b is None or a is None:return ()
        return number(b,positive=True),number(a,positive=True)
    return ()


def _ordered(rows,allow_tied_events):
    if len({v.source.position for v in rows})!=len(rows):return False
    key=lambda v:(v.event_ns,v.receive_ns or v.event_ns,v.source.ordinal)
    return all((key(b)>key(a) if allow_tied_events else b.event_ns>a.event_ns) for a,b in zip(rows,rows[1:]))


def fit(training, *, review_reference, minimum_samples=8, scale=Decimal(8),allow_tied_events=False):
    """Fit one exact contract/schema. Publication role determines the sample unit.

    Candle calibration uses full OHLC excursions; trade calibration uses execution
    increments. This avoids applying a tick-to-tick floor to minute-bar ranges.
    The robust center/MAD cap excludes gross training anomalies from the floor.
    It does not certify that every structurally valid training price is genuine.
    """
    if type(allow_tied_events) is not bool or type(minimum_samples) is not int or minimum_samples<3 or number(scale)<3:raise ValueError('bounded_calibration_parameters_required')
    rows=tuple(training)
    if len(rows)<minimum_samples or not review_reference:raise ValueError('insufficient_calibration_evidence')
    c,schema=rows[0].contract,rows[0].schema
    if any((v.contract.identity,v.contract.tick_size,v.contract.multiplier)!=(c.identity,c.tick_size,c.multiplier) or v.schema!=schema or not prices(v) for v in rows):raise ValueError('exact_calibration_scope_required')
    if not _ordered(rows,allow_tied_events):raise ValueError('distinct_chronological_training_required')
    last=prices(rows[0])[-1];excursions=[];spreads=[]
    for v in rows[1:]:
        ps=prices(v);excursions.append(max(abs(p-last) for p in ps)/c.tick_size);last=ps[-1]
        if schema.startswith('mbp-'):spreads.append((ps[-1]-ps[0])/c.tick_size)
    center=median(excursions);mad=median(abs(x-center) for x in excursions)
    robust_cap=max(Decimal(1),center+scale*Decimal('1.4826')*mad)
    retained=sorted(x for x in excursions if x<=robust_cap)
    # A tick is the physical minimum. Three times the observed robust envelope
    # is an explicit research policy, validated separately below, not a market law.
    floor=int((max(Decimal(1),max(retained,default=Decimal(1)))*3).to_integral_value(rounding=ROUND_CEILING))
    spread=int((max(spreads,default=Decimal(floor))*3).to_integral_value(rounding=ROUND_CEILING))
    policy=PlausibilityPolicy(c.metadata.product,max(1,floor),scale,max(1,spread),review_reference,digest(rows))
    return Calibration(c,schema,policy,rows[-1],digest(rows),len(rows),len(excursions)-len(retained),allow_tied_events)


@dataclass(frozen=True)
class Calibration:
    contract: object
    schema: str
    policy: PlausibilityPolicy
    anchor_observation: object
    training_sha256: str
    training_count: int
    trimmed_training_increments: int
    allow_tied_events: bool = False

    @property
    def sha256(self):return digest(self)

    def validate(self, holdout, *, maximum_rejection_fraction=Decimal('0.01'), minimum_samples=8):
        if type(minimum_samples) is not int or minimum_samples<3 or not Decimal(0)<=number(maximum_rejection_fraction)<=Decimal(1):raise ValueError('bounded_holdout_parameters_required')
        rows=tuple(holdout);anchor=self.anchor_observation
        if len(rows)<minimum_samples:raise ValueError('insufficient_independent_holdout')
        if any((v.contract.identity,v.contract.tick_size,v.contract.multiplier)!=(self.contract.identity,self.contract.tick_size,self.contract.multiplier) or v.schema!=self.schema or v.event_ns<=anchor.event_ns for v in rows):
            raise ValueError('holdout_overlap_or_scope_mismatch')
        if not _ordered(rows,self.allow_tied_events):raise ValueError('ordered_holdout_required')
        g=PriceGuard(self.contract,self.policy,anchor=prices(anchor)[-1],anchor_ns=anchor.event_ns,
            anchor_sha256=anchor.source.record_sha256)
        rejected=[]
        for v in rows:
            ps=prices(v);reason=g.inspect(ps,v.event_ns)
            if reason:rejected.append(dict(event_ns=v.event_ns,record_sha256=v.source.record_sha256,reason=reason))
            else:g.commit(ps[-1])
        fraction=Decimal(len(rejected))/len(rows)
        return dict(status='HOLDOUT_PASSED' if fraction<=maximum_rejection_fraction else 'HOLDOUT_FAILED',
            calibration_sha256=self.sha256,training_sha256=self.training_sha256,holdout_sha256=digest(rows),
            training_count=self.training_count,holdout_count=len(rows),rejected_count=len(rejected),
            rejection_fraction=str(fraction),maximum_rejection_fraction=str(maximum_rejection_fraction),
            rejected=rejected,independent_chronological_holdout=True,full_regime_coverage_certified=False,
            first_holdout_event_ns=rows[0].event_ns,last_training_event_ns=anchor.event_ns)
