"""Private read-only snapshots. Run refresh in a separate OS process from capture.

No SDK/client, acquisition, subscription, trading or legacy graph is created.
Age is measured at response delivery, never used as a hidden admission cutoff.
"""
import argparse
import copy
import fcntl
import json
from pathlib import Path
import time

from monatise.research.institutional.models import digest
from monatise.research.phase9.rotation import atomic_json


def source_snapshot(pipeline, *, capture_id, health, observed_at_ns, status):
    """Constant-size top-of-book snapshot; no history scan or analysis in capture."""
    instruments={}
    for gate in pipeline.gates.values():
        if not hasattr(gate,'quality_mode'):
            raise ValueError('native_information_mode_required')
        quotes={}
        for schema in ('mbp-1','mbp-10'):
            value=gate.latest.get(schema)
            if value is None:continue
            top=value.payload[0]
            fault=gate.faults.get(schema)
            quotes[schema]=dict(available=not fault,reason=fault,
                quote=dict(bid=top[0],ask=top[3],bid_contracts=top[1],ask_contracts=top[4],
                    receive_ns=value.receive_ns,available_ns=value.source.admission_ns,
                    source_sha256=value.source.record_sha256,executable_quote=False),
                book_state='TWO_SIDED' if top[0] is not None and top[3] is not None else 'ONE_SIDED_OR_EMPTY',
                source_flags=value.flags)
        instruments[gate.contract.metadata.raw_symbol]=dict(identity=list(gate.contract.identity),quotes=quotes)
    body=dict(version='native-source-snapshot-v1',capture_id=capture_id,observed_at_ns=observed_at_ns,
        status=status,health=health,instruments=instruments)
    return dict(body=body,sha256=digest(body))


def refresh_once(capture, cache, *, cutoff_ns=None):
    """Expensive forensic reconstruction belongs only to this worker process."""
    from monatise.research.phase10.source import load_capture
    from monatise.research.phase10.access import AnalysisRequest
    start=time.time_ns();cutoff_ns=cutoff_ns or start
    try:
        service=load_capture(capture,cutoff_ns=cutoff_ns)
        if any(not hasattr(g,'quality_mode') for g in service.pipeline.gates.values()):
            raise ValueError('native_information_mode_required')
        symbols=tuple(g.contract.metadata.raw_symbol for g in service.pipeline.gates.values())
        result=service.analyse(AnalysisRequest(symbols,cutoff_ns))
        body=dict(version='native-analysis-cache-v1',capture_id=str(Path(capture).resolve()),
            calculation_started_ns=start,calculation_completed_ns=time.time_ns(),
            analysis=result)
        atomic_json(cache,dict(body=body,sha256=digest(body)))
        atomic_json(str(cache)+'.status',dict(status='READY',observed_at_ns=time.time_ns(),error_type=None))
        return dict(status='READY',duration_ns=time.time_ns()-start)
    except Exception as exc:
        # Preserve the last successful cache; expose the new failed refresh.
        atomic_json(str(cache)+'.status',dict(status='REFRESH_FAILED',observed_at_ns=time.time_ns(),
            error_type=type(exc).__name__))
        raise


def checked(path):
    envelope=json.loads(Path(path).read_text())
    if envelope['sha256']!=digest(envelope['body']):raise ValueError('snapshot_hash_mismatch')
    return envelope['body']


