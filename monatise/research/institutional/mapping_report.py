"""Complete mapping report using the existing context mapper and basis engine."""
from .mapping import ContextMapper,MappingPolicy,RELATIONSHIPS
from .models import digest,encode,number


def report(*, contract, futures_quotes, broker_quotes, broker_sessions, futures_session,
           policy, cutoff_ns, level=None):
    instrument=RELATIONSHIPS.get(contract.metadata.product)
    base=dict(source_instrument=contract.metadata.product,source_contract=contract.identity,
        source_price=None if level is None else str(number(level,positive=True)),broker_instrument=instrument,
        broker_identity=None,observed_basis=None,mapped_reference_level=None,mapping_timestamp_ns=cutoff_ns,
        observation_timestamps=[],valid_paired_observations=0,uncertainty=None,expiry_ns=None,
        data_quality='UNAVAILABLE',mapping_valid=False,rejection_reasons=[],status='MAPPING_UNAVAILABLE',
        input_sha256=digest(dict(contract=contract,futures=futures_quotes,broker=broker_quotes,
            broker_sessions=broker_sessions,futures_session=futures_session,cutoff_ns=cutoff_ns,policy=policy,level=level)),
        context_only=True,publication_eligible=False,approval_eligible=False,execution_eligible=False)
    if not futures_quotes or not broker_quotes:
        base['rejection_reasons']=['genuine_synchronized_quotes_unavailable'];return base
    try:
        base['observation_timestamps']=[dict(futures_event_ns=f.event_ns,futures_receive_ns=f.receive_ns,
            futures_available_ns=f.source.admission_ns,broker_event_ns=b.event_ns,broker_receive_ns=b.receive_ns,
            broker_available_ns=b.available_ns,broker_local_admission_ns=b.admission_ns)
            for f,b in zip(futures_quotes,broker_quotes)]
        mapper=ContextMapper(contract=contract,broker_instrument=instrument,policy=policy)
        seen=set();future_positions=set();previous=None
        for future,broker in zip(futures_quotes,broker_quotes,strict=True):
            spec=broker.specification
            if (broker_sessions is None or broker_sessions.specification_namespace!=spec.namespace
                    or broker.session_sha256!=broker_sessions.source_sha256
                    or broker_sessions.interval(cutoff_ns) is None
                    or future.contract!=contract or spec.instrument!=instrument
                    or broker.event_ns>future.receive_ns
                    or broker.available_ns>cutoff_ns
                    or any(not 0<=cutoff_ns-t<=policy.maximum_age_ns for t in (future.event_ns,future.receive_ns,broker.event_ns))
                    or broker.receive_ns is not None and broker.receive_ns>cutoff_ns):
                raise ValueError('mapping_identity_session_or_future_data_rejected')
            position=(broker.source_sha256,broker.ordinal)
            if position in seen or future.source.position in future_positions or previous is not None and broker.event_ns<=previous:
                raise ValueError('distinct_ordered_broker_pair_evidence_required')
            interval=broker_sessions.interval(broker.event_ns)
            start=max(interval[0],futures_session['start_ns']);end=min(interval[1],futures_session['end_ns'])
            if not futures_session.get('review_reference'):raise ValueError('reviewed_futures_session_required')
            mapper.add(future,broker.basis_quote(cutoff_ns=cutoff_ns),now_ns=cutoff_ns,
                session_start_ns=start,session_end_ns=end,session_reference=digest([broker_sessions,futures_session]))
            seen.add(position);future_positions.add(future.source.position);previous=broker.event_ns
        estimate=mapper.estimate(now_ns=cutoff_ns,futures_level=level)
        if estimate['status']!='MAPPING_CONTEXT_ESTIMATE':raise ValueError(estimate['reason'])
        base.update(status=estimate['status'],broker_identity=encode(spec),observed_basis=estimate['observed_basis'],
            mapped_reference_level=str(number(level)-number(estimate['basis'])) if level is not None else None,
            valid_paired_observations=estimate['sample_count'],uncertainty=estimate['uncertainty'],
            expiry_ns=estimate['expiration_ns'],data_quality='OBSERVED_CONTEXT_ESTIMATE',mapping_valid=True,
            estimate=estimate)
    except (ValueError,TypeError,ArithmeticError,AttributeError,KeyError) as exc:
        base['rejection_reasons']=[str(exc)]
    return base
