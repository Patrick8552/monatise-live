"""Causal candidate evaluation around the unchanged GoldBasisService/ContextMapper."""
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from monatise.adapters.databento_identity import timestamp_ns
from ..mapping import MappingPolicy, ContextMapper
from ..models import digest, encode, number
from . import SAFETY


@dataclass(frozen=True)
class BasisPolicy:
    reference: str
    maximum_age_ns: int = 30*10**9
    maximum_skew_ns: int = 10**9
    minimum_samples: int = 5
    maximum_uncertainty: Decimal = Decimal('2')
    maximum_basis_range: Decimal = Decimal('.5')
    price_change_bound_per_second: Decimal = Decimal('.01')
    timing_bound_review_reference: str = ''
    minimum_time_to_expiry_ns: int = 86400*10**9

    def __post_init__(self):
        MappingPolicy(self.reference,self.maximum_age_ns,self.maximum_skew_ns,self.minimum_samples,
                      number(self.maximum_basis_range,positive=True),number(self.maximum_uncertainty,positive=True))
        if (not self.timing_bound_review_reference or number(self.price_change_bound_per_second) < 0
                or type(self.minimum_time_to_expiry_ns) is not int or self.minimum_time_to_expiry_ns < 0):
            raise ValueError('reviewed_timing_and_expiry_uncertainty_policy_required')


def _weighted_median(values, weights):
    halfway = sum(weights)/2; running = Decimal(0)
    for v,w in sorted(zip(values,weights)):
        running += w
        if running >= halfway: return v
    raise ValueError('positive_weights_required')


