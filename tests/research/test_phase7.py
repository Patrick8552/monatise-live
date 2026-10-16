"""Synthetic engineering tests. Genuine acceptance uses private runner CLI.

No fixture here is claimed to be genuine exchange data, even when a test
temporarily exercises the authentic-label certification branch.
"""
from dataclasses import replace
from decimal import Decimal
from math import isclose
import hashlib
import json
import struct

import pytest

from monatise.application.gold_options import black76, american_futures, european_greeks
from monatise.research.databento.datasets import InstrumentMetadata
from monatise.research.databento.options import OpenInterest
from monatise.research.databento.acquisition import HistoricalRequest, DownloadPreflight
from monatise.research.institutional.models import Contract,digest,encode
from monatise.research.institutional.options import OptionConvention
from monatise.research.institutional.phase7.basis import Timestamp,Quote,BasisPolicy,certify,map_level
from monatise.research.institutional.phase7.chain import ChainLeg,CoveragePolicy,assess,expanded_requests,review_expanded
from monatise.research.institutional.phase7.greeks import GreekInput,validated,american_fd,validated_curve
from monatise.research.institutional.phase7.scenarios import exposures
from monatise.research.institutional.phase7.replay import native_records
from monatise.research.institutional.phase7.runner import run

NOW=1791903769000000000
S=10**9
SYN='ENGINEERING_SYNTHETIC'
AUTH='AUTHENTIC_ARCHIVED_RECORD'


def quote(symbol,identity,at,*,publisher='GLBX.MDP3/XCEC',bid='4189.2',ask='4189.4',evidence=SYN):
    h=digest((symbol,identity,at))
    stamp=Timestamp(at,at,at,str(at),'ENGINEERING_FIXTURE',h,'ENGINEERING_UTC_AUTHORITY',1)
    return Quote(symbol,publisher,identity,bid,ask,stamp,at+1000,at+2000,h,evidence)


def pairs(evidence=SYN):
    return [(quote('GCZ6',41271,NOW-(10-i*2)*S,evidence=evidence),
             quote('XAUUSD',0,NOW-(10-i*2)*S,publisher='FXCM/RatesXML3',bid='4166',ask='4166.2',evidence=evidence)) for i in range(5)]


def policy():
    return BasisPolicy('ENGINEERING_REVIEW','GCZ6',41271,timing_bound_review_reference='ENGINEERING_BOUND',
                       clock_review_reference='ENGINEERING_CLOCK',identity_review_reference='ENGINEERING_IDENTITY')


def basis(p=None,pol=None):return certify(p if p is not None else pairs(),policy=pol or policy(),cutoff_ns=NOW)


def contract(identity,kind='F',strike=None,expiry=NOW+100*86400*S):
    is_option=kind!='F';product='OG' if is_option else 'GC'
    metadata=InstrumentMetadata('GLBX.MDP3',1,identity,'OGX6 '+kind+str(strike) if is_option else 'GCZ6',
        product,'XCEC',kind,NOW-86400*S,NOW-86400*S+1000,expiry,2026,12,
        int(strike*S) if is_option else None,41271 if is_option else None,
        (('currency','USD'),('min_price_increment','100000000')),digest((identity,kind,strike,expiry)))
    return Contract(metadata,'futures_option' if is_option else 'futures','USD',Decimal('.1'),Decimal(100),'USD_per_troy_oz','ENGINEERING_SPEC')


def chain_inputs():
    parent=contract(41271);legs=[]
    for e in (NOW+14*86400*S,NOW+28*86400*S):
        for strike in (4175,4200):
            for kind in ('C','P'):
                identity=100+len(legs);c=contract(identity,kind,strike,e)
                q=quote(c.metadata.raw_symbol,identity,NOW-2*S,bid='50',ask='50.2')
                u=quote('GCZ6',41271,NOW-2*S)
                oi=OpenInterest(1,identity,100,NOW-86400*S,NOW-3600*S,NOW-3500*S,digest(identity))
                legs.append(ChainLeg(c,OptionConvention('OG','American',c.metadata.definition_sha256,'ENGINEERING_SPEC'),
                    q,u,oi,NOW-86400*S+2000,'ENGINEERING_SETTLEMENT','25','ENGINEERING_INCREMENT'))
    expected=tuple(sorted((l.contract.metadata.expiration_ns,l.contract.metadata.strike_fixed,l.contract.metadata.kind) for l in legs))
    pol=CoveragePolicy('ENGINEERING_SCOPE',expected,digest(expected),'ENGINEERING_CATALOG',minimum_strikes_per_expiry=2)
    return legs,parent,pol


