import databento_dbn as dn
from monatise.research.databento.live_state import FeedState
from tests.research.test_databento_live_preparation import scope,populate,system,NOW_NS


def test_native_slow_reader_warning_is_not_a_fatal_record_validation_error():
    state=FeedState(scope(),native_information=True);populate(state)
    row=system(dn.SystemCode.SLOW_READER_WARNING)
    before=state.checkpoint();state.ingest('trades',row,capture_ns=NOW_NS,ordinal=100)
    assert not state.quality_reasons and state.checkpoint()==before
    assert state.provider_warnings[0]['code']==int(dn.SystemCode.SLOW_READER_WARNING)
    assert not state.health(NOW_NS)['component_record_rejections_reported']


def test_native_observation_age_is_reported_without_a_local_qualification_TTL():
    state=FeedState(scope(),native_information=True);populate(state)
    at=NOW_NS+60*10**9
    for schema in state.scope.schemas:state.ingest(schema,system(dn.SystemCode.HEARTBEAT),capture_ns=at,ordinal=100)
    h=state.health(at)
    assert not h['custom_observation_age_cutoff_applied'] and not h['stale_market_inputs']
    assert any(age>=60*10**9 for age in h['observation_ages_ns'].values())
    assert all('stream_stale_or_missing' not in c['reasons'] for v in h['component_health'].values() for c in v.values())
    assert not h['execution_eligible']


def test_provider_hung_connection_rule_is_distinct_from_record_validation():
    mono=[1];state=FeedState(scope(),native_information=True,liveness_clock_ns=lambda:mono[0]);populate(state)
    for schema in state.scope.schemas:state.liveness_started[schema]=1
    mono[0]+=15*10**9
    assert not state.health(NOW_NS)['stalled_connections']
    mono[0]+=1
    h=state.health(NOW_NS)
    assert set(h['stalled_connections'])==set(state.scope.schemas)
    assert h['transport_interrupted'] and not h['component_record_rejections_reported']


def test_native_invalid_replay_sequence_is_not_silently_ignored():
    state=FeedState(scope(),native_information=True)
    row=system(dn.SystemCode.REPLAY_COMPLETED)
    state.ingest('trades',row,capture_ns=NOW_NS,ordinal=1)
    assert state.quality_reasons
