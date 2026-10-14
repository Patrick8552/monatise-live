from types import SimpleNamespace as NS
import pytest
from monatise.research.institutional.phase8.gamma import scenarios
from monatise.research.institutional.phase8.surface import representative_ids
from monatise.research.institutional.models import digest

def row(i=1,oi=10,status='VALIDATED',underlying=41271):
    inputs={'native_instrument_id':i,'cutoff_ns':1}
    model={'status':'VALIDATED_MODEL_SENSITIVITIES','gamma':.002,'inputs':inputs,'input_sha256':digest(inputs),'evidence_kind':'ENGINEERING_SYNTHETIC'}
    return dict(instrument_id=i,underlying_id=underlying,expiration_ns=100,strike_fixed=4200*10**9,
        OI={'value':oi},Greek={'status':status,'gamma':.002 if status=='VALIDATED' else None,'model_result':model},normalized_contract={'multiplier':'100'})

def test_raw_gamma_units_and_partial_exposure_cannot_be_full_chain_gex():
    ledger={'contracts':[row(),row(2,oi=None)],'scope_complete':False,'provider_market_cutoff_ns':1,'evidence_kind':'ENGINEERING_SYNTHETIC'}
    out=scenarios(ledger,assumptions=[{'name':'all_long_hypothetical','signs':{1:1,2:1},'assumption_reference':'synthetic-signs'}])
    result=out['scenarios'][0]
    assert result['raw_subset_gamma']==2 and result['qualified_chain_scenario_gamma'] is None
    assert result['missing_contract_ids']==[2] and result['flip_candidates'] is None and result['observed_dealer_GEX'] is None

def test_unknown_inventory_invalid_signs_and_separate_underlyings():
    ledger={'contracts':[row(),row(2,underlying=9)],'scope_complete':True,'provider_market_cutoff_ns':1,'evidence_kind':'ENGINEERING_SYNTHETIC'}
    out=scenarios(ledger,assumptions=[{'name':'unknown','signs':None,'assumption_reference':'no-inventory'}])
    assert out['scenarios'][0]['status']=='POSITIONING_UNKNOWN'
    with pytest.raises(ValueError,match='hypothetical_sign'):scenarios(ledger,assumptions=[{'name':'bad','signs':{1:True,2:1},'assumption_reference':'synthetic'}])
    out=scenarios(ledger,assumptions=[{'name':'signed','signs':{1:1,2:-1},'assumption_reference':'synthetic'}])
    assert len(out['scenarios'])==2 and {r['underlying_id'] for r in out['scenarios']}=={9,41271}
    assert all(r['qualified_chain_scenario_gamma'] is None for r in out['scenarios'])

def test_edited_model_result_or_hash_cannot_be_weighted_as_validated_gamma():
    r=row();r['Greek']['model_result']['gamma']=.004
    ledger={'contracts':[r],'scope_complete':False,'provider_market_cutoff_ns':1,'evidence_kind':'ENGINEERING_SYNTHETIC'}
    result=scenarios(ledger,assumptions=[{'name':'synthetic','signs':{1:1},'assumption_reference':'fixture'}])['scenarios'][0]
    assert result['included_contracts']==0 and result['raw_subset_gamma'] is None

def test_representative_budget_preserves_family_sides_and_samples_moneyness():
    inputs={i:NS(future=4200,strike=k,kind=kind,years=.1) for i,(k,kind) in enumerate([(4200,'C'),(4200,'P'),(2000,'C'),(8000,'P'),(4195,'C'),(4205,'P')],1)}
    selected=representative_ids(inputs,maximum=6,strata={i:('weekly' if i>4 else 'monthly',41271) for i in inputs})
    assert set(selected)==set(inputs) and len(representative_ids(inputs,maximum=4))==4
    with pytest.raises(ValueError):representative_ids(inputs,maximum=65)