def chain(legs=None,pol=None):
    l,u,p=chain_inputs();return assess(l if legs is None else legs,underlying=u,policy=pol or p,cutoff_ns=NOW,evidence_kind=SYN)


def greek_input(style='European',kind='C'):
    model=black76 if style=='European' else american_futures
    premium=model(100,100,1,.01,.2,kind)
    return GreekInput(100,100,1,.01,kind,style,premium-.05,premium+.05,NOW,NOW-S,'a'*64,'ENGINEERING_SPEC',SYN)


def test_synthetic_cannot_certify_genuine_basis():
    r=basis();assert r['status']=='INDICATIVE';assert r['basis']=='23.2';assert r['uncertainty'] is None
    assert 'synthetic_fixture_cannot_certify_genuine_basis' in r['rejection_reasons']


def test_authoritative_gate_and_uncertainty_geometry():
    r=basis(pairs(AUTH));assert r['status']=='CERTIFIED';assert Decimal(r['uncertainty'])>=Decimal('.2')
    m=map_level(4200,contract='GCZ6',basis=r,now_ns=NOW+S)
    assert m['estimated_spot']=='4176.8';assert m['qualified_spot_mapping'];assert not m['execution_price_authority']
    assert m['actual_executable_broker_price'] is None
    assert Decimal(m['spot_interval'][1])-Decimal(m['estimated_spot'])>Decimal(r['uncertainty'])


@pytest.mark.parametrize('field',['timing_bound_review_reference','clock_review_reference','identity_review_reference'])
def test_narrow_basis_does_not_replace_required_review(field):
    r=basis(pairs(AUTH),replace(policy(),**{field:None}));assert r['status']=='INDICATIVE'


def test_timezone_ambiguity_is_not_inferred_from_matching_clock():
    p=pairs(AUTH);g,s=p[2];p[2]=(g,replace(s,event=replace(s.event,utc_authority_reference=None)))
    r=basis(p);assert r['status']=='INDICATIVE';assert not r['qualified_spot_mapping']


@pytest.mark.parametrize('mutation,expected',[
    ('stale','stale_future'),('crossed','invalid_crossed'),('missing','conversion'),
    ('wide','invalid_crossed'),('contract','contract_or_publisher'),('id','contract_or_publisher'),
    ('publisher','contract_or_publisher'),('future','stale_future'),('duplicate','duplicate_or_dependent'),
    ('skew','skew_exceeded'),('instability','dispersion'),('unavailable','stale_future')])
def test_basis_invalid_current_observation_quarantines_entire_window(mutation,expected):
    p=pairs(AUTH);g,s=p[-1]
    if mutation=='stale':g=quote('GCZ6',41271,NOW-40*S,evidence=AUTH)
    if mutation=='crossed':g=replace(g,bid='4200')
    if mutation=='missing':g=replace(g,bid='')
    if mutation=='wide':g=replace(g,ask='4191')
    if mutation=='contract':g=replace(g,contract='GCG7')
    if mutation=='id':g=replace(g,instrument_id=1)
    if mutation=='publisher':g=replace(g,publisher='UNREVIEWED')
    if mutation=='future':g=quote('GCZ6',41271,NOW+S,evidence=AUTH)
    if mutation=='duplicate':g,s=p[-2]
    if mutation=='skew':g=replace(g,event=replace(g.event,lower_ns=g.event.lower_ns-2*S,precision_ns=2*S))
    if mutation=='instability':g=replace(g,bid='4191',ask='4191.2')
    if mutation=='unavailable':g=replace(g,available_ns=NOW+S)
    p[-1]=(g,s);r=basis(p)
    assert r['status']=='REJECTED';assert r['basis'] is None
    assert expected.lower() in r['rejection_reasons'][0].lower()