def evaluate(*, contract, futures_quotes=(), broker_quotes=(), broker_sessions=None,
             futures_session=None, policy, cutoff_ns, futures_level=None):
    timestamp_ns(cutoff_ns)
    inputs = digest(dict(contract=contract,futures=futures_quotes,broker=broker_quotes,sessions=broker_sessions,
        futures_session=futures_session,policy=policy,cutoff_ns=cutoff_ns,level=futures_level))
    base = dict(version='gc-causal-basis-candidates-v1',status='MAPPING_UNAVAILABLE',
        input_sha256=inputs,contract=contract.identity,cutoff_ns=cutoff_ns,basis=None,uncertainty=None,
        mapped_spot_level=None,mapped_spot_interval=None,candidates={},baseline=None,
        evidence_kind='UNAVAILABLE',rejection_reasons=[],context_only=True,**SAFETY)
    if not futures_quotes or not broker_quotes:
        return dict(base,rejection_reasons=['genuine_synchronized_futures_and_broker_quotes_missing'])
    try:
        if contract.metadata.product != 'GC' or contract.asset_class != 'futures':
            raise ValueError('exact_GC_underlying_required')
        if cutoff_ns+policy.minimum_time_to_expiry_ns >= contract.metadata.expiration_ns:
            raise ValueError('unvalidated_expiry_window_rejected')
        baseline_policy = MappingPolicy(policy.reference,policy.maximum_age_ns,policy.maximum_skew_ns,
            policy.minimum_samples,number(policy.maximum_basis_range),number(policy.maximum_uncertainty))
        mapper = ContextMapper(contract=contract,broker_instrument='XAU/USD',policy=baseline_policy)
        values, bounds, clocks, oldest_clocks = [], [], [], []; seen_f=set();seen_b=set();namespace=None;session_key=None
        for f,b in zip(futures_quotes,broker_quotes,strict=True):
            top = f.payload[0]
            interval = broker_sessions.interval(b.event_ns)
            current = broker_sessions.interval(cutoff_ns)
            key = (broker_sessions.source_sha256,interval, f.contract.identity)
            if (f.contract != contract or f.schema != 'mbp-1' or interval is None or current != interval
                    or b.session_sha256 != broker_sessions.source_sha256
                    or b.specification.namespace != broker_sessions.specification_namespace
                    or namespace not in {None,b.specification.namespace} or session_key not in {None,key}
                    or f.source.position in seen_f or (b.source_sha256,b.ordinal) in seen_b
                    or b.receive_ns is None or b.event_ns > f.receive_ns
                    or abs(f.event_ns-b.event_ns) > policy.maximum_skew_ns
                    or max(f.source.admission_ns,b.available_ns,b.receive_ns) > cutoff_ns
                    or any(not 0 <= cutoff_ns-t <= policy.maximum_age_ns for t in (f.event_ns,f.receive_ns,b.event_ns))
                    or not futures_session or not futures_session.get('review_reference')
                    or not futures_session['start_ns'] <= min(f.event_ns,b.event_ns) <= cutoff_ns < futures_session['end_ns']):
                raise ValueError('identity_roll_session_availability_or_causal_alignment_rejected')
            mapper.add(f,b.basis_quote(cutoff_ns=cutoff_ns),now_ns=cutoff_ns,
                session_start_ns=max(interval[0],futures_session['start_ns']),
                session_end_ns=min(interval[1],futures_session['end_ns']),session_reference=digest(key))
            observed=(number(top[0])+number(top[3]))/2-b.midpoint
            if clocks and max(f.receive_ns,b.event_ns) <= clocks[-1]:
                raise ValueError('strictly_increasing_unique_pairs_required')
            values.append(observed);clocks.append(max(f.receive_ns,b.event_ns))
            oldest_clocks.append(min(f.event_ns,b.event_ns))
            half_spreads=(number(top[3])-number(top[0])+b.ask-b.bid)/2
            # Both clock mismatch and aging require a separately reviewed price
            # change bound. This is a conservative engineering envelope, not CI.
            timing_ns=abs(f.event_ns-b.event_ns)+(cutoff_ns-min(f.event_ns,b.event_ns))
            bounds.append(half_spreads+number(policy.price_change_bound_per_second)*Decimal(timing_ns)/10**9)
            seen_f.add(f.source.position);seen_b.add((b.source_sha256,b.ordinal))
            namespace=b.specification.namespace;session_key=key
        if len(values) < policy.minimum_samples:
            raise ValueError('insufficient_unique_causal_pairs')
        if max(values)-min(values) > number(policy.maximum_basis_range):
            raise ValueError('excessive_observed_basis_variation')
        centre=median(values);mad=median(abs(v-centre) for v in values)
        threshold=max(Decimal('.000000001'),3*mad)
        retained=[v for v in values if abs(v-centre)<=threshold]
        if len(retained)<policy.minimum_samples:
            raise ValueError('insufficient_outlier_resistant_samples')
        weights=[Decimal(1)/(1+Decimal(cutoff_ns-t)/10**9) for t in clocks]
        estimates={'rolling_median':centre,'recency_weighted_median':_weighted_median(values,weights),
                   'mad_filtered_median':median(retained)}
        original=number(futures_level,positive=True) if futures_level is not None else None
        candidates={}
        for method,estimate in estimates.items():
            # Include every admitted observation in the residual envelope, even
            # outliers excluded by an estimation method. No hidden uncertainty cut.
            uncertainty=max(abs(v-estimate) for v in values)+max(bounds)
            if uncertainty > number(policy.maximum_uncertainty):
                raise ValueError('excessive_mapping_uncertainty')
            mapped=original-estimate if original is not None else None
            if mapped is not None and mapped-uncertainty <= 0:
                raise ValueError('nonpositive_mapped_interval')
            candidates[method]=dict(basis=str(estimate),uncertainty=str(uncertainty),
                mapped_spot_level=None if mapped is None else str(mapped),
                mapped_spot_interval=None if mapped is None else [str(mapped-uncertainty),str(mapped+uncertainty)])
        baseline=mapper.estimate(now_ns=cutoff_ns,futures_level=futures_level)
        expiry=min(contract.metadata.expiration_ns-policy.minimum_time_to_expiry_ns,
                   min(oldest_clocks)+policy.maximum_age_ns,interval[1],futures_session['end_ns'])
        if expiry<=cutoff_ns:raise ValueError('mapping_freshness_expired')
        return dict(base,status='RESEARCH_CONTEXT_ESTIMATE',**candidates['rolling_median'],
            candidates=candidates,baseline=baseline,sample_count=len(values),outlier_retained=len(retained),
            expires_ns=expiry,broker_namespace=namespace,evidence_kind=mapper.kind,
            policy=encode(policy),confidence='EXPERIMENTAL_OBSERVED_ENVELOPE_NOT_STATISTICAL_CI',
            observed_basis=[str(v) for v in values],timestamps_ns=clocks,
            actual_broker_mid=str(broker_quotes[-1].midpoint),broker_price_observation_ns=broker_quotes[-1].event_ns,
            methodology='median-recency-weighted-median-MAD-filtered-median; residual-envelope+half-spreads+reviewed-timing-bound',
            production_replacement_approved=False)
    except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError) as exc:
        return dict(base,rejection_reasons=[str(exc)])


