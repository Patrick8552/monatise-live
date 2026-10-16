import pytest
from monatise.research.databento.live_journal import NativeJournal,verify
from monatise.research.phase9.rotation import RotatingNativeJournal,RotationPolicy,verify_rotated_native
from monatise.research.phase9.storage import DurableSpool,record_metadata_hash
from tests.research.test_databento_live_preparation import scope,trade,NOW_NS

def test_v2_preserves_backward_wall_clock_and_exact_native_bytes(tmp_path):
    j=NativeJournal(tmp_path/'new',schema='trades',scope=scope(),evidence_kind='ENGINEERING_SYNTHETIC',arrival_order=True)
    j.append(trade(),capture_ns=NOW_NS,arrival_ns=100);j.append(trade(),capture_ns=NOW_NS-111000,arrival_ns=101)
    with pytest.raises(ValueError,match='monotonic_arrival'):j.append(trade(),capture_ns=NOW_NS+1,arrival_ns=99)
    m=j.close(quality={'quarantined':False},checkpoint={});assert m['local_capture_wall_regressions']==1
    _,rows=verify(tmp_path/'new');assert rows==((NOW_NS,bytes(trade())),(NOW_NS-111000,bytes(trade())))

def test_monotonic_rotation_survives_wall_regression_across_segment(tmp_path):
    p=RotationPolicy(records_per_segment=1,bytes_per_segment=2048,maximum_total_bytes=8192)
    j=RotatingNativeJournal(tmp_path/'new',schema='trades',scope=scope(),policy=p,arrival_order=True)
    j.append(trade(),capture_ns=NOW_NS,arrival_ns=100);j.append(trade(),capture_ns=NOW_NS-111000,arrival_ns=101)
    with pytest.raises(ValueError,match='monotonic_arrival'):j.append(trade(),capture_ns=NOW_NS,arrival_ns=100)
    j.close(quality={'quarantined':False},checkpoint={})
    assert [x[1] for x in verify_rotated_native(tmp_path/'new')]==[NOW_NS,NOW_NS-111000]

def test_spool_hash_binds_original_wall_and_monotonic_clock(tmp_path):
    s=DurableSpool(tmp_path/'raw.sqlite');row=trade()
    for n,at in enumerate((NOW_NS,NOW_NS-111000)):s.append('trades',row,capture_ns=at,arrival_ns=100+n,delivery_id=str(n),evidence_kind='ENGINEERING_SYNTHETIC')
    for d,schema,at,sha,kind,a,h,rejection,review,arrival in s.db.execute('SELECT delivery,schema,captured,hash,kind,admitted,metadata_hash,rejection,clock_review,arrival_ns FROM raw ORDER BY id'):
        assert h==record_metadata_hash(d,schema,at,sha,kind,bool(a),rejection,review,arrival)
        assert h!=record_metadata_hash(d,schema,at,sha,kind,bool(a),rejection,review,arrival+1)
    s.close()


def test_liveness_uses_monotonic_elapsed_despite_wall_clock_jump():
    from monatise.research.databento.live_state import FeedState
    mono=[100]
    state=FeedState(scope(),liveness_clock_ns=lambda:mono[0])
    for schema in state.scope.schemas:state.liveness_started[schema]=100
    # Large wall movement alone cannot hide or manufacture a delivery stall.
    assert not state.health(NOW_NS+60*10**9)['stalled_connections']
    mono[0]+=16*10**9
    assert set(state.health(NOW_NS-111000)['stalled_connections'])==set(state.scope.schemas)