def test_reused_poll_hash_does_not_count_as_independent_observation():
    p=pairs(AUTH);g,s=p[-1];h=p[-2][1].source_sha256
    p[-1]=(g,replace(s,source_sha256=h,event=replace(s.event,source_sha256=h)))
    assert basis(p)['status']=='REJECTED'


def test_precision_interval_must_cover_declared_precision():
    with pytest.raises(ValueError):replace(pairs()[0][0].event,precision_ns=S).validate()


def test_restart_recomputes_and_expiry_cannot_restore_certificate():
    p=pairs(AUTH);raw=json.loads(json.dumps(encode(p)))
    restored=[tuple(Quote(**{**q,'event':Timestamp(**q['event'])}) for q in pair) for pair in raw]
    assert basis(p)==basis(restored)
    later=certify(restored,policy=policy(),cutoff_ns=NOW+31*S)
    assert later['status']=='REJECTED'
    assert map_level(4200,contract='GCZ6',basis=basis(p),now_ns=NOW+31*S)['status']=='UNAVAILABLE'


def test_contract_specific_mapping_and_indicative_interval():
    b=basis();assert map_level(4200,contract='GCG7',basis=b,now_ns=NOW)['estimated_spot'] is None
    r=map_level(4200,contract='GCZ6',basis=b,now_ns=NOW)
    assert r['status']=='INDICATIVE_ONLY';assert not r['qualified_spot_mapping']


def test_reviewed_scope_requires_exact_catalog_not_count():
    assert chain()['status']=='REVIEWED_SCOPE_COVERED'
    l,u,p=chain_inputs();r=chain(pol=replace(p,catalog_sha256=None))
    assert r['status']=='INSUFFICIENT_CHAIN_COVERAGE';assert not r['complete_exchange_chain']


@pytest.mark.parametrize('defect',['strike','expiry','put','OI','stale_OI','future_OI','quote','stale_quote','underlying','increment','settlement'])
def test_chain_coverage_failures(defect):
    l,u,p=chain_inputs();first=l[0]
    if defect=='strike':l=l[2:]
    if defect=='expiry':l=l[:4]
    if defect=='put':l=[leg for leg in l if leg.contract.metadata.kind=='C']
    if defect=='OI':l[0]=replace(first,open_interest=None)
    if defect=='stale_OI':l[0]=replace(first,open_interest=replace(first.open_interest,reference_ns=NOW-8*86400*S))
    if defect=='future_OI':l[0]=replace(first,open_interest=replace(first.open_interest,available_ns=NOW+S))
    if defect=='quote':l[0]=replace(first,quote=None)
    if defect=='stale_quote':l[0]=replace(first,quote=replace(first.quote,event=replace(first.quote.event,lower_ns=NOW-40*S)))
    if defect=='underlying':l[0]=replace(first,underlying_quote=replace(first.underlying_quote,instrument_id=111))
    if defect=='increment':l[0]=replace(first,strike_increment_reference=None)
    if defect=='settlement':l[0]=replace(first,settlement_reference=None)
    r=chain(l,p);assert r['status']=='INSUFFICIENT_CHAIN_COVERAGE';assert r['rejection_reasons']
    assert all(not c['gamma_wall'] for c in r['concentrations'])
    if defect in {'OI','stale_OI','future_OI'}:
        assert r['selected_OI_totals'] is None
        assert r['concentrations'][0]['combined_OI'] is None


def test_multi_expiry_planner_reuses_exact_existing_contract_requests():
    l,u,p=chain_inputs();mapping={}
    for leg in l:mapping.setdefault(leg.contract.metadata.expiration_ns,set()).add(leg.contract.metadata.strike_fixed)
    proposal=expanded_requests([leg.contract for leg in l],underlying=u,
        expirations_to_strikes={e:tuple(s) for e,s in mapping.items()},schema='mbp-1',start_ns=NOW,end_ns=NOW+S)
    assert len(proposal)==8;assert len({r.sha256 for r in proposal})==8


