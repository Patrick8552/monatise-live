"""Local ES/NQ archive diagnostics; unsettled billing never grants admission."""
import json
from pathlib import Path

from monatise.research.databento.archive import NativeDBNArchive,dbn_records,sha256_file
from monatise.research.databento.acquisition import HistoricalRequest,inspect_request_archive
from monatise.research.databento.datasets import DatasetCapability
from .native_index import validate
from .native import START_NS,END_NS
from .normalize import observation
from .models import encode,digest
from .indicators import trade_indicators,volatility


def diagnose(data_root, *, allow_engineering=False):
    """Diagnostics may inspect quarantined inputs, but never call cached admission.

    Manifests are trusted reviewed operator inputs, not an authenticity oracle.
    No prices are admitted to canonical scoring or broker execution here.
    """
    import databento_dbn as dbn
    root=Path(data_root);archive=NativeDBNArchive.open_existing(root/'native-dbn');groups={};manifest_hashes={}
    for path in sorted(root.glob('result-*.json')):
        if path.is_symlink():raise ValueError('regular_reviewed_manifest_required')
        before=sha256_file(path);m=json.loads(path.read_text());params=dict(m['request'])
        params['contracts']=tuple(tuple(c) for c in params['contracts']);r=HistoricalRequest(**params)
        if (len(r.contracts)!=1 or r.contracts[0][2] not in {'ESZ6','NQZ6'}
                or r.schema not in {'definition','trades','ohlcv-1m'} or m['status']!='ARCHIVED'
                or m['evidence_kind'] not in {'AUTHENTIC_HISTORICAL_DOWNLOAD','ENGINEERING_SYNTHETIC'}
                or m['evidence_kind']=='ENGINEERING_SYNTHETIC' and not allow_engineering):
            raise ValueError('reviewed_exact_ES_NQ_archives_required')
        coverage=inspect_request_archive(archive.verify(m['archive_sha256']),r)
        if coverage!=m['coverage'] or not coverage['transport_complete']:
            raise ValueError('incomplete_or_revised_native_archive')
        if r.schema!='definition' and (r.start_ns,r.end_ns)!=(START_NS,END_NS):
            raise ValueError('exact_phase5_native_sample_required')
        if r.schema=='definition' and (r.end_ns!=START_NS or not START_NS-86400*10**9<=r.start_ns<START_NS):
            raise ValueError('reviewed_pre_sample_definition_window_required')
        product=r.contracts[0][2][:-2];group=groups.setdefault(product,{})
        if r.schema in group:raise ValueError('ambiguous_duplicate_schema_archive')
        group[r.schema]=(r,m);manifest_hashes[str(path.name)]=before
        if sha256_file(path)!=before:raise ValueError('manifest_changed_during_diagnostics')
    if set(groups)!={'ES','NQ'}:raise ValueError('both_native_index_scopes_required')
    result={}
    for product,group in sorted(groups.items()):
        if set(group)!={'definition','trades','ohlcv-1m'}:raise ValueError('complete_price_schema_bundle_required')
        r,m=group['definition']
        definitions=[x for x in dbn_records(archive.verify(m['archive_sha256'])) if isinstance(x,dbn.InstrumentDefMsg)]
        if not definitions:raise ValueError('native_definition_required')
        row=max(definitions,key=lambda x:(x.ts_recv,x.ts_event))
        cap=DatasetCapability('GLBX.MDP3',tuple(sorted(group)),m['preflight']['observed_at_ns'],m['preflight']['metadata_sha256'])
        contract=validate(row,capability=cap,publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=m['ingestion_ns'])
        if contract.identity[1:4]!=r.contracts[0] or row.ts_recv>=START_NS:
            raise ValueError('exact_native_definition_lineage_required')
        kind='ENGINEERING_SYNTHETIC' if m['evidence_kind']=='ENGINEERING_SYNTHETIC' else 'AUTHENTIC_ARCHIVED_RECORD'
        normalized={};costs=[]
        for schema,(request,manifest) in sorted(group.items()):
            if request.contracts!=(contract.identity[1:4],) or manifest['evidence_kind']!=m['evidence_kind']:
                raise ValueError('mixed_contract_or_source_kind')
            values=tuple(observation(record,schema=schema,contract=contract,archive_sha256=manifest['archive_sha256'],
                ordinal=i,retrieval_ns=manifest['retrieval_ns'],admission_ns=manifest['ingestion_ns'],
                evidence_kind=kind,enabled_schemas=cap.schemas)
                for i,record in enumerate(x for x in dbn_records(archive.verify(manifest['archive_sha256'])) if not isinstance(x,dbn.Metadata)))
            normalized[schema]=values
            costs.append(dict(request_sha256=request.sha256,archive_sha256=manifest['archive_sha256'],
                provider_estimate_usd=manifest['preflight']['estimated_usd'],actual_billed_usd=manifest.get('actual_billed_usd'),
                billing_status=manifest.get('actual_cost_status','UNKNOWN')))
        bars=normalized['ohlcv-1m'];opens=[v.event_ns for v in bars]
        if len(set(opens))!=len(opens):raise ValueError('duplicate_native_candle')
        missing=sorted(set(range(START_NS,END_NS,60*10**9))-set(opens))
        scope=dict(start_ns=START_NS,end_ns=END_NS,session_reference='CAPTURED_CME_DAYTIME_WINDOW_CALENDAR_UNCERTIFIED')
        settled=all(v['actual_billed_usd'] is not None for v in costs)
        result[product]=dict(status='DIAGNOSTICS_ONLY_BILLING_UNRECONCILED' if not settled else 'DIAGNOSTICS_ONLY',
            evidence_kind=kind,contract=encode(contract),scope=scope,
            normalized=encode(normalized),normalized_sha256=digest(normalized),
            counts=dict(definitions=len(normalized['definition']),trades=len(normalized['trades']),candles=len(bars)),
            missing_minute_opens_ns=missing,incomplete_h1=True,point_in_time_certified=False,
            complete_exchange_continuity=False,calendar_certified=False,
            indicators=dict(trades=trade_indicators(normalized['trades'],capacity=100000,**scope),
                volatility=volatility(bars,**scope),book=dict(status='UNAVAILABLE',reason='MBP_1_NOT_ACQUIRED'),
                open_interest=dict(status='UNAVAILABLE',reason='STATISTICS_NOT_ACQUIRED')),
            costs=costs,research_admission_eligible=False,canonical_scoring_used=False,execution_eligible=False)
    return dict(products=result,manifest_sha256=manifest_hashes,input_sha256=digest(manifest_hashes),
        diagnostics_only=True,quarantined_for_billing=any(v['status'].endswith('UNRECONCILED') for v in result.values()),
        execution_eligible=False,publication_eligible=False,approval_eligible=False)
