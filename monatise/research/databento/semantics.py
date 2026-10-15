"""Versioned internal mapping and schema-specific capability decisions.

Databento performs exchange normalization. This layer preserves DBN meaning;
it does not repair prices/clocks, grant capture continuity or fit thresholds.
"""
from monatise.research.institutional.models import digest,MAPPING_VERSION

VERSION=MAPPING_VERSION
EXCURSION='max-inspected-price-distance-from-previous-reference-v2'


def flag_eligibility(schema,flags, *, reviewed_mbo_snapshot=False):
    if type(flags) is not int or not 0<=flags<=255:raise ValueError('native_flags_required')
    if reviewed_mbo_snapshot and (schema!='mbo' or not flags&32):raise ValueError('explicit_mbo_snapshot_context_required')
    snapshot=bool(schema=='mbo' and flags&32 and reviewed_mbo_snapshot)
    receive_valid=not bool(flags&8)
    channel_valid=not bool(flags&4)
    ordinary=channel_valid and receive_valid and not bool(flags&32)
    return dict(flags=flags,channel_gap_flagged=not channel_valid,receive_timestamp_valid=receive_valid,
        source_continuity_certified=False,ordinary_record_eligible=ordinary,
        snapshot_book_seed_eligible=bool(snapshot and channel_valid and not flags&(16|64)),
        trade_volume_eligible=bool(schema=='trades' and ordinary),
        trade_price_features_eligible=bool(schema=='trades' and ordinary),
        event_time_ohlcv_eligible=bool(schema=='trades' and ordinary),
        native_candle_eligible=bool(schema.startswith('ohlcv-') and ordinary),
        temporal_book_liquidity_eligible=bool(schema in {'mbp-1','mbp-10','mbo'} and ordinary),
        reason='SCHEMA_REVIEWED_MBO_SNAPSHOT_NO_RECEIVE_CLOCK' if snapshot and not receive_valid else
            'NATIVE_PRICE_OR_RECEIVE_OR_SNAPSHOT_QUALITY_RESTRICTED' if not ordinary else None,
        schema=schema,version=VERSION)


def assess_native_record(record, *, schema,contract,capture_upper_ns):
    """Independent dimensions; eligibility remains conservative for all trades.

    These diagnostics never admit a flagged execution or substitute its clock.
    Numeric fields are not returned: raw DBN and its hash are the evidence.
    """
    from monatise.adapters.databento_identity import timestamp_ns
    import hashlib
    import databento_dbn as dbn
    expected={'trades':dbn.TradeMsg,'ohlcv-1s':dbn.OHLCVMsg,'ohlcv-1m':dbn.OHLCVMsg,'ohlcv-1h':dbn.OHLCVMsg}
    m=contract.metadata;tick=int(contract.tick_size*10**9)
    dims=dict(contract_identity_valid=(getattr(record,'publisher_id',None),getattr(record,'instrument_id',None))==(m.publisher_id,m.instrument_id),
        schema_valid=schema in expected and isinstance(record,expected[schema]),price_valid=False,quantity_valid=False,
        event_timestamp_valid=False,receive_timestamp_valid=False,capture_time_valid=False)
    flags=flag_eligibility(schema,int(getattr(record,'flags',0)))
    try:
        event=timestamp_ns(record.ts_event);receive=timestamp_ns(getattr(record,'ts_recv',event))
        dims.update(event_timestamp_valid=m.event_ns<=event<m.expiration_ns,
            receive_timestamp_valid=flags['receive_timestamp_valid'] and m.event_ns<=receive<m.expiration_ns,
            capture_time_valid=max(event,receive)<=capture_upper_ns)
    except (ValueError,TypeError,AttributeError):pass
    if schema=='trades' and isinstance(record,dbn.TradeMsg):
        dims['price_valid']=0<record.price<2**63-1 and record.price%tick==0
        dims['quantity_valid']=0<record.size<2**32-1
        dims['schema_valid'] &= str(record.action)=='T' and str(record.side) in {'A','B','N'}
    elif schema.startswith('ohlcv-') and isinstance(record,dbn.OHLCVMsg):
        from .candles import WIDTHS
        expected_rtype={'ohlcv-1s':dbn.RType.OHLCV_1S,'ohlcv-1m':dbn.RType.OHLCV_1M,'ohlcv-1h':dbn.RType.OHLCV_1H}.get(schema)
        dims['schema_valid'] &= record.rtype==expected_rtype and record.ts_event%WIDTHS.get(schema[6:],1)==0
        o,h,l,c=record.open,record.high,record.low,record.close
        dims['price_valid']=all(0<p<2**63-1 and p%tick==0 for p in (o,h,l,c)) and l<=min(o,c)<=max(o,c)<=h
        dims['quantity_valid']=0<=record.volume<2**64-1
    eligible=all(dims.values()) and flags['ordinary_record_eligible']
    return dict(version=VERSION,dimensions=dims,flags=flags,
        native_record_sha256=hashlib.sha256(bytes(record)).hexdigest(),
        capabilities={k:bool(eligible and v) for k,v in flags.items() if k.endswith('_eligible')},
        price_plausibility='SEPARATE_PRICE_GUARD_REQUIRED',continuity='SEPARATE_SOURCE_REVIEW_REQUIRED',
        original_timestamps_preserved=True,rejected_records_readmitted=False)


def transformation_provenance(value):
    """Hash-only public description; original fixed prices remain in raw DBN."""
    return dict(version=VERSION,excursion_measurement=EXCURSION,schema=value.schema,
        contract=value.contract.identity,definition_sha256=value.contract.metadata.definition_sha256,
        native_record_sha256=value.source.record_sha256,source_position=value.source.position,
        canonical_sha256=digest(value),index_clock='PROVIDER_RECEIVE' if value.receive_ns is not None else 'EVENT',
        original_timestamps_preserved=True,source_multiplicity_preserved=True,
        quality=flag_eligibility(value.schema,value.flags),execution_eligible=False)