def test_acquisition_unknown_cost_entitlement_licensing_and_global_budget():
    req=[HistoricalRequest('GLBX.MDP3','mbp-1',((1,100+i,'OGX6 C'+str(4100+i*25)),),NOW,NOW+S,100,10000) for i in range(10)]
    cache=lambda r:dict(new_download_required=True,overlapping_request_hashes=[])
    def preflight(r):
        return DownloadPreflight(request_sha256=r.sha256,observed_at_ns=NOW,available_from_ns=NOW-S,
            available_to_ns=NOW+2*S,estimated_usd='1',schema_available=True,identities_verified=True,
            metadata_sha256=digest(r),entitlement='VERIFIED_OPERATOR')
    result=review_expanded(req+req[:1],cache_plan=cache,metadata_preflight=preflight,now_ns=NOW,
        approved_credit_ceiling_usd='8',verified_credit_usd='8',credit_expires_ns=NOW+60*S,
        credit_checked_ns=NOW,credit_review_reference='ENGINEERING_CREDIT',zero_cash_protection_reference='ENGINEERING_ZERO_CASH',
        licensing_reference='ENGINEERING_PRIVATE_LICENSE')
    assert result['unique_requests']==10;assert result['duplicates_removed']==1
    assert not result['acquisition_enabled']
    assert 'global_approved_ceiling_exceeded' in result['rejection_reasons']
    assert 'fresh_explicit_request_specific_approval_and_one_use_permits_required' in result['rejection_reasons']


def test_no_cost_estimate_never_grants_download():
    req=HistoricalRequest('GLBX.MDP3','mbp-1',((1,100,'OGX6 C4200'),),NOW,NOW+S,100,10000)
    def unavailable(r):raise RuntimeError('provider_outage')
    r=review_expanded([req],cache_plan=lambda r:dict(new_download_required=True,overlapping_request_hashes=[]),
        metadata_preflight=unavailable,now_ns=NOW)
    assert 'unknown_cost_cannot_download' in r['rejection_reasons'];assert not r['acquisition_enabled']


def test_verified_cache_uses_no_provider_estimate():
    req=HistoricalRequest('GLBX.MDP3','statistics',((1,100,'OGX6 C4200'),),NOW,NOW+S,100,10000)
    r=review_expanded([req],cache_plan=lambda r:dict(new_download_required=False,covering_manifests=['HASH'],uncovered_ranges=[]),
        metadata_preflight=lambda r:pytest.fail('cache must avoid provider call'),now_ns=NOW,licensing_reference='PRIVATE')
    assert r['total_known_estimated_usd']=='0';assert not r['acquisition_enabled']


@pytest.mark.parametrize('kind',['C','P'])
def test_european_sensitivities_agree_with_finite_differences(kind):
    r=validated(greek_input(kind=kind));expected=european_greeks(100,100,1,.01,.2,kind)
    assert r['status']=='VALIDATED_MODEL_SENSITIVITIES'
    assert r['source']=='MODEL_GENERATED_NOT_EXCHANGE_PUBLISHED'
    for k,v in expected.items():assert isclose(r[k],v,rel_tol=1e-6)
    assert r['theta']<0


def test_american_has_independent_price_and_Greek_checks():
    r=validated(greek_input('American'))
    assert r['status']=='REJECTED';assert len(r['diagnostics'])==4
    assert r['gamma'] is None;assert r['iv']==pytest.approx(.2,abs=1e-6)
    assert r['rejection_reasons']==['fine_bump_lattice_gamma_instability']
    assert len(r['fine_gamma_diagnostics'])==4


def test_american_FD_respects_intrinsic_and_zero_rate_european_reference():
    for kind in ('C','P'):
        value=american_fd(100,100,1,0,.2,kind,space=400,time=400)
        assert value>=0;assert value==pytest.approx(black76(100,100,1,0,.2,kind),abs=.04)


