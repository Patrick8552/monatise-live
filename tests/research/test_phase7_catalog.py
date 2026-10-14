import pytest
import databento_dbn as dbn
from monatise.research.institutional.phase7.catalog import reduce_definitions

NOW=1791933000000000000
def record(identity=1,kind='C',action=dbn.SecurityUpdateAction.ADD,received=NOW-100,**updates):
    fields=dict(publisher_id=1,instrument_id=identity,ts_event=received-1,ts_recv=received,
        min_price_increment=100000000,display_factor=10000000,raw_symbol='OGX6 '+kind+'4200',
        asset='OG',security_type='OOF',instrument_class=dbn.InstrumentClass.CALL if kind=='C' else dbn.InstrumentClass.PUT,security_update_action=action,
        expiration=NOW+86400*10**9,unit_of_measure_qty=100*10**9,underlying_id=41271,
        strike_price=4200*10**9,currency='USD',exchange='XCEC',maturity_year=2026,maturity_month=11)
    fields.update(updates)
    return dbn.InstrumentDefMsg(**fields)

def run(rows,completed=True):
    return reduce_definitions([(NOW-1,row) for row in rows],cutoff_ns=NOW,
                              replay_completed=completed,source_reference='ENGINEERING_SYNTHETIC')

def test_delete_and_reordered_old_update_cannot_restore_option():
    added=record();deleted=record(action=dbn.SecurityUpdateAction.DELETE,received=NOW-10)
    result,active=run([deleted,added])
    assert result['deleted_latest_definitions']==1
    assert result['selected_GCZ6_option_count']==0 and 1 not in active

def test_complete_transport_is_separate_from_market_coverage():
    result,_=run([record(),record(2,'P')])
    assert result['selected_GCZ6_option_count']==2 and not result['missing_call_put_pairs']
    assert result['replay_completed']
    assert not result['whole_exchange_chain_certified'] and not result['quote_scope_certified']
    assert not result['execution_eligible'] and not result['gil_enabled']

def test_missing_put_other_underlying_and_expired_are_not_synthesized():
    result,_=run([record(),record(2,'P',underlying_id=2),record(3,'P',expiration=NOW-1)])
    assert result['selected_GCZ6_option_count']==1
    assert result['missing_call_put_pairs'] and result['active_OG_outright_count']==2

def test_missing_replay_completion_keeps_catalogue_incomplete():
    result,_=run([record()],completed=False)
    assert result['status']=='INCOMPLETE_PARENT_REPLAY'

def test_ambiguous_same_clock_native_definition_is_rejected():
    with pytest.raises(ValueError,match='ambiguous_same_clock'):
        run([record(),record(strike_price=4205*10**9)])

def test_unknown_lifecycle_action_is_rejected():
    with pytest.raises(ValueError,match='invalid_native'):
        run([record(publisher_id=2)])


def test_distinct_spread_leg_definitions_are_preserved_but_never_admitted():
    result,active=run([record(leg_count=2,leg_index=0),record(leg_count=2,leg_index=1)])
    assert result['excluded_non_outright_records']==2
    assert result['selected_GCZ6_option_count']==0 and not active
