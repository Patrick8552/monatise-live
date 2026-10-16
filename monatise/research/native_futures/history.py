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
        store=db.DBNStore.from_file(path);metadata=store.metadata
        for ordinal,row in enumerate(store):
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
        coverage=[]
        if (source['schema']=='ohlcv-1m' and admitted==count
                and str(metadata.dataset)=='GLBX.MDP3' and str(metadata.schema)==source['schema']
                and metadata.start==source['start_ns'] and metadata.end==source['end_ns']
                and metadata.limit==source['request_limit'] and not metadata.partial and not metadata.not_found
                and set(metadata.symbols)=={g.contract.metadata.raw_symbol for g in pipeline.gates.values()}):
            from monatise.research.databento.bar_coverage import HistoricalBarCoverage
            from monatise.research.institutional.models import digest
            details=dict(dataset=str(metadata.dataset),schema=str(metadata.schema),start=metadata.start,end=metadata.end,
                limit=metadata.limit,symbols=metadata.symbols,partial=metadata.partial,not_found=metadata.not_found)
            for g in pipeline.gates.values():
                if g.faults:continue
                proof=HistoricalBarCoverage(g.contract.identity,source['schema'],source['start_ns'],source['end_ns'],
                    source['retrieval_ns'],source['sha256'],digest(details),count,source['request_limit'],
                    'Verified complete DBN historical response; Databento OHLCV no-print semantics; not live-gap repair')
                g.coverage_reviews[proof.sha256]=proof;coverage.append(proof.sha256)
        results.append(dict(schema=source['schema'],records=count,admitted=admitted,non_OI_statistics_preserved_in_archive=ignored,source_sha256=source['sha256'],historical_response_coverage_sha256=coverage))
    return dict(mode=MODE,sources=results,old_capture_admission_changed=False,synthetic_bars=0,
        independent_exchange_completeness_certified=False)
