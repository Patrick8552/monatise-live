from pathlib import Path
from types import SimpleNamespace
import hashlib,json,sqlite3
import pytest
from monatise.research.institutional.models import digest,encode
from monatise.research.databento.live_journal import NativeJournal
from monatise.research.phase9.rotation import RotatingSpool,RotationPolicy
from monatise.research.phase10.source import load_capture
from monatise.research.phase10.access import AnalysisRequest
from tests.research.phase9.test_pipeline import contract,gate,trade,NOW_NS,NS

@pytest.fixture
def capture(tmp_path):
    c=contract();g=gate(c);root=tmp_path/'capture';root.mkdir();anchor_root=tmp_path/'anchors'
    s=SimpleNamespace(schemas=('trades',),sha256=digest('anchor'),maximum_records=100,maximum_bytes=65536)
    anchor=trade(c,t=NOW_NS-5*NS)
    j=NativeJournal(anchor_root/'trades',schema='trades',scope=s,evidence_kind='ENGINEERING_SYNTHETIC')
    j.append(anchor,capture_ns=NOW_NS);j.close(quality={'quarantined':False},checkpoint={})
    scope=dict(contracts=[encode(c)],schemas=['trades'],session_end_ns=(NOW_NS//(60*NS))*60*NS+86400*NS,session_review_reference='ENGINEERING CALENDAR')
    key=c.metadata.raw_symbol+':trades';auth=dict(plan=dict(steps=[dict(scope=scope)]),calibration_references={key:dict(policy_sha256=g.policy.sha256,anchor_event_ns=anchor.ts_event,anchor_record_sha256=hashlib.sha256(bytes(anchor)).hexdigest())})
    (root/'authorization.json').write_text(json.dumps(auth))
    inputs=dict(version='phase10-analysis-inputs-v1',authorization_sha256=digest(auth),anchor_root=str(anchor_root),session_open_ns=(NOW_NS//(60*NS))*60*NS-86400*NS,policies={key:encode(g.policy)})
    (root/'analysis-inputs.json').write_text(json.dumps(inputs))
    spool=RotatingSpool(root/'spool',policy=RotationPolicy(records_per_segment=2,bytes_per_segment=4096,maximum_segments=10,maximum_total_bytes=65536))
    for n in range(4):spool.append('trades',trade(c,t=NOW_NS-(4-n)*NS),capture_ns=NOW_NS,delivery_id=digest(auth['plan'])+':0:trades:'+str(n),evidence_kind='ENGINEERING_SYNTHETIC')
    spool.checkpoint('feed_cursor',dict(spool_records=spool.count,cursors={}))
    spool.close()
    final=root/'capture/attempt-00';final.mkdir(parents=True);(final/'report.json').write_text(json.dumps(dict(scope_sha256=digest(scope),quality=dict(quarantined=False,reasons=[]))))
    return root,c


def hashes(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def test_verified_replay_is_read_only_and_preserves_legitimate_multiplicity(capture):
    root,c=capture;before=hashes(root)
    result=load_capture(root,cutoff_ns=NOW_NS).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))
    value=result['instruments'][c.metadata.raw_symbol]
    assert value['capture_health']['native_records_verified']==4
    assert value['capture_health']['market_records_accepted']==4
    assert value['components']['trade_features']['available']
    assert hashes(root)==before
    assert value['capture_health']['source_evidence_kind']=='ENGINEERING_SYNTHETIC'
    assert not value['execution_eligible']


def test_corrupt_sealed_segment_is_rejected_before_engines(capture):
    root,c=capture;path=root/'spool/raw-00000.sqlite';path.chmod(0o600)
    db=sqlite3.connect(path)
    try:
        with db:db.execute("UPDATE raw SET native=x'00' WHERE id=1")
    finally:db.close()
    with pytest.raises(ValueError,match='sealed_segment_hash'):load_capture(root,cutoff_ns=NOW_NS)


def test_changed_policy_cannot_silently_relax_quality(capture):
    root,c=capture;p=root/'analysis-inputs.json';v=json.loads(p.read_text());v['policies'][c.metadata.raw_symbol+':trades']['floor_ticks']*=100;p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='policy_hash'):load_capture(root,cutoff_ns=NOW_NS)


def test_quarantined_capture_retains_calculations_but_is_unavailable(capture):
    root,c=capture;p=root/'capture/attempt-00/report.json';v=json.loads(p.read_text());v['quality']=dict(quarantined=True,reasons=['provider_disconnected_trades']);p.write_text(json.dumps(v))
    r=load_capture(root,cutoff_ns=NOW_NS).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]
    assert r['availability']=='UNAVAILABLE' and r['components']['trade_features']['available']
    assert r['capture_health']['quarantined']


def test_legacy_empty_reason_stall_is_reported_without_rewriting_source(capture):
    root,c=capture;path=root/'capture/attempt-00/report.json';v=json.loads(path.read_text())
    v['quality'].update(quarantined=True,reasons=[],stalled_connections=['trades']);path.write_text(json.dumps(v));before=hashes(root)
    service=load_capture(root,cutoff_ns=NOW_NS)
    value=service.analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]
    assert value['availability']=='UNAVAILABLE'
    assert 'connection_stalled_trades' in value['capture_health']['reasons']
    assert hashes(root)==before


