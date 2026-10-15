"""Read-only, cursor-bounded replay of a private Phase 9 capture; no SDK client."""
from decimal import Decimal
import hashlib,json,sqlite3,time,os
from pathlib import Path
from urllib.parse import quote

from monatise.research.databento.datasets import InstrumentMetadata
from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.live_models import ClockReview
from monatise.research.databento.live_journal import verify
from monatise.research.databento.candles import ExchangeCalendar
from monatise.research.institutional.models import Contract,digest
from monatise.research.phase9.quality import PlausibilityPolicy,QualityGate
from monatise.research.phase9.pipeline import ResearchPipeline
from .access import AnalysisService


def read_json(path,maximum=4*1024**2):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>maximum:
        raise ValueError('bounded_regular_source_file_required')
    with path.open() as stream:return json.load(stream)


def readonly(path,*,sealed=False):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('existing_regular_private_database_required')
    wal=Path(str(path)+'-wal');shm=Path(str(path)+'-shm')
    # Closed WAL stores are read without creating journal sidecars. Active
    # stores must already have both sidecars; never create/repair them here.
    active=wal.exists() and wal.stat().st_size>0
    if sealed and active:raise ValueError('source_sealed_segment_has_unreviewed_wal')
    if active and not shm.is_file():raise ValueError('active_source_shared_memory_unavailable')
    uri='file:'+quote(str(path.absolute()),safe='/')+'?mode=ro'+('' if active else '&immutable=1')
    db=sqlite3.connect(uri,uri=True,timeout=2)
    db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
    return db


def checkpoint(db,name):
    value=db.execute('SELECT value,hash FROM states WHERE name=?',(name,)).fetchone()
    if value is None:raise ValueError('source_checkpoint_missing:'+name)
    data=json.loads(value[0])
    if digest(data)!=value[1]:raise ValueError('source_checkpoint_hash_mismatch')
    return data


def decode_contract(entry):
    entry=dict(entry);metadata=dict(entry.pop('metadata'));metadata['native_terms']=tuple(tuple(x) for x in metadata['native_terms'])
    entry['tick_size']=Decimal(entry['tick_size']);entry['multiplier']=Decimal(entry['multiplier'])
    return Contract(metadata=InstrumentMetadata(**metadata),**entry)


