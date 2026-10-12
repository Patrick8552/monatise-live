"""Read verified, already-authorized archives; never acquire or rewrite sources."""
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from monatise.research.databento.archive import NativeDBNArchive, dbn_records, sha256_file
from monatise.research.databento.acquisition import HistoricalRequest, inspect_request_archive
from monatise.research.databento.datasets import DatasetCapability
from .models import digest, encode
from .normalize import EconomicConvention, definition, observation
from .indicators import trade_indicators, book_indicator, volatility

START_NS = 1791212400*10**9  # 2026-10-05 15:00 UTC
END_NS = START_NS+15*60*10**9


def process_gc(*, data_root, prepared_file, repository):
    import databento_dbn as dbn
    root, prepared_file, repository = map(Path,(data_root,prepared_file,repository))
    accepted=json.loads((repository/'docs/audits/gc-qualification-validation.json').read_text())
    if sha256_file(prepared_file) != accepted['prepared_input_sha256']:
        raise ValueError('accepted_native_manifest_index_changed')
    prepared=json.loads(prepared_file.read_text())
    if not any(s['start_ns'] <= START_NS < END_NS <= s['end_ns'] for s in prepared['sessions']):
        raise ValueError('native_sample_session_unavailable')
    archive=NativeDBNArchive.open_existing(root/'native-dbn')
    chosen=[]
    for item in prepared['source_archives']:
        if item['schema'] not in {'definition','trades','mbp-1','ohlcv-1m'}:
            continue
        path=root/item['manifest_file']
        if sha256_file(path) != item['manifest_sha256']:
            raise ValueError('native_manifest_tampered')
        manifest=json.loads(path.read_text());manifest=manifest.get('result',manifest)
        params=dict(manifest['request']);params['contracts']=tuple(tuple(c) for c in params['contracts'])
        request=HistoricalRequest(**params)
        if not request.start_ns <= START_NS < END_NS <= request.end_ns:
            continue
        if (manifest['status'] != 'ARCHIVED' or manifest['evidence_kind'] != 'AUTHENTIC_HISTORICAL_DOWNLOAD'
                or request.dataset != 'GLBX.MDP3' or request.contracts != ((1,41271,'GCZ6'),)):
            raise ValueError('accepted_authentic_exact_gc_source_required')
        native=archive.verify(manifest['archive_sha256'])
        coverage=inspect_request_archive(native,request)
        if coverage != manifest['coverage'] or not coverage['transport_complete']:
            raise ValueError('native_archive_request_coverage_changed')
        chosen.append((request,manifest,native,item['manifest_sha256']))
    if sorted(r.schema for r,_,_,_ in chosen) != ['definition','mbp-1','ohlcv-1m','trades']:
        raise ValueError('single_unambiguous_cached_scope_per_schema_required')
    cap=DatasetCapability('GLBX.MDP3',('definition','trades','mbp-1','ohlcv-1m'),
        min(m['retrieval_ns'] for _,m,_,_ in chosen),digest([h for *_,h in chosen]))
    definition_source=next((m,p) for r,m,p,_ in chosen if r.schema=='definition')
    m,p=definition_source
    definitions=[(ordinal,r) for ordinal,r in enumerate(r for r in dbn_records(p) if not isinstance(r,dbn.Metadata))
                 if isinstance(r,dbn.InstrumentDefMsg) and r.ts_recv <= START_NS]
    if not definitions:
        raise ValueError('point_in_time_native_definition_unavailable')
    definition_ordinal,row=max(definitions,key=lambda pair:(pair[1].ts_recv,pair[1].ts_event))
    # Reuse the independently reviewed exact native GC contract validator too.
    from monatise.adapters.databento_identity import DatabentoPublisherPolicy
    from monatise.research.gc_fib.native_contract import reconstruct_native_gcz6
    policy=DatabentoPublisherPolicy(((1,'GLBX.MDP3','GLBX'),),cap.observed_at_ns,cap.source_sha256)
    reconstruct_native_gcz6(row,identity_policy=policy,retrieval_ns=max(m['retrieval_ns'],cap.observed_at_ns))
    contract=definition(row,capability=cap,publishers={1:('GLBX.MDP3','GLBX')},
        as_of_ns=max(m['retrieval_ns'],cap.observed_at_ns),
        convention=EconomicConvention('GC',Decimal('.1'),Decimal(100),'USD_PER_TRYOZ','databento-native-gcz6-reference-v1'))
    definition_observation=observation(row,schema='definition',contract=contract,
        archive_sha256=m['archive_sha256'],ordinal=definition_ordinal,retrieval_ns=m['retrieval_ns'],
        admission_ns=m['ingestion_ns'],evidence_kind='AUTHENTIC_ARCHIVED_RECORD',enabled_schemas=cap.schemas)
    trades, candles, last_book=[],[],None
    manifest_evidence=[]
    for request,manifest,native,manifest_hash in chosen:
        manifest_evidence.append(dict(schema=request.schema,request_sha256=request.sha256,
            archive_sha256=manifest['archive_sha256'],manifest_sha256=manifest_hash,
            coverage=manifest['coverage'],billing_status='HISTORIC_UNRECONCILED'))
        if request.schema=='definition': continue
        for ordinal,record in enumerate(r for r in dbn_records(native) if not isinstance(r,dbn.Metadata)):
            clock=getattr(record,'ts_recv',record.ts_event)
            if not START_NS <= clock < END_NS:
                continue
            if request.schema=='mbp-1':
                # Keep the last observed quote, without discarding a bad last quote
                # or treating book updates as another executed-volume contribution.
                if record.flags & (4|8|32): raise ValueError('sample_book_quality_invalid')
                last_book=(record,ordinal,manifest)
                continue
            value=observation(record,schema=request.schema,contract=contract,
                archive_sha256=manifest['archive_sha256'],ordinal=ordinal,
                retrieval_ns=manifest['retrieval_ns'],admission_ns=manifest['ingestion_ns'],
                evidence_kind='AUTHENTIC_ARCHIVED_RECORD',enabled_schemas=cap.schemas)
            (trades if request.schema=='trades' else candles).append(value)
    if last_book is None:
        raise ValueError('sample_two_sided_book_unavailable')
    row,ordinal,manifest=last_book
    book=observation(row,schema='mbp-1',contract=contract,archive_sha256=manifest['archive_sha256'],ordinal=ordinal,
        retrieval_ns=manifest['retrieval_ns'],admission_ns=manifest['ingestion_ns'],
        evidence_kind='AUTHENTIC_ARCHIVED_RECORD',enabled_schemas=cap.schemas)
    scope=dict(start_ns=START_NS,end_ns=END_NS,session_reference=prepared['session_review_sha256'])
    results=dict(trades=trade_indicators(trades,**scope),book=book_indicator(book),volatility=volatility(candles,**scope))
    normalized=encode(dict(contract=contract,definition=definition_observation,trades=trades,candles=candles,book=book))
    return dict(evidence_kind='AUTHENTIC_ARCHIVED_RECORD',scope=scope,contract=encode(contract),
        manifests=manifest_evidence,normalized=normalized,normalized_sha256=digest(normalized),
        indicators=results,counts=dict(trades=len(trades),candles=len(candles),book_snapshots=1),
        point_in_time_certified=False,source_availability='RETROSPECTIVE_ARCHIVE_ADMISSION',
        complete_exchange_continuity=False,execution_eligible=False)
