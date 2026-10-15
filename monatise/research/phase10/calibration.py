"""Versioned provider-index windows and immutable research candidate policies."""
from dataclasses import dataclass,replace
from decimal import Decimal
from pathlib import Path
import json,os
from monatise.research.institutional.models import digest,encode,hash_required,Source,MarketObservation
from monatise.research.databento.live_models import ClockReview
from monatise.research.phase9.calibration import fit,Calibration
from monatise.research.phase9.quality import PlausibilityPolicy
from .source import decode_contract,read_json
from monatise.research.databento.semantics import VERSION,EXCURSION

@dataclass(frozen=True)
class CalibrationProtocol:
    training_start_ns:int
    training_end_ns:int
    holdout_start_ns:int
    holdout_end_ns:int
    review_reference:str
    maximum_rejection_fraction:str='0.01'
    independent_start_ns:int|None=None
    independent_end_ns:int|None=None

    def __post_init__(self):
        if (any(type(v) is not int or v<=0 for v in (self.training_start_ns,self.training_end_ns,self.holdout_start_ns,self.holdout_end_ns))
            or not self.training_start_ns<self.training_end_ns<=self.holdout_start_ns<self.holdout_end_ns
            or not self.review_reference or not Decimal(0)<=Decimal(self.maximum_rejection_fraction)<=Decimal(1)):
            raise ValueError('prespecified_nonoverlapping_calibration_windows_required')
        if ((self.independent_start_ns is None)!=(self.independent_end_ns is None) or self.independent_start_ns is not None and (type(self.independent_start_ns) is not int or type(self.independent_end_ns) is not int or not self.holdout_end_ns<=self.independent_start_ns<self.independent_end_ns)):
            raise ValueError('prespecified_independent_session_window_required')


def fit_scope(rows,*,protocol,source_hashes,engineering=False):
    rows=tuple(rows)
    if not rows or not source_hashes:raise ValueError('verified_training_provenance_required')
    for sha in source_hashes:hash_required(sha)
    allowed={'ENGINEERING_SYNTHETIC'} if engineering else {'AUTHENTIC_LIVE_CAPTURE','AUTHENTIC_ARCHIVED_RECORD'}
    if any(not protocol.training_start_ns<=v.index_ns<protocol.training_end_ns or v.source.evidence_kind not in allowed for v in rows):
        raise ValueError('training_window_or_evidence_mismatch')
    return fit(rows,review_reference=protocol.review_reference,allow_tied_events=True)


def freeze_candidate(path,*,protocol,calibrations,source_hashes,coverage):
    if not calibrations or len(calibrations)>9 or not source_hashes:raise ValueError('bounded_exact_calibration_scopes_required')
    for sha in source_hashes:hash_required(sha)
    for key,c in calibrations.items():
        if (key!=c.contract.metadata.raw_symbol+':'+c.schema
            or not protocol.training_start_ns<=c.anchor_observation.index_ns<protocol.training_end_ns
            or c.policy.review_reference!=protocol.review_reference):raise ValueError('candidate_scope_or_protocol_mismatch')
    payload=dict(version='phase10-frozen-calibration-v1',protocol=encode(protocol),calibrations=encode(calibrations),
        normalization_semantics=VERSION,excursion_measurement=EXCURSION,window_clock='PROVIDER_INDEX',
        source_hashes=list(source_hashes),coverage=coverage,production_promotion=False,holdout_refitted=False)
    result=dict(payload=payload,sha256=digest(payload));path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
    with os.fdopen(fd,'w') as stream:json.dump(result,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
    return result


def load_candidate(path):
    value=read_json(path,16*1024**2);payload=value['payload']
    if (payload.get('version')!='phase10-frozen-calibration-v1' or payload.get('normalization_semantics')!=VERSION
            or payload.get('excursion_measurement')!=EXCURSION or payload.get('window_clock')!='PROVIDER_INDEX'
            or digest(payload)!=value['sha256'] or payload['production_promotion'] is not False or payload['holdout_refitted'] is not False):
        raise ValueError('frozen_candidate_integrity_failed')
    protocol=CalibrationProtocol(**payload['protocol']);calibrations={}
    for key,entry in payload['calibrations'].items():
        e=dict(entry);e['contract']=decode_contract(e['contract']);pd=dict(e['policy']);pd['scale']=Decimal(pd['scale']);e['policy']=PlausibilityPolicy(**pd)
        a=dict(e['anchor_observation']);a['contract']=decode_contract(a['contract']);source=dict(a['source']);review=source.get('clock_review');source['clock_review']=ClockReview(**review) if review else None;a['source']=Source(**source);a['payload']=tuple(a['payload']);e['anchor_observation']=MarketObservation(**a)
        calibrations[key]=Calibration(**e)
    return protocol,calibrations,value['sha256']


def validate_scope(candidate_path,key,rows,*,stage='same_day',initial_anchor=None,anchor_review_reference=None):
    protocol,calibrations,sha=load_candidate(candidate_path);rows=tuple(rows)
    start,end=(protocol.holdout_start_ns,protocol.holdout_end_ns) if stage=='same_day' else (protocol.independent_start_ns,protocol.independent_end_ns) if stage=='next_session' else (None,None)
    if start is None or any(not start<=v.index_ns<end for v in rows):raise ValueError('holdout_window_mismatch')
    fitted=calibrations[key];allowed={'ENGINEERING_SYNTHETIC'} if fitted.anchor_observation.source.evidence_kind=='ENGINEERING_SYNTHETIC' else {'AUTHENTIC_LIVE_CAPTURE','AUTHENTIC_ARCHIVED_RECORD'}
    if any(v.source.evidence_kind not in allowed for v in rows):raise ValueError('holdout_evidence_mismatch')
    if stage=='next_session':
        if (not isinstance(initial_anchor,MarketObservation) or not anchor_review_reference
            or initial_anchor.contract.identity!=fitted.contract.identity or initial_anchor.schema!=fitted.schema
            or initial_anchor.contract.tick_size!=fitted.contract.tick_size or initial_anchor.contract.multiplier!=fitted.contract.multiplier
            or not protocol.training_end_ns<=initial_anchor.index_ns<start
            or initial_anchor.source.admission_ns>=start or initial_anchor.source.evidence_kind not in allowed):
            raise ValueError('reviewed_causal_pre_session_anchor_required')
        fitted=replace(fitted,anchor_observation=initial_anchor)
    result=fitted.validate(rows,maximum_rejection_fraction=Decimal(protocol.maximum_rejection_fraction))
    result.update(operational_anchor_sha256=digest(initial_anchor) if initial_anchor else None,anchor_review_reference=anchor_review_reference,policy_sha256=fitted.policy.sha256)
    result.update(frozen_candidate_sha256=sha,holdout_refitted=False,production_promotion=False,
        native_timestamps_preserved=True,native_tie_order='provider_index_ns,original_global_ordinal',window_clock='PROVIDER_INDEX')
    return result