@pytest.mark.parametrize('defect',['rate','rate_stale','convention','iv','crossed','nan','unstable'])
def test_unreliable_model_inputs_have_null_Greeks(defect):
    x=greek_input();kwargs={}
    if defect=='rate':x=replace(x,rate=None)
    if defect=='rate_stale':x=replace(x,rate_as_of_ns=NOW-2*86400*S)
    if defect=='convention':x=replace(x,convention_reference=None)
    if defect=='iv':x=replace(x,bid=200,ask=200.1)
    if defect=='crossed':x=replace(x,ask=x.bid-1)
    if defect=='nan':x=replace(x,bid=float('nan'))
    if defect=='unstable':x=greek_input('American');kwargs={'relative_tolerance':0,'price_absolute_tolerance':0}
    r=validated(x,**kwargs);assert r['status']=='REJECTED';assert r['gamma'] is None


def test_partial_coverage_never_calls_model_for_authoritative_flip():
    l,u,p=chain_inputs();c=chain(l[:4],p)
    r=exposures(c,scenarios=[],futures_grid=[],curve=lambda f:pytest.fail('blocked before Greeks'),model_reference='TEST')
    assert r['status']=='INSUFFICIENT_CHAIN_COVERAGE';assert r['gamma_flip'] is None


def test_unknown_inventory_and_hypothetical_roots_are_separate():
    c=chain();ids=[r['contract']['metadata']['instrument_id'] for r in c['contracts']]
    signs={i:1 if n%2==0 else -1 for n,i in enumerate(ids)}
    def curve(f):
        return {i:dict(status='VALIDATED_MODEL_SENSITIVITIES',gamma=.001*(f/4187.5 if n%2==0 else 1),
            evidence_kind=SYN,input_sha256=digest((f,i)),inputs=dict(native_instrument_id=i,future=f,
                strike=c['contracts'][n]['contract']['metadata']['strike_fixed']/1e9,
                kind=c['contracts'][n]['contract']['metadata']['kind'],style='American',cutoff_ns=NOW)) for n,i in enumerate(ids)}
    r=exposures(c,scenarios=[{'name':'unknown','signs':None},
        {'name':'ENGINEERING_HYPOTHESIS','signs':signs,'assumption_reference':'SYNTHETIC_TEST_ONLY'}],
        futures_grid=[4175,4180,4190,4200],curve=curve,model_reference='ENGINEERING_CURVE')
    assert r['observed_dealer_gex'] is None;assert r['gamma_flip'] is None
    assert r['scenarios'][0]['status']=='POSITIONING_UNKNOWN'
    interval=r['scenarios'][1]['roots'][0]['candidate_gc_interval']
    assert interval[0]<=4187.5<=interval[1];assert interval[1]-interval[0]<=.1


def test_unvalidated_gamma_curve_rejected():
    c=chain();ids=[r['contract']['metadata']['instrument_id'] for r in c['contracts']]
    r=exposures(c,scenarios=[dict(name='test',signs={i:1 for i in ids},assumption_reference='TEST')],
        futures_grid=[4175,4180,4200],curve=lambda f:{i:{'status':'REJECTED','gamma':.001} for i in ids},model_reference='TEST')
    assert r['scenarios'][0]['status']=='REJECTED';assert r['scenarios'][0]['roots'] is None


def test_real_numerical_curve_is_counterfactual_and_hash_bound():
    x=replace(greek_input(),native_instrument_id=100)
    curve=validated_curve([x]);point=curve(101)[100]
    assert point['status']=='VALIDATED_MODEL_SENSITIVITIES'
    assert point['counterfactual_model_repricing'];assert not point['observed_market_quote']
    assert point['inputs']['native_instrument_id']==100;assert point['inputs']['future']==101
    assert curve(101)==curve(101)


def test_sensitivity_for_wrong_contract_cannot_supply_scenario():
    c=chain();ids=[r['contract']['metadata']['instrument_id'] for r in c['contracts']]
    def curve(f):return {i:dict(status='VALIDATED_MODEL_SENSITIVITIES',gamma=.001,evidence_kind=SYN,
        input_sha256=digest(i),inputs={'native_instrument_id':999}) for i in ids}
    r=exposures(c,scenarios=[dict(name='test',signs={i:1 for i in ids},assumption_reference='TEST')],
        futures_grid=[4175,4180,4200],curve=curve,model_reference='TEST')
    assert r['scenarios'][0]['status']=='REJECTED'
    assert 'mismatch' in r['scenarios'][0]['rejection_reasons'][0]