def test_read_only_phrase_cli_resolves_current_exact_contract(capture,capsys):
    from monatise.research.phase10.cli import main
    root,c=capture;pointer=root.parent/'pointer.txt';pointer.write_text(str(root))
    assert main(['--capture-pointer',str(pointer),'--request','Analyse GC using Databento'])==0
    result=json.loads(capsys.readouterr().out)
    assert list(result['instruments'])==[c.metadata.raw_symbol]
    assert result['decision']=='NO_TRADE' and not result['execution_eligible']


def test_optional_history_decoder_error_does_not_erase_valid_live_data(capture,monkeypatch):
    import databento_dbn as dn
    from monatise.research.phase10 import history
    root,c=capture
    def invalid_history(*args,**kwargs):raise dn.DBNError('ENGINEERING_INVALID_DBN')
    monkeypatch.setattr(history,'load_history',invalid_history)
    result=load_capture(root,cutoff_ns=NOW_NS,history_manifest=root/'bad-history.json').analyse(
        AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))['instruments'][c.metadata.raw_symbol]
    assert result['components']['trade_features']['available']
    assert result['capture_health']['history_warmup']['status']=='UNAVAILABLE'
    assert result['capture_health']['history_warmup']['error_type']=='DBNError'


def test_record_budget_is_enforced_without_returning_partial_replay_as_complete(capture):
    root,c=capture
    with pytest.raises(ValueError,match='record_budget'):load_capture(root,cutoff_ns=NOW_NS,maximum_records=3)


def test_future_records_do_not_enter_historical_analysis(capture):
    root,c=capture;service=load_capture(root,cutoff_ns=NOW_NS-NS)
    assert not service.analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS-NS))['instruments'][c.metadata.raw_symbol]['components']['trade_features']['available']


def test_setup_can_only_bind_the_existing_reviewed_policies_once(capture):
    from monatise.research.phase10.source import prepare_inputs
    root,c=capture;p=root/'analysis-inputs.json';inputs=json.loads(p.read_text());p.unlink()
    policies=inputs['policies'];policy=dict(policies[c.metadata.raw_symbol+':trades']);policy['floor_ticks']*=100
    with pytest.raises(ValueError,match='policy_hash'):prepare_inputs(root,policies={c.metadata.raw_symbol+':trades':policy},anchor_root=inputs['anchor_root'],session_open_ns=inputs['session_open_ns'])
    prepare_inputs(root,policies=policies,anchor_root=inputs['anchor_root'],session_open_ns=inputs['session_open_ns'])
    with pytest.raises(FileExistsError):prepare_inputs(root,policies=policies,anchor_root=inputs['anchor_root'],session_open_ns=inputs['session_open_ns'])
    assert load_capture(root,cutoff_ns=NOW_NS)


def test_uncheckpointed_final_component_rejection_still_blocks_affected_inputs(capture):
    root,c=capture;p=root/'capture/attempt-00/report.json';value=json.loads(p.read_text());value['quality']['component_rejections']={'trades:'+str(c.metadata.instrument_id):['native_record_or_recovery_validation_failed']};p.write_text(json.dumps(value))
    result=load_capture(root,cutoff_ns=NOW_NS).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS,mandatory=('trade_features',)))['instruments'][c.metadata.raw_symbol]
    assert not result['components']['trade_features']['available'] and result['availability']=='UNAVAILABLE'
    assert result['capture_health']['component_rejections']


def test_campaign_excludes_reported_bad_schema_without_admitting_its_clean_prefix_as_full(capture):
    from monatise.research.phase10.campaign import _collect
    root,c=capture;p=root/'capture/attempt-00/report.json';value=json.loads(p.read_text());value['quality']['component_rejections']={'trades:'+str(c.metadata.instrument_id):['rejection']};p.write_text(json.dumps(value))
    samples,coverage,hashes=_collect([root],start_ns=NOW_NS-10*NS,end_ns=NOW_NS,training=True)
    assert not samples and coverage[0]['excluded_component_scopes']==[c.metadata.raw_symbol+':trades']
