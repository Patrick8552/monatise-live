from dataclasses import replace
from decimal import Decimal
import pytest
import databento_dbn as dn
from tests.research.test_phase7_catalog import NOW,record
from monatise.research.institutional.phase8.catalog import catalogue,weekly_definition
from monatise.research.databento.datasets import DatasetCapability,InstrumentMetadata
from monatise.research.institutional.models import Contract

def run(rows):return catalogue([(NOW-1,r) for r in rows],cutoff_ns=NOW,replay_completed=True,
    requested_roots=('OG','G3W','GC'),source_reference='ENGINEERING_SYNTHETIC')

def weekly(identity=1,kind='C',**updates):
    return record(identity,kind,asset='G3W',raw_symbol='G3WV6 '+kind+'4200',underlying='GCZ6',
        unit_of_measure='TRYOZ',strike_price_currency='USD',cfi='OCAXPS' if kind=='C' else 'OPAXPS',
        user_defined_instrument=dn.UserDefinedInstrument.YES,maturity_month=10,**updates)

def test_families_and_underlyings_partition_same_expiry_strike_without_merging():
    report,active=run([record(1),record(2,'P'),weekly(3),weekly(4,'P')])
    assert report['family_counts']=={'G3W':2,'OG':2} and len(report['partitions'])==2
    assert all(p['complete_captured_pair_lattice'] for p in report['partitions'])
    assert not report['whole_exchange_universe_certified'] and not report['execution_eligible']

def test_same_clock_ambiguity_delete_and_missing_pair_fail_closed():
    with pytest.raises(ValueError,match='ambiguous_same_clock'):run([weekly(),weekly(strike_price=4205*10**9)])
    r,_=run([weekly(),weekly(2,'P',underlying_id=9)])
    assert all(p['missing_pairs'] for p in r['partitions'])
    _,active=run([weekly(),weekly(security_update_action=dn.SecurityUpdateAction.DELETE,ts_recv=NOW-10,ts_event=NOW-11)])
    assert not active

def future():
    m=InstrumentMetadata('GLBX.MDP3',1,41271,'GCZ6','GC','XCEC','F',NOW-1000,NOW-900,NOW+90*86400*10**9,2026,12,None,None,(('currency','USD'),('min_price_increment','100000000')), 'b'*64)
    return Contract(m,'futures','USD',Decimal('.1'),Decimal(100),'USD_per_troy_oz','synthetic-native-GC')

def test_weekly_adapter_preserves_native_family_hash_and_mapping():
    r=weekly();c=weekly_definition(r,underlying=future(),capability=DatasetCapability('GLBX.MDP3',('definition',),NOW-1000,'a'*64),
        publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=NOW-1,review_reference='synthetic-weekly-convention')
    assert c.metadata.product=='G3W' and c.metadata.underlying_id==41271 and c.multiplier==100
    assert dict(c.metadata.native_terms)['user_defined_instrument']=='Y'
    with pytest.raises(ValueError,match='exact_native_weekly'):
        weekly_definition(weekly(underlying_id=9),underlying=future(),capability=DatasetCapability('GLBX.MDP3',('definition',),NOW-1000,'a'*64),publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=NOW-1,review_reference='synthetic')