def test_native_frame_hash_and_truncation_fail_closed(tmp_path):
    p=tmp_path/'record.native';p.write_bytes(struct.pack('>QI',NOW,16)+b'bad')
    h=hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='frame'):list(native_records(p,expected_hash=h,expected_count=1,cutoff_ns=NOW))
    with pytest.raises(ValueError,match='hash'):list(native_records(p,expected_hash='0'*64,expected_count=1,cutoff_ns=NOW))


def test_missing_genuine_archive_not_reconstructed(tmp_path):
    with pytest.raises(ValueError,match='missing_no_recreation'):
        run(capture=tmp_path,basis_reference=tmp_path/'basis',technical_reference=tmp_path/'technical',
            user_evidence_json=tmp_path/'user.json',user_evidence_text=tmp_path/'user.txt',output=tmp_path/'output')
    assert not (tmp_path/'output').exists()


def udi_record(**changes):
    import databento_dbn as dbn
    args=dict(publisher_id=1,instrument_id=42635889,ts_event=NOW-86400*S,ts_recv=NOW-86400*S+1000,
        min_price_increment=100000000,display_factor=10000000,raw_symbol='OGX6 C4200',asset='OG',
        security_type='OOF',instrument_class=dbn.InstrumentClass.CALL,security_update_action=dbn.SecurityUpdateAction.ADD,expiration=NOW+14*86400*S,
        unit_of_measure_qty=100*S,min_price_increment_amount=100000000,strike_price=4200*S,
        underlying_id=41271,maturity_year=2026,maturity_month=11,currency='USD',exchange='XCEC',
        cfi='OCAXPS',unit_of_measure='TRYOZ',underlying='GCZ6',strike_price_currency='USD',user_defined_instrument=dbn.UserDefinedInstrument.YES)
    args.update(changes);return dbn.InstrumentDefMsg(**args)


def test_reviewed_UDI_preserves_original_native_flag_and_hash():
    from monatise.research.institutional.phase7.udi import reviewed_definition,UDIReview
    from monatise.research.databento.datasets import DatasetCapability,discover
    row=udi_record();raw=bytes(row);h=hashlib.sha256(raw).hexdigest()
    cap=DatasetCapability('GLBX.MDP3',('definition',),NOW-S,'a'*64)
    with pytest.raises(ValueError):discover(row,publishers={1:('GLBX.MDP3','GLBX')},capability=cap,as_of_ns=NOW)
    c=reviewed_definition(row,underlying=contract(41271),capability=cap,publishers={1:('GLBX.MDP3','GLBX')},
        as_of_ns=NOW,review=UDIReview(h,'ENGINEERING_UDI_REVIEW'))
    assert bytes(row)==raw;assert c.metadata.definition_sha256==h
    assert dict(c.metadata.native_terms)['user_defined_instrument']=='Y'


@pytest.mark.parametrize('defect',['review','hash','legs','type','cfi','underlying','symbol','currency','multiplier'])
def test_UDI_extension_does_not_admit_unreviewed_or_multileg_records(defect):
    from monatise.research.institutional.phase7.udi import reviewed_definition,UDIReview
    from monatise.research.databento.datasets import DatasetCapability
    changes={}
    if defect=='legs':changes={'leg_count':2}
    if defect=='type':changes={'security_type':'MLEG'}
    if defect=='cfi':changes={'cfi':'OCEXPS'}
    if defect=='underlying':changes={'underlying_id':1}
    if defect=='symbol':changes={'raw_symbol':'OGX6 C4205'}
    if defect=='currency':changes={'currency':'EUR'}
    if defect=='multiplier':changes={'unit_of_measure_qty':10*S}
    row=udi_record(**changes);h=hashlib.sha256(bytes(row)).hexdigest()
    review=None if defect=='review' else UDIReview('b'*64 if defect=='hash' else h,'ENGINEERING_REVIEW')
    with pytest.raises(ValueError):reviewed_definition(row,underlying=contract(41271),
        capability=DatasetCapability('GLBX.MDP3',('definition',),NOW-S,'a'*64),
        publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=NOW,review=review)