def held_out(*, contract, futures_quotes, broker_quotes, broker_sessions, futures_session, policy):
    """Walk-forward one-step pairs. Held-out broker prices never fit the model.
    Hyperparameters must be fixed before this evaluation; no automatic tuning.
    """
    rows=[]; k=policy.minimum_samples
    pairs=list(zip(futures_quotes,broker_quotes,strict=True))
    for i in range(k,len(pairs)):
        f,b=pairs[i]; cutoff=max(f.source.admission_ns,b.available_ns,f.receive_ns,b.receive_ns or 0)
        train=pairs[:i]
        report=evaluate(contract=contract,futures_quotes=[p[0] for p in train],broker_quotes=[p[1] for p in train],
            broker_sessions=broker_sessions,futures_session=futures_session,policy=policy,cutoff_ns=cutoff,
            futures_level=(number(f.payload[0][0])+number(f.payload[0][3]))/2)
        if report['status']=='RESEARCH_CONTEXT_ESTIMATE' and (f.contract!=contract or f.source.evidence_kind!=report.get('evidence_kind')
                or b.specification.namespace!=report.get('broker_namespace')
                or b.session_sha256!=broker_sessions.source_sha256
                or broker_sessions.interval(b.event_ns)!=broker_sessions.interval(cutoff)
                or b.evidence_kind!='ENGINEERING_SYNTHETIC' and b.evidence_kind!='POINT_IN_TIME_OBSERVATION'
                or b.available_ns>cutoff or f.source.admission_ns>cutoff
                or b.receive_ns is None or max(f.receive_ns,b.event_ns)<=max(train[-1][0].receive_ns,train[-1][1].event_ns)
                or not 0<=cutoff-b.event_ns<=policy.maximum_age_ns
                or abs(f.event_ns-b.event_ns)>policy.maximum_skew_ns):
            report=dict(status='MAPPING_UNAVAILABLE',rejection_reasons=['held_out_identity_or_clock_rejected'])
        metrics={}
        if report['status']=='RESEARCH_CONTEXT_ESTIMATE':
            for name,r in report['candidates'].items():
                error=number(r['mapped_spot_level'])-b.midpoint
                low,high=map(number,r['mapped_spot_interval'])
                metrics[name]=dict(error=str(error),absolute_error=str(abs(error)),inside_interval=low<=b.midpoint<=high)
            baseline=report['baseline']
            if baseline['status']=='MAPPING_CONTEXT_ESTIMATE':
                metrics['existing_GoldBasisService']=dict(absolute_error=str(abs(number(f.payload[0][0])/2+
                    number(f.payload[0][3])/2-number(baseline['basis'])-b.midpoint)))
        rows.append(dict(test_position=i,cutoff_ns=cutoff,train_positions=list(range(i)),
                         status=report['status'],rejection_reasons=report.get('rejection_reasons',[]),metrics=metrics,
                         training_input_sha256=report.get('input_sha256')))
    names={name for row in rows for name in row['metrics']}
    means={name:str(sum(number(row['metrics'][name]['absolute_error']) for row in rows if name in row['metrics'])/
                    sum(name in row['metrics'] for row in rows)) for name in sorted(names)}
    return dict(version='gc-basis-walk-forward-v1',status='EVALUATED' if means else 'BLOCKED_AUTHENTIC_INPUTS',
        rows=rows,mean_absolute_error=means,input_sha256=digest(pairs),policy_sha256=digest(policy),
        evidence_kind=pairs[0][0].source.evidence_kind if pairs else 'UNAVAILABLE',
        held_out_broker_prices_used_for_fit=False,production_replacement_approved=False,**SAFETY)