def load_capture(root,*,cutoff_ns,maximum_records=2000000,observation_sink=None,history_manifest=None):
    """Snapshot state and every segment read-only; never repair/close source DBs.

    The cursor bounds the prefix committed by the collector across its databases.
    A rotated index may include a new, not-yet-checkpointed segment; rows beyond
    the observed cursor are deliberately excluded. No missing prefix is guessed.
    """
    import databento_dbn as dn
    root=Path(root).absolute()
    if root.is_symlink() or type(maximum_records) is not int or not 1<=maximum_records<=10000000:
        raise ValueError('bounded_private_capture_required')
    auth=read_json(root/'authorization.json');inputs=read_json(root/'analysis-inputs.json')
    from monatise.research.databento.semantics import VERSION
    if inputs.get('normalization_semantics')!=VERSION or auth.get('normalization_semantics')!=VERSION:
        raise ValueError('source_normalization_version_requires_original_reader_or_separate_review')
    if inputs.get('version')!='phase10-analysis-inputs-v1' or inputs.get('authorization_sha256')!=digest(auth):
        raise ValueError('analysis_inputs_authorization_mismatch')
    steps=auth['plan']['steps']
    if len(steps)!=1:raise ValueError('analysis_access_requires_single_reviewed_attempt')
    scope=steps[0]['scope'];schemas=tuple(scope['schemas']);refs=auth['calibration_references']
    if not set(schemas)<={'definition','trades','ohlcv-1s','ohlcv-1m'} or 'trades' not in schemas:
        raise ValueError('access_v1_requires_reviewed_trade_and_native_candle_capture')
    contracts={};gates={};calendars={};anchors={}
    for schema in schemas:
        if schema=='definition':continue
        wanted={v['anchor_record_sha256'] for k,v in refs.items() if k.endswith(':'+schema)}
        anchor_folder=Path(inputs['anchor_root'])/schema
        if (anchor_folder/'rotation.json').exists():
            from monatise.research.phase9.rotation import verify_rotated_native
            frames=((at,raw) for _,at,raw in verify_rotated_native(anchor_folder))
        else:_,frames=verify(anchor_folder)
        for at,raw in frames:
            sha=hashlib.sha256(raw).hexdigest()
            if sha not in wanted:continue
            rows=dn.DBNDecoder(has_metadata=False,input_version=3).write_and_decode(raw)
            if len(rows)!=1 or bytes(rows[0])!=raw:raise ValueError('anchor_native_roundtrip_failed')
            row=rows[0];anchors[(row.instrument_id,schema,sha)]=(row,at)
    for encoded in scope['contracts']:
        c=decode_contract(encoded);iid=c.metadata.instrument_id;contracts[iid]=c;policies={};points={}
        for schema in schemas:
            if schema=='definition':continue
            key=c.metadata.raw_symbol+':'+schema
            pd=dict(inputs['policies'][key]);pd['scale']=Decimal(pd['scale']);policy=PlausibilityPolicy(**pd)
            if policy.sha256!=refs[key]['policy_sha256']:raise ValueError('source_policy_hash_mismatch')
            sha=refs[key]['anchor_record_sha256'];row,at=anchors[(iid,schema,sha)]
            if row.ts_event!=refs[key]['anchor_event_ns']:raise ValueError('source_anchor_event_mismatch')
            price=Decimal(row.price if schema=='trades' else row.close)/10**9
            policies[schema]=policy;points[schema]=dict(anchor=price,anchor_ns=row.ts_event,anchor_sha256=sha)
        gates[iid]=QualityGate(c,policies['trades'],**points['trades'],schema_policies=policies,schema_anchors=points,rolling=True,capacity=50000)
        ref=scope['session_review_reference']
        opened=inputs['session_open_ns'];closed=scope['session_end_ns']
        calendars[iid]=ExchangeCalendar('GLBX.MDP3',c.metadata.exchange,ref,digest(ref),'explicit-read-only-capture-session',opened,closed,((opened,closed),))
    pipeline=ResearchPipeline(gates,calendars,enabled_schemas=schemas,rolling=True,capacity=50000)
    from monatise.research.native_futures.quality_review import NativeQualityReview
    native_review=NativeQualityReview()
    # Read source health before the cursor snapshot. A later progress write can
    # contain failures outside the prefix being replayed by this request.
    progress_snapshot=read_json(root/'progress.json') if (root/'progress.json').exists() else None
    final_snapshot=read_json(root/'capture/attempt-00/report.json',32*1024**2) if (root/'capture/attempt-00/report.json').exists() else None
    state=readonly(root/'spool/state.sqlite')
    try:
        segments=checkpoint(state,'segments');cursor=checkpoint(state,'feed_cursor');limit=cursor['spool_records']
        if type(limit) is not int or not 0<=limit<=maximum_records:raise ValueError('analysis_replay_record_budget_exceeded')
        count=0;accepted=0;rejected=0;last_global=0;kinds=set();last_captures={};delivery_prefix=digest(auth['plan'])+':0:'
        acks=set();replays=set();markers={};native_prefix=digest([]);clock_cache={};prefix_last_ns=0;prefix_clock=None
        for segment in segments:
            base=segment['base'];path=root/'spool'/segment['path']
            if path.parent!=root/'spool' or path.is_symlink() or base!=count:raise ValueError('source_segment_position_mismatch')
            if base>=limit:break
            if segment.get('sha256'):
                with path.open('rb') as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=segment['sha256']:raise ValueError('source_sealed_segment_hash_mismatch')
            db=readonly(path,sealed=bool(segment.get('sha256')))
            try:
                for row in db.execute('SELECT id,delivery,schema,captured,native,hash,kind,admitted,metadata_hash,rejection,clock_review FROM raw WHERE id<=? ORDER BY id',(limit-base,)):
                    ordinal,delivery,schema,at,raw,sha,kind,admitted,metadata,rejection,review=row
                    timestamp_ns(at)
                    if at<last_captures.get(schema,0):raise ValueError('source_capture_clock_regression')
                    last_captures[schema]=at
                    if not delivery.startswith(delivery_prefix+schema+':') or not delivery.rsplit(':',1)[1].isdecimal():raise ValueError('source_delivery_plan_mismatch')
                    if ordinal+base!=last_global+1:raise ValueError('source_native_position_gap')
                    last_global=ordinal+base;count+=1
                    if digest([delivery,schema,at,sha,kind,bool(admitted),rejection,review])!=metadata or hashlib.sha256(raw).hexdigest()!=sha:
                        raise ValueError('source_native_or_metadata_hash_mismatch')
                    if not 1<=len(raw)<=65536 or admitted not in (0,1):raise ValueError('bounded_native_source_row_required')
                    if schema not in schemas or kind not in {'AUTHENTIC_LIVE_CAPTURE','ENGINEERING_SYNTHETIC'}:raise ValueError('source_schema_or_evidence_mismatch')
                    kinds.add(kind)
                    try:records=dn.DBNDecoder(has_metadata=False,input_version=3).write_and_decode(raw)
                    except Exception:raise ValueError('source_native_decode_failure') from None
                    if len(records)!=1 or bytes(records[0])!=raw:raise ValueError('source_native_roundtrip_failed')
                    record=records[0]
                    if at>cutoff_ns:continue
                    if review not in clock_cache:
                        clock=json.loads(review);clock_cache[review]=ClockReview(**clock) if clock else None
                    record_clock=clock_cache[review]
                    _,clock_upper=record_clock.bounds(at) if record_clock else (0,0)
                    if at>=prefix_last_ns:prefix_last_ns=at;prefix_clock=record_clock
                    native_prefix=digest([native_prefix,schema,at,sha,ordinal+base])
                    if isinstance(record,dn.SystemMsg):
                        if record.code==dn.SystemCode.SUBSCRIPTION_ACK:acks.add(schema)
                        elif record.code==dn.SystemCode.REPLAY_COMPLETED and schema in acks:replays.add(schema)
                        elif record.code==dn.SystemCode.END_OF_INTERVAL and schema.startswith('ohlcv-'):
                            from monatise.research.databento.candles import WIDTHS
                            width=WIDTHS[schema[6:]]
                            prior=markers.get(schema,[])
                            if (schema in acks and not record.ts_event%width and (prior[-1]['end_ns'] if prior else 0)<=record.ts_event<=at+clock_upper):
                                markers[schema]=[*prior[-15:],dict(end_ns=record.ts_event,available_ns=at,sha256=sha)]
                    if rejection:
                        if record.instrument_id in gates:
                            gates[record.instrument_id].transport_gap(schema,rejection,event_ns=record.ts_event)
                            clock=record_clock
                            _,upper=clock.bounds(at) if clock else (0,0)
                            contextual=(scope.get('start_ns',contracts[record.instrument_id].metadata.event_ns)<=record.ts_event<scope['session_end_ns']
                                and getattr(record,'ts_recv',record.ts_event)<=at+upper
                                and at+max(0,upper)<scope['session_end_ns']+scope.get('session_drain_seconds',30)*10**9)
                            native_review.rejection(schema,record,contracts[record.instrument_id],original_reason=rejection,context_valid=contextual)
                    if not admitted or isinstance(record,(dn.SystemMsg,dn.SymbolMappingMsg,dn.ErrorMsg)):continue
                    evidence=record_clock
                    outcome=pipeline.ingest(record,schema=schema,archive_sha256=sha,ordinal=ordinal+base,
                        capture_ns=at,admission_ns=at,evidence_kind=kind,clock_review=evidence)
                    native_review.observe(schema,record,contracts[record.instrument_id],admitted=bool(admitted),gate=gates[record.instrument_id])
                    accepted+=int(outcome['accepted']);rejected+=int(not outcome['accepted'] and not outcome['duplicate'])
                    if observation_sink is not None and not outcome['duplicate']:
                        from monatise.research.institutional.normalize import observation
                        try:
                            canonical=observation(record,schema=schema,contract=gates[record.instrument_id].contract,archive_sha256=sha,ordinal=ordinal+base,retrieval_ns=at,admission_ns=at,evidence_kind=kind,enabled_schemas=schemas,clock_review=evidence)
                        except (ValueError,TypeError,AttributeError,ArithmeticError):canonical=None
                        if canonical is not None:observation_sink(canonical,outcome)
            finally:db.close()
        if count!=limit or len(kinds)>1:raise ValueError('incomplete_or_mixed_native_prefix')
    finally:state.close()
    final=root/'capture/attempt-00/report.json'
    if final_snapshot is not None:
        report=final_snapshot
        if report['scope_sha256']!=digest(scope):raise ValueError('source_final_scope_mismatch')
        health=dict(status='SEALED_HISTORICAL_CAPTURE',quarantined=report['quality']['quarantined'],
            reasons=report['quality']['reasons'],component_rejections=report['quality'].get('component_rejections',{}),stale_checkpoint=False,live_verified=False)
    else:
        progress=progress_snapshot;health=dict(status=progress['status'],
            quarantined=progress['health']['quarantined'],reasons=progress['health']['reasons'],component_rejections=progress['health'].get('component_rejections',{}),
            observed_at_ns=progress['observed_at_ns'],stale_checkpoint=not 0<=time.time_ns()-progress['observed_at_ns']<=180*10**9,
            live_verified=False,interval_watermarks=progress['health'].get('interval_watermarks',{}))
    for component,reasons in health['component_rejections'].items():
        schema,instrument=component.rsplit(':',1);iid=int(instrument)
        if iid not in gates or schema not in schemas:raise ValueError('source_component_health_scope_mismatch')
        gates[iid].transport_gap(schema,'captured_component_rejection_requires_review')
    quality=report['quality'] if final_snapshot is not None else progress['health']
    health['stalled_connections']=list(quality.get('stalled_connections',()))
    health['reasons']=sorted(set(health['reasons'])|{'connection_stalled_'+s for s in health['stalled_connections']})
    # Progress can be newer than the cursor snapshot. Never explain away an
    # unobserved rejection using older typed evidence for the same component.
    published=progress_snapshot
    accounted=bool(published and published.get('spool_records',limit+1)<=limit)
    health['native_rejection_reviews']=native_review.typed_rejections(complete_for_reported_prefix=accounted)
    health['reader_price_fault_reviews']={g.contract.metadata.raw_symbol:native_review.price_faults(g) for g in gates.values()}
    health.update(native_records_verified=count,market_records_accepted=accepted,market_records_rejected=rejected,
        cursor_prefix_sha256=digest(cursor),source_evidence_kind=next(iter(kinds),None),complete_exchange_continuity_certified=False,
        retained_market_records_per_instrument=50000,network_requests=0,source_mutations=0,
        verification_scope='spool byte/metadata hashes and committed cursor prefix; independent framed-journal reconciliation remains separate')
    # Reconstruct provider-empty coverage only from native controls inside the
    # verified committed prefix. A status JSON or heartbeat cannot supply it.
    from monatise.research.databento.bar_coverage import NativeBarCoverage
    from monatise.research.databento.candles import WIDTHS
    if not health['reasons'] and not health['stalled_connections']:
        for iid,gate in gates.items():
            for schema,controls in markers.items():
                marker=next((r for r in reversed(controls) if r['end_ns']<=prefix_last_ns),None)
                if marker is None:continue
                if schema not in replays or schema in gate.faults or f'{schema}:{iid}' in health['component_rejections']:continue
                step=WIDTHS[schema[6:]];ref=refs[gate.contract.metadata.raw_symbol+':'+schema]
                begin=max(scope.get('start_ns',0),ref['anchor_event_ns']+step)
                begin=(begin+step-1)//step*step
                if begin>=marker['end_ns']:continue
                proof=NativeBarCoverage(gate.contract.identity,schema,begin,marker['end_ns'],prefix_last_ns,
                    marker['sha256'],native_prefix,'verified-read-only-native-control-prefix',prefix_clock)
                gate.coverage_reviews[proof.sha256]=proof
    health['normalization_semantics']=VERSION
    if history_manifest is not None:
        from .history import load_history,WarmedPipeline
        try:
            history=load_history(history_manifest,pipeline=pipeline,authorization_sha256=digest(auth),
                policy_hashes={k:v['policy_sha256'] for k,v in refs.items()},cutoff_ns=cutoff_ns)
            pipeline=WarmedPipeline(pipeline,history)
            faults={g.contract.metadata.raw_symbol:dict(g.faults) for g in history['gates'].values() if g.faults}
            health['history_warmup']=dict(status='SOURCE_VERIFIED_WITH_PRICE_GUARD_REJECTIONS' if faults else 'SOURCE_VERIFIED_SEPARATE_HISTORY',
                manifest_sha256=history['manifest_sha256'],retained_price_guard_faults=faults,live_soak_gap_repaired=False)
        except (OSError,ValueError,TypeError,KeyError,ArithmeticError,dn.DBNError) as exc:
            # Optional bad history cannot contaminate or erase valid live data.
            health['history_warmup']=dict(status='UNAVAILABLE',reason=str(exc) if isinstance(exc,ValueError) else 'history_source_invalid',error_type=type(exc).__name__,live_soak_gap_repaired=False)
    from .market_info import FuturesMarketInfo
    return FuturesMarketInfo(pipeline,source_health=lambda now:dict(health))


