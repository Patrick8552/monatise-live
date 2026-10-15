from dataclasses import replace
from decimal import Decimal
import hashlib,json
import pytest
from monatise.research.phase10.calibration import CalibrationProtocol,fit_scope,freeze_candidate,validate_scope
from tests.research.phase9.test_continuation import canonical
from tests.research.phase9.test_pipeline import contract,NOW_NS,NS
from monatise.research.institutional.models import digest


def samples():
    c=contract();rows=[canonical(c,Decimal('2500')+Decimal('.1')*(i%3),i) for i in range(40)]
    # Legitimate distinct executions can share both event and receive times.
    rows[5]=replace(rows[5],event_ns=rows[4].event_ns,receive_ns=rows[4].receive_ns)
    protocol=CalibrationProtocol(rows[0].event_ns,rows[20].event_ns,rows[20].event_ns,rows[-1].event_ns+NS,'ENGINEERING FIXED WINDOWS')
    return rows,protocol


def test_candidate_preserves_tied_execution_multiplicity_and_freezes_before_holdout(tmp_path):
    rows,protocol=samples();f=fit_scope(rows[:20],protocol=protocol,source_hashes=[digest('native')],engineering=True)
    assert f.training_count==20 and f.allow_tied_events
    key=f.contract.metadata.raw_symbol+':trades';path=tmp_path/'candidate.json'
    freeze_candidate(path,protocol=protocol,calibrations={key:f},source_hashes=[digest('native')],coverage={'gaps':[]})
    before=path.read_bytes();result=validate_scope(path,key,rows[20:])
    assert result['status']=='HOLDOUT_PASSED' and result['holdout_count']==20
    assert path.read_bytes()==before and not result['holdout_refitted']
    with pytest.raises(FileExistsError):freeze_candidate(path,protocol=protocol,calibrations={key:f},source_hashes=[digest('native')],coverage={})


def test_training_cannot_include_holdout_or_synthetic_market_evidence():
    rows,protocol=samples()
    with pytest.raises(ValueError,match='training_window'):fit_scope(rows,protocol=protocol,source_hashes=[digest('native')],engineering=True)
    with pytest.raises(ValueError,match='evidence'):fit_scope(rows[:20],protocol=protocol,source_hashes=[digest('native')])


def test_repeated_position_and_reversed_tie_are_rejected():
    rows,protocol=samples()
    for modified in ([*rows[:5],rows[4],*rows[6:20]],[*rows[:4],rows[5],rows[4],*rows[6:20]]):
        with pytest.raises(ValueError,match='chronological'):fit_scope(modified,protocol=protocol,source_hashes=[digest('native')],engineering=True)


def test_candidate_tampering_and_holdout_spike_are_not_hidden(tmp_path):
    rows,protocol=samples();f=fit_scope(rows[:20],protocol=protocol,source_hashes=[digest('native')],engineering=True);key=f.contract.metadata.raw_symbol+':trades';path=tmp_path/'candidate.json'
    freeze_candidate(path,protocol=protocol,calibrations={key:f},source_hashes=[digest('native')],coverage={})
    spike=replace(rows[-1],payload=('250000',2,'BUY'))
    assert validate_scope(path,key,[*rows[20:-1],spike])['status']=='HOLDOUT_FAILED'
    path.chmod(0o600);value=json.loads(path.read_text());value['payload']['calibrations'][key]['policy']['floor_ticks']*=100;path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='integrity'):validate_scope(path,key,rows[20:])


def test_campaign_does_not_read_sources_before_windows_close(tmp_path):
    from monatise.research.phase10.campaign import train_candidate,evaluate_candidate
    rows,protocol=samples()
    with pytest.raises(ValueError,match='not_sealed'):train_candidate([tmp_path/'missing'],tmp_path/'candidate',protocol=protocol,now_ns=protocol.training_end_ns)
    f=fit_scope(rows[:20],protocol=protocol,source_hashes=[digest('native')],engineering=True);key=f.contract.metadata.raw_symbol+':trades';path=tmp_path/'candidate'
    freeze_candidate(path,protocol=protocol,calibrations={key:f},source_hashes=[digest('native')],coverage={})
    with pytest.raises(ValueError,match='not_complete'):evaluate_candidate([tmp_path/'missing'],path,now_ns=protocol.holdout_end_ns)
    with pytest.raises(FileExistsError):train_candidate([tmp_path/'missing'],path,protocol=protocol,now_ns=protocol.training_end_ns+30*NS)


def test_independent_session_requires_causal_reviewed_anchor_without_refitting(tmp_path):
    rows,protocol=samples();start=rows[-1].event_ns+100*NS
    protocol=replace(protocol,independent_start_ns=start,independent_end_ns=start+100*NS)
    f=fit_scope(rows[:20],protocol=protocol,source_hashes=[digest('native')],engineering=True);key=f.contract.metadata.raw_symbol+':trades';path=tmp_path/'candidate'
    freeze_candidate(path,protocol=protocol,calibrations={key:f},source_hashes=[digest('native')],coverage={})
    later=[replace(row,event_ns=start+i*NS,receive_ns=start+i*NS,source=replace(row.source,retrieval_ns=start+i*NS,admission_ns=start+i*NS)) for i,row in enumerate(rows[20:])]
    with pytest.raises(ValueError,match='pre_session_anchor'):validate_scope(path,key,later,stage='next_session')
    anchor=rows[-1];original=path.read_bytes();result=validate_scope(path,key,later,stage='next_session',initial_anchor=anchor,anchor_review_reference='ENGINEERING CLOSING ANCHOR')
    assert result['policy_sha256']==f.policy.sha256 and path.read_bytes()==original and not result['holdout_refitted']
