"""Offline campaign training/holdout helpers; never acquire or repair data."""
from collections import Counter,defaultdict
import hashlib,time
from pathlib import Path
from monatise.research.institutional.models import digest
from .calibration import fit_scope,freeze_candidate,load_candidate,validate_scope
from .source import load_capture,readonly,checkpoint


def _collect(roots,*,start_ns,end_ns,training,maximum_records=10000000,maximum_samples_per_scope=250000):
    if not 1<=len(roots)<=8:raise ValueError('bounded_reviewed_capture_roots_required')
    samples=defaultdict(list);coverage=[];hashes=[]
    for root in roots:
        root=Path(root);local=defaultdict(list);excluded=Counter()
        def take(value,outcome):
            if not start_ns<=value.event_ns<end_ns:return
            if training and not outcome['accepted']:
                excluded[outcome['reason']]+=1;return
            key=value.contract.metadata.raw_symbol+':'+value.schema
            if len(local[key])>=maximum_samples_per_scope:raise ValueError('calibration_sample_budget_exceeded_no_downsampling')
            local[key].append(value)
        service=load_capture(root,cutoff_ns=end_ns+20*10**9,maximum_records=maximum_records,observation_sink=take)
        health=service.source_health(end_ns)
        # A quarantined attempt is preserved as negative evidence. It cannot
        # silently supply training even when its prices looked plausible.
        excluded_run=bool(health['quarantined'])
        coverage.append(dict(root=str(root),quarantined=excluded_run,source_health=health,excluded_training=dict(excluded),
            samples={k:len(v) for k,v in local.items()},used=not excluded_run))
        if excluded_run:continue
        rejected_scopes=set()
        for component in health.get('component_rejections',{}):
            schema,iid=component.rsplit(':',1)
            rejected_scopes.add(service.pipeline.gates[int(iid)].contract.metadata.raw_symbol+':'+schema)
        for key,rows in local.items():
            if key in rejected_scopes:
                coverage[-1].setdefault('excluded_component_scopes',[]).append(key);continue
            if training:
                gate=next(g for g in service.pipeline.gates.values() if key.startswith(g.contract.metadata.raw_symbol+':'))
                schema=key.split(':',1)[1]
                if schema in gate.faults:
                    boundary=gate.fault_event_ns.get(schema,0);before=len(rows);rows=[v for v in rows if v.event_ns<boundary]
                    coverage[-1].setdefault('excluded_after_dated_quality_fault',{})[key]=before-len(rows)
                    coverage[-1].setdefault('dated_faults',{})[key]=dict(reason=gate.faults[schema],event_ns=boundary)
            if len(samples[key])+len(rows)>maximum_samples_per_scope:raise ValueError('calibration_sample_budget_exceeded_no_downsampling')
            samples[key].extend(rows)
        hashes.append(health['cursor_prefix_sha256'])
        for name in ('authorization.json','analysis-inputs.json'):
            hashes.append(hashlib.sha256((root/name).read_bytes()).hexdigest())
        # Prefix file proofs remain independently verifiable as capture grows.
        db=readonly(root/'spool/state.sqlite')
        try:segments=checkpoint(db,'segments')
        finally:db.close()
        for segment in segments:
            if segment.get('sha256'):hashes.append(segment['sha256'])
    return samples,coverage,hashes


def train_candidate(roots,path,*,protocol,now_ns=None):
    now=time.time_ns() if now_ns is None else now_ns
    if now<protocol.training_end_ns+20*10**9:raise ValueError('training_window_not_sealed_yet')
    if Path(path).exists():raise FileExistsError('candidate_already_frozen_no_refit')
    samples,coverage,hashes=_collect(roots,start_ns=protocol.training_start_ns,end_ns=protocol.training_end_ns,training=True)
    fitted={};failures={}
    for key,rows in samples.items():
        try:fitted[key]=fit_scope(rows,protocol=protocol,source_hashes=hashes)
        except ValueError as exc:failures[key]=str(exc)
    if not fitted:raise ValueError('no_source_eligible_calibration_scopes')
    coverage=dict(captures=coverage,scope_failures=failures,complete_exchange_continuity_certified=False,
        declared_training_window=[protocol.training_start_ns,protocol.training_end_ns],
        observed_scope_spans={k:[rows[0].event_ns,rows[-1].event_ns] for k,rows in samples.items() if rows},
        sparse_resampling=False,quarantined_attempts_excluded=True)
    return freeze_candidate(path,protocol=protocol,calibrations=fitted,source_hashes=hashes,coverage=coverage)


def evaluate_candidate(roots,path,*,stage='same_day',now_ns=None,reviewed_anchors=None,anchor_review_reference=None):
    protocol,calibrations,sha=load_candidate(path)
    start,end=(protocol.holdout_start_ns,protocol.holdout_end_ns) if stage=='same_day' else (protocol.independent_start_ns,protocol.independent_end_ns) if stage=='next_session' else (None,None)
    now=time.time_ns() if now_ns is None else now_ns
    if start is None or now<end+20*10**9:raise ValueError('prespecified_holdout_window_not_complete')
    samples,coverage,_=_collect(roots,start_ns=start,end_ns=end,training=False)
    results={}
    for key in calibrations:
        try:results[key]=validate_scope(path,key,samples.get(key,()),stage=stage,initial_anchor=(reviewed_anchors or {}).get(key),anchor_review_reference=anchor_review_reference)
        except ValueError as exc:results[key]=dict(status='INSUFFICIENT_OR_INVALID_EVIDENCE',reason=str(exc))
    return dict(version='phase10-heldout-evaluation-v1',stage=stage,frozen_candidate_sha256=sha,
        results=results,source_coverage=coverage,holdout_refitted=False,production_promotion=False,
        complete_exchange_continuity_certified=False)