def prepare_inputs(root,*,policies,anchor_root,session_open_ns):
    """Collector/operator setup once; analysis requests then need only a root.

    The manifest cannot change policy hashes already bound by the capture's
    authorization. No price/anchor is accepted from manually entered JSON.
    """
    from monatise.research.institutional.models import encode
    root=Path(root).absolute();auth=read_json(root/'authorization.json');refs=auth['calibration_references']
    from monatise.research.databento.semantics import VERSION
    if auth.get('normalization_semantics')!=VERSION:raise ValueError('new_versioned_collector_authorization_required')
    if set(policies)!=set(refs):raise ValueError('exact_reviewed_analysis_policies_required')
    if any(digest(policies[key])!=ref['policy_sha256'] for key,ref in refs.items()):raise ValueError('source_policy_hash_mismatch')
    if type(session_open_ns) is not int or session_open_ns<=0:raise ValueError('reviewed_session_open_required')
    anchor_root=Path(anchor_root).absolute()
    if anchor_root.is_symlink() or not anchor_root.is_dir():raise ValueError('regular_source_anchor_directory_required')
    value=dict(version='phase10-analysis-inputs-v1',authorization_sha256=digest(auth),anchor_root=str(anchor_root),
        session_open_ns=session_open_ns,policies=encode(policies),normalization_semantics=VERSION)
    path=root/'analysis-inputs.json';fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
    return path