def read_cached(cache, *, response_ns=None, source_path=None):
    """Fast local request. Old values remain explicitly dated historical context."""
    now=response_ns or time.time_ns();body=checked(cache)
    report=copy.deepcopy(body['analysis'])
    if report['version']!='native-futures-market-information-v1':raise ValueError('native_report_required')
    state_path=Path(str(cache)+'.status')
    worker=json.loads(state_path.read_text()) if state_path.exists() else dict(status='UNKNOWN')
    result=dict(response_ns=now,analysis_as_of_ns=report['request']['cutoff_ns'],
        analysis_age_ns=now-report['request']['cutoff_ns'],
        calculation_duration_ns=body['calculation_completed_ns']-body['calculation_started_ns'],
        cache_sha256=digest(body),worker=worker,worker_status_scope='LAST_REFRESH_RESULT_ONLY',local_freshness_cutoff_applied=False,
        source_status_at_response='NOT_CONTEMPORANEOUSLY_VERIFIED',quote_overlay_used=False)
    if source_path is not None:
        source=checked(source_path)
        if response_ns is None:
            # The collector can publish a new quote while the cache is being
            # read. Sample delivery time after that read, without changing the
            # quote's original timestamps or any explicit historical cutoff.
            now=time.time_ns()
            result.update(response_ns=now,analysis_age_ns=now-report['request']['cutoff_ns'])
        if source['capture_id']!=body['capture_id']:raise ValueError('cross_capture_snapshot_forbidden')
        result.update(source_status_at_observation=source['status'],source_observed_at_ns=source['observed_at_ns'],
            source_observation_age_ns=now-source['observed_at_ns'],source_health=source['health'])
        for symbol,latest in source['instruments'].items():
            target=report['instruments'].get(symbol)
            if target is None:continue
            original_identity=target.get('contract_identity')
            if original_identity is None or list(original_identity)!=latest['identity']:
                raise ValueError('cross_contract_quote_overlay_forbidden')
            for schema,part in latest['quotes'].items():
                q=part['quote']
                if q['available_ns']>now:raise ValueError('future_snapshot_forbidden')
                target['components'][schema]=copy.deepcopy(part)
                target['components'][schema]['as_of_source_snapshot_ns']=source['observed_at_ns']
                bounds=source['health'].get('local_clock_offset_bounds_ns')
                if bounds is not None and len(bounds)==2:
                    # These bounds were measured for the source observation,
                    # not for the later delivery. Never rewrite native ts_recv.
                    target['components'][schema]['quote']['age_at_source_observation_utc_bounds_ns']=[
                        source['observed_at_ns']-q['receive_ns']+b for b in bounds]
                result['quote_overlay_used']=True
                result['quote_update_scope']='INDEPENDENT_QUOTE_SNAPSHOT; HISTORICAL_FEATURES_NOT_RECOMPUTED'
            target['analysis_source_health']=target.get('capture_health',{})
            target['capture_health']=copy.deepcopy(source['health'])
            target['capture_health']['status']=('SEALED_HISTORICAL_CAPTURE'
                if source['status'].startswith('COMPLETED') else source['status'])
            target['source_status_at_observation']=source['status']
            if source['health'].get('quarantined') or source['status'] not in {'CAPTURING','LIVE'}:
                target['current_live_use']='UNAVAILABLE; RETAINED_AS_OF_INFORMATION_ONLY'
                if source['health'].get('quarantined'):
                    target['calculated_availability']=target['availability'];target['availability']='UNAVAILABLE'
            else:target['current_live_use']='CHECK_REPORTED_OBSERVATION_AGES; NOT_EXECUTION_CERTIFIED'
    for item in report['instruments'].values():
        for schema in ('mbp-1','mbp-10'):
            part=item.get('components',{}).get(schema,{})
            if part.get('quote'):
                part['quote']['age_at_response_ns']=now-part['quote']['receive_ns']
                part['quote']['age_at_response_clock_basis']='SIGNED_LOCAL_WALL_MINUS_PROVIDER_RECEIVE; NOT_SYNCHRONIZED_AGE_CERTIFICATION'
                part['quote']['executable_quote']=False
        # Child digests describe the original analysis, not this delivery overlay.
        item['analysis_snapshot_sha256']=item.pop('reproducibility_sha256',None)
    report['analysis_snapshot_sha256']=report.pop('reproducibility_sha256',None)
    report['delivery']=result
    report['reproducibility_sha256']=digest(report)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache',required=True);p.add_argument('--capture')
    p.add_argument('--source-snapshot');p.add_argument('--refresh',action='store_true')
    p.add_argument('--duration',type=float,default=0);p.add_argument('--interval',type=float,default=30)
    p.add_argument('--format',choices=('json','text'),default='json')
    args=p.parse_args(argv)
    if args.refresh:
        if not args.capture or not 0<=args.duration<=86400 or not 1<=args.interval<=300:
            p.error('explicit existing capture and finite duration/interval required')
        lock=Path(str(args.cache)+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
        with lock.open('a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            deadline=time.monotonic()+args.duration
            while True:
                summary=refresh_once(args.capture,args.cache)
                print(json.dumps(summary),flush=True)
                remaining=deadline-time.monotonic()
                if remaining<=0:break
                time.sleep(min(args.interval,remaining))
        return 0
    report=read_cached(args.cache,source_path=args.source_snapshot)
    if args.format=='text':
        from monatise.research.phase10.formatting import text_report
        print(text_report(report))
    else:print(json.dumps(report,sort_keys=True))
    return 0


if __name__=='__main__':raise SystemExit(main())
