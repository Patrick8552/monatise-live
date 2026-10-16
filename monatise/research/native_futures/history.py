"""Read-only native archives interpreted under the explicitly chosen source rules.

No statistical price cap, synthetic candle, paid acquisition or old-run repair.
"""
from pathlib import Path
import hashlib
from .information_gate import MODE


def seed_native_history(pipeline,sources,*,cutoff_ns):
    import databento as db
    import databento_dbn as dn
    total=0;results=[]
    for source in sources:
        path=Path(source['path'])
        if (path.is_symlink() or not path.is_file() or path.stat().st_size>32*1024**2
                or source['retrieval_ns']>cutoff_ns or source['schema'] not in {'ohlcv-1m','statistics'}
                or not 0<source['records']<source['request_limit']<=100000):
            raise ValueError('complete_bounded_native_history_receipt_required')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:
            raise ValueError('native_history_hash_mismatch')
        count=0;admitted=0;ignored=0
        for ordinal,row in enumerate(db.DBNStore.from_file(path)):
            count+=1;total+=1
            if count>source['records'] or total>100000:raise ValueError('native_history_count_budget')
            if row.instrument_id not in pipeline.gates or not source['start_ns']<=getattr(row,'ts_recv',row.ts_event)<source['end_ns']:
                raise ValueError('native_history_request_identity_or_time_mismatch')
            if source['schema']=='statistics' and isinstance(row,dn.StatMsg) and row.stat_type!=dn.StatType.OPEN_INTEREST:
                ignored+=1;continue
            gate=pipeline.gates[row.instrument_id]
            if getattr(gate,'quality_mode',None)!=MODE:raise ValueError('explicit_native_information_history_mode_required')
            r=pipeline.ingest(row,schema=source['schema'],archive_sha256=source['sha256'],ordinal=ordinal,
                capture_ns=source['retrieval_ns'],admission_ns=source['retrieval_ns'],
                evidence_kind='AUTHENTIC_ARCHIVED_RECORD')
            admitted+=int(r['accepted'])
        if count!=source['records']:raise ValueError('native_history_record_count_mismatch')
        results.append(dict(schema=source['schema'],records=count,admitted=admitted,non_OI_statistics_preserved_in_archive=ignored,source_sha256=source['sha256']))
    return dict(mode=MODE,sources=results,old_capture_admission_changed=False,synthetic_bars=0,
        independent_exchange_completeness_certified=False)
