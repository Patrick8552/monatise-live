"""Offline Phase 5 boundaries; native-shaped data is explicitly engineering."""
import asyncio
from dataclasses import replace
from decimal import Decimal
import hashlib
import json

import databento_dbn as dbn
import pytest

from monatise.research.institutional.broker_import import BrokerSpecification,BrokerSessions,ImportedBrokerQuote,import_quotes,import_candles
from monatise.research.institutional.mapping import MappingPolicy
from monatise.research.institutional.mapping_report import report
from monatise.research.institutional.fixtures import contract,quote,NOW_NS,candle_evidence,positioning
from monatise.research.institutional.models import digest,encode
from monatise.research.institutional.cached_bundle import admit
from monatise.research.institutional.options import OptionConvention
from monatise.research.institutional.options_coverage import select,coverage
from monatise.research.institutional.presentation import complete,text_preview
from monatise.research.institutional.signals import broker_preview
from monatise.research.institutional.phase5_runner import run
from monatise.research.institutional.phase5_metadata import proposal
from monatise.research.institutional.native_index import validate as validate_index
from monatise.research.institutional.native_window import diagnose
from monatise.research.databento.acquisition import HistoricalRequest,DownloadPreflight
from monatise.research.databento.options import OpenInterest
from tests.research.test_databento_history import write_dbn


def specification(asset='GC',**changes):
    values=dict(broker='ENGINEERING_BROKER',server='ENGINEERING_SERVER',account_reference='opaque-fixture-account',
        instrument={'GC':'XAU/USD','ES':'US500.cash','NQ':'US100.cash'}[asset],
        native_symbol={'GC':'XAUUSD','ES':'US500.cash','NQ':'US100.cash'}[asset],currency='USD',
        price_unit='USD_PER_TRYOZ' if asset=='GC' else 'INDEX_POINT',digits=2,tick_size=Decimal('.01'),
        point=Decimal('.01'),contract_size=Decimal('100'),source_sha256=digest('ENGINEERING_SPEC'),
        available_ns=NOW_NS-86400*10**9)
    values.update(changes);return BrokerSpecification(**values)


def sessions(spec):
    return BrokerSessions(spec.namespace,digest('ENGINEERING_SESSION'),'ENGINEERING_REVIEW',
                          ((NOW_NS-3600*10**9,NOW_NS+3600*10**9),))


def pair(asset='GC',i=0,**changes):
    spec=specification(asset);t=NOW_NS-(5-i)*10**9
    values=dict(specification=spec,bid=Decimal('2518') if asset=='GC' else Decimal('4999'),
        ask=Decimal('2518.2') if asset=='GC' else Decimal('4999.5'),event_ns=t,receive_ns=t,
        admission_ns=t+1,available_ns=t+1,source_sha256=digest('ENGINEERING_QUOTES'),
        record_sha256=digest(i),ordinal=i,evidence_kind='ENGINEERING_SYNTHETIC',session_sha256=sessions(spec).source_sha256)
    values.update(changes)
    return quote(contract(asset),receive_ns=t,ordinal=i),ImportedBrokerQuote(**values)


def mapping(asset='GC',**changes):
    pairs=[pair(asset,i) for i in range(5)]
    values=dict(contract=contract(asset),futures_quotes=[p[0] for p in pairs],broker_quotes=[p[1] for p in pairs],
        broker_sessions=sessions(specification(asset)),futures_session=dict(start_ns=NOW_NS-3600*10**9,
            end_ns=NOW_NS+3600*10**9,review_reference='ENGINEERING_FUTURES_SESSION'),
        policy=MappingPolicy('ENGINEERING_POLICY'),cutoff_ns=NOW_NS,level='2520' if asset=='GC' else '5002')
    values.update(changes);return report(**values)


@pytest.mark.parametrize('asset',['GC','ES','NQ'])
def test_mapping_complete_context_report_and_server_bound_namespace(asset):
    result=mapping(asset)
    assert result['mapping_valid'] and result['valid_paired_observations']==5
    assert result['mapped_reference_level']=='2519.0' if asset=='GC' else result['mapped_reference_level']=='5001.00'
    assert result['uncertainty'] and result['expiry_ns']>NOW_NS and result['context_only']
    assert not result['execution_eligible'] and not result['approval_eligible']
    assert specification(asset).namespace!=specification(asset,server='OTHER_SERVER').namespace


def test_mapping_hash_binds_level_and_session_and_rejection_preserves_missing_clock():
    first=mapping();second=mapping(level='2521')
    assert first['input_sha256']!=second['input_sha256'] and first['mapped_reference_level']!=second['mapped_reference_level']
    pairs=[pair(i=i) for i in range(5)]
    rejected=mapping(futures_quotes=[p[0] for p in pairs],broker_quotes=[replace(p[1],receive_ns=None) for p in pairs])
    assert not rejected['mapping_valid'] and rejected['observation_timestamps'][0]['broker_receive_ns'] is None


@pytest.mark.parametrize('fault',['missing_receipt','future_broker','future_admission','stale','expiry','session',
                                  'provider','repeated_future','repeated_broker','mismatched_count','empty'])
def test_mapping_rejects_missing_or_invalid_synchronization(fault):
    pairs=[pair(i=i) for i in range(5)];f=[p[0] for p in pairs];b=[p[1] for p in pairs];kwargs={}
    if fault=='missing_receipt':b[0]=replace(b[0],receive_ns=None)
    if fault=='future_broker':b[0]=replace(b[0],event_ns=f[0].receive_ns+1,receive_ns=f[0].receive_ns+1)
    if fault=='future_admission':b[0]=replace(b[0],available_ns=NOW_NS+1,admission_ns=NOW_NS+1)
    if fault=='stale':kwargs['cutoff_ns']=NOW_NS+31*10**9
    if fault=='expiry':kwargs['cutoff_ns']=contract().metadata.expiration_ns
    if fault=='session':kwargs['broker_sessions']=replace(sessions(specification()),intervals=((NOW_NS-3600*10**9,NOW_NS),))
    if fault=='provider':b[0]=replace(b[0],specification=specification(server='OTHER'))
    if fault=='repeated_future':f[1]=f[0]
    if fault=='repeated_broker':b[1]=b[0]
    if fault=='mismatched_count':b.pop()
    if fault=='empty':f=[];b=[]
    result=mapping(futures_quotes=f,broker_quotes=b,**kwargs)
    assert not result['mapping_valid'] and result['status']=='MAPPING_UNAVAILABLE'
    assert result['observed_basis'] is None and result['mapped_reference_level'] is None and result['rejection_reasons']


@pytest.mark.parametrize('changes',[{'tick_size':'.015'},{'point':'.1'},{'digits':True},{'currency':'EUR'},
                                  {'price_unit':'UNKNOWN'},{'contract_size':0},{'server':''}])
def test_broker_specification_rejects_contradictions(changes):
    with pytest.raises(ValueError):specification(**changes)


def export(tmp_path,*,kind='RETROSPECTIVE_HISTORICAL_DOWNLOAD',receipt=None):
    spec=specification();s=sessions(spec);t=NOW_NS-10**9
    row=dict(bid='2518.00',ask='2518.20',event_ns=t,receive_ns=receipt,
             time_msc=t//10**6,original_available_ns=t+1)
    doc=dict(schema='broker-quote-export-v1',evidence_kind=kind,specification_namespace=spec.namespace,quotes=[row])
    path=tmp_path/'quotes.json';path.write_text(json.dumps(doc,sort_keys=True))
    review=dict(source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),specification_namespace=spec.namespace,
        session_sha256=s.source_sha256,origin_review_reference='ENGINEERING_SOURCE_REVIEW',
        clock_review_reference='ENGINEERING_UTC_REVIEW',evidence_kind=kind)
    return path,spec,s,review


def test_historical_quotes_preserve_null_receipt_and_retrospective_availability(tmp_path):
    p,s,c,r=export(tmp_path)
    q,=import_quotes(p,specification=s,sessions=c,review=r,admission_ns=NOW_NS+86400*10**9)
    assert q.receive_ns is None and q.available_ns==q.admission_ns and q.midpoint==Decimal('2518.10')
    with pytest.raises(ValueError,match='receipt_unavailable'):q.basis_quote(cutoff_ns=q.admission_ns)


def test_point_in_time_quote_requires_review_and_cannot_backdate_historical(tmp_path):
    p,s,c,r=export(tmp_path,kind='POINT_IN_TIME_OBSERVATION',receipt=NOW_NS-10**9)
    with pytest.raises(ValueError,match='capture_proof'):import_quotes(p,specification=s,sessions=c,review=r,admission_ns=NOW_NS)
    r['original_capture_proof_reference']='ENGINEERING_CAPTURE_PROOF'
    q,=import_quotes(p,specification=s,sessions=c,review=r,admission_ns=NOW_NS)
    assert q.available_ns==NOW_NS-10**9+1 and q.receive_ns==NOW_NS-10**9
    assert q.basis_quote(cutoff_ns=NOW_NS).provider==s.namespace


@pytest.mark.parametrize('fault',['hash','namespace','session','time','price','numeric_price','unordered','capacity'])
def test_quote_import_review_and_native_clock_validation(tmp_path,fault):
    p,s,c,r=export(tmp_path);doc=json.loads(p.read_text())
    if fault=='hash':r['source_sha256']=digest('other')
    if fault=='namespace':r['specification_namespace']='OTHER'
    if fault=='session':r['session_sha256']=digest('other')
    if fault=='time':doc['quotes'][0]['time_msc']+=1
    if fault=='price':doc['quotes'][0]['bid']='2518.001'
    if fault=='numeric_price':doc['quotes'][0]['bid']=2518
    if fault=='unordered':doc['quotes']+=[dict(doc['quotes'][0],event_ns=NOW_NS-2*10**9,time_msc=(NOW_NS-2*10**9)//10**6)]
    if fault not in {'hash','namespace','session'}:
        p.write_text(json.dumps(doc));r['source_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(ValueError):import_quotes(p,specification=s,sessions=c,review=r,admission_ns=NOW_NS,
                                                capacity=True if fault=='capacity' else 50000)


def native_file(tmp_path,*,limit=10):
    c=contract('ES');t=NOW_NS-10**9
    request=HistoricalRequest('GLBX.MDP3','trades',(c.identity[1:4],),t,t+10**9,limit)
    row=dbn.TradeMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=t+1,ts_recv=t+2,
        price=5000*10**9,size=2,action=dbn.Action.TRADE,side=dbn.Side.NONE,depth=0,sequence=1,flags=0)
    path=tmp_path/'es.dbn.zst';write_dbn(path,request,[row,row],compressed=True)
    review=dict(origin_review_reference='ENGINEERING_REVIEW',request_sha256=request.sha256,
        definition_sha256=c.metadata.definition_sha256,billing_status='RECONCILED',request_receipt_reference='ENGINEERING_NO_CHARGE',
        evidence_kind='ENGINEERING_SYNTHETIC',archive_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        retrieval_ns=NOW_NS,admission_ns=NOW_NS)
    return path,request,c,review


def test_cached_archive_reuses_native_normalization_and_source_ordinals(tmp_path):
    p,r,c,v=native_file(tmp_path)
    a=admit(p,request=r,contract=c,review=v,enabled_schemas=('trades',))
    b=admit(p,request=r,contract=c,review=v,enabled_schemas=('trades',))
    assert a==b and not a['continuity_certified'] and a['evidence_kind']=='ENGINEERING_SYNTHETIC'
    assert a['observations'][0].payload==('5000',2,None)
    assert a['observations'][0].source.record_sha256==a['observations'][1].source.record_sha256
    assert a['observations'][0].source.position!=a['observations'][1].source.position


@pytest.mark.parametrize('fault',['hash','identity','billing','receipt','definition','disabled','incomplete'])
def test_native_cache_admission_fails_closed(tmp_path,fault):
    p,r,c,v=native_file(tmp_path,limit=2 if fault=='incomplete' else 10);enabled=('trades',)
    if fault=='hash':v['archive_sha256']=digest('other')
    if fault=='identity':c=contract('NQ')
    if fault=='billing':v['billing_status']='UNKNOWN'
    if fault=='receipt':v['request_receipt_reference']=None
    if fault=='definition':v['definition_sha256']=digest('other')
    if fault=='disabled':enabled=()
    with pytest.raises(ValueError):admit(p,request=r,contract=c,review=v,enabled_schemas=enabled)


def option_inputs():
    parent,child=contract(),contract(option=True)
    convention=OptionConvention('OG','American',child.metadata.definition_sha256,'ENGINEERING_STANDARD_OG')
    oi=OpenInterest(1,child.metadata.instrument_id,123,NOW_NS-86400*10**9,NOW_NS-3600*10**9,
                    NOW_NS-3600*10**9,digest('ENGINEERING_OI'))
    return parent,child,convention,oi


def test_bounded_exact_og_selection_and_partial_OI_concentration():
    p,c,v,oi=option_inputs()
    chosen=select([p,c],underlying=p,expiration_ns=c.metadata.expiration_ns,strikes_fixed=(c.metadata.strike_fixed,))
    result=coverage(chosen,underlying=p,conventions={c.metadata.definition_sha256:v},open_interest=(oi,),
                    cutoff_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC')
    assert chosen==(c,) and result['selected_strike_contracts']=={'2500':123}
    assert result['selected_call_put_contracts']=={'C':123,'P':None} and not result['complete_chain']
    assert result['signed_dealer_gex'] is result['gamma_flip'] is None and not result['gil_enabled']
    empty=coverage((c,),underlying=p,conventions={c.metadata.definition_sha256:v},cutoff_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC')
    assert empty['selected_call_put_contracts'] is None and empty['contracts'][0]['open_interest'] is None


def test_partial_selected_OI_never_turns_unknown_put_or_strike_total_into_zero():
    p,c,v,oi=option_inputs()
    put=replace(c,metadata=replace(c.metadata,instrument_id=900004,kind='P',raw_symbol='OGZ6 P2500',
                                 definition_sha256=digest('ENGINEERING_PUT_DEFINITION')))
    convention=OptionConvention('OG','American',put.metadata.definition_sha256,'ENGINEERING_PUT_REVIEW')
    result=coverage((c,put),underlying=p,conventions={c.metadata.definition_sha256:v,put.metadata.definition_sha256:convention},
                    open_interest=(oi,),cutoff_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC')
    assert result['selected_call_put_contracts']=={'C':123,'P':None}
    assert result['selected_strike_contracts']=={'2500':None}
    assert result['observed_call_put_contracts']=={'C':123} and result['observed_strike_contracts']=={'2500':123}
    assert 'published_open_interest' in result['missing']


@pytest.mark.parametrize('fault',['duplicate','capacity','underlying','future_OI','unrelated_OI','style','expired'])
def test_options_identity_clock_and_convention_guards(fault):
    p,c,v,oi=option_inputs();kwargs=dict(underlying=p,conventions={c.metadata.definition_sha256:v},open_interest=(oi,),
                                      cutoff_ns=NOW_NS,evidence_kind='ENGINEERING_SYNTHETIC')
    if fault=='duplicate':
        with pytest.raises(ValueError):select([c,c],underlying=p,expiration_ns=c.metadata.expiration_ns,strikes_fixed=(c.metadata.strike_fixed,))
        return
    if fault=='capacity':
        with pytest.raises(ValueError):select([c],underlying=p,expiration_ns=c.metadata.expiration_ns,strikes_fixed=(c.metadata.strike_fixed,),capacity=100)
        return
    if fault=='underlying':kwargs['underlying']=contract('ES')
    if fault=='future_OI':kwargs['open_interest']=(replace(oi,available_ns=NOW_NS+1),)
    if fault=='unrelated_OI':kwargs['open_interest']=(replace(oi,instrument_id=999),)
    if fault=='style':kwargs['conventions']={}
    if fault=='expired':kwargs['cutoff_ns']=c.metadata.expiration_ns
    with pytest.raises(ValueError):coverage((c,),**kwargs)






def test_phase5_isolated_two_repeat_hash_and_authentic_fixture_separation(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABENTO_API_KEY','FAKE_SECRET_MUST_NOT_BE_READ')
    output=tmp_path/'phase5';summary=run(output=output)
    assert summary['repeat_equal'] and summary['actual_downloads']==0 and summary['credit_used_usd']=='0'
    result=json.loads((output/'preview-01.json').read_text())
    assert all(v['analytical_qualification']=='BLOCKED_AUTHENTIC_INPUTS' for v in result['authentic_previews'].values())
    assert result['engineering_previews']['GC']['decision']=='INSUFFICIENT_MARKET_DATA'
    assert 'FAKE_SECRET' not in (output/'preview-01.json').read_text()
    assert (output/'preview-01.json').read_bytes()==(output/'preview-02.json').read_bytes()
    with pytest.raises(FileExistsError):run(output=output)


def test_broker_candle_export_binds_five_timeframes_spec_tick_and_origin(tmp_path):
    evidence=candle_evidence();spec=specification()
    calendar=BrokerSessions(spec.namespace,digest('ENGINEERING_CANDLE_CALENDAR'),'ENGINEERING_REVIEW',
        ((NOW_NS-60*86400*10**9,NOW_NS+3600*10**9),))
    rows=json.loads(evidence.timeframes_json)
    for series in rows.values():
        for row in series:
            for k in ('o','h','l','c'):row[k]=str(row[k])
    doc=dict(schema='broker-candle-export-v1',evidence_kind='ENGINEERING_SYNTHETIC',
        specification_namespace=spec.namespace,original_available_ns=evidence.captured_ns,timeframes=rows)
    path=tmp_path/'candles.json';path.write_text(json.dumps(doc,sort_keys=True))
    review=dict(source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),specification_namespace=spec.namespace,
        session_sha256=calendar.source_sha256,origin_review_reference='ENGINEERING_ORIGIN',clock_review_reference='ENGINEERING_UTC',
        evidence_kind='ENGINEERING_SYNTHETIC',volume_kind='broker_tick_count')
    result=import_candles(path,specification=spec,sessions=calendar,review=review,admission_ns=NOW_NS,
        cutoff_ns=NOW_NS,spread_price='.2',confirmation_sha256=evidence.confirmation_sha256,confirmation_ns=NOW_NS)
    assert result.rows(expected='XAU/USD',now_ns=NOW_NS)==json.loads(evidence.timeframes_json)
    with pytest.raises(ValueError):import_candles(path,specification=spec,sessions=calendar,
        review=dict(review,volume_kind='exchange_contracts'),admission_ns=NOW_NS,cutoff_ns=NOW_NS,spread_price='.2')
    with pytest.raises(RuntimeError,match='engineering_candles_cannot_enter_authentic'):
        run(output=tmp_path/'mislabelled',broker_inputs={'GC':dict(evidence=result,cutoff_ns=NOW_NS)})
    doc['timeframes']['1m'][0]['t']=doc['timeframes']['1m'][0]['t'].replace('+00:00','')
    path.write_text(json.dumps(doc));review['source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='explicit_UTC'):
        import_candles(path,specification=spec,sessions=calendar,review=review,admission_ns=NOW_NS,
                       cutoff_ns=NOW_NS,spread_price='.2')


class MetadataFixture:
    def __init__(self,fault=None):
        self._client=self;self.metadata=self;self.symbology=self;self.requests=[];self.fault=fault
    def list_publishers(self):return [dict(publisher_id=1,dataset='GLBX.MDP3',venue='GLBX')]
    def resolve(self,**params):
        assert params['symbols']==['ESZ6','NQZ6'] and params['stype_in']=='raw_symbol'
        return dict(partial=['ESZ6'] if self.fault=='partial' else [],not_found=[],
            result={s:[dict(d0='2026-10-05',d1='2026-10-06',s=str(i))] for s,i in [('ESZ6',900001),('NQZ6',900002)]})
    def preflight(self,request,*,now_ns):
        self.requests.append(request)
        return DownloadPreflight(request.sha256,now_ns,request.start_ns,request.end_ns,'0.01',
                                 self.fault!='schema',self.fault!='identity',digest('ENGINEERING_METADATA'))
    def download(self,*args,**kwargs):raise AssertionError('Metadata cannot download')


@pytest.mark.parametrize('portal',[False,True])
def test_exact_metadata_quotes_do_not_download_approve_or_assume_entitlement(portal):
    from monatise.research.institutional.native import START_NS,END_NS
    source=MetadataFixture()
    result=proposal(source,now_ns=NOW_NS,end_ns=START_NS+1200*10**9 if portal else END_NS)
    assert len(source.requests)==6 and {r.schema for r in source.requests}=={'definition','trades','ohlcv-1m'}
    assert result['entitlement']=='UNVERIFIED' and result['numeric_credit_only_ceiling'] is None
    assert not result['acquisition_enabled'] and result['actual_downloads']==0
    assert all(r['cache_plan']['status']=='CACHE_INSPECTION_REQUIRED' and r['request_receipt'] is None for r in result['requests'])


@pytest.mark.parametrize('fault',['partial','schema','identity'])
def test_metadata_preflight_missing_inputs_cannot_produce_ready_proposal(fault):
    with pytest.raises(ValueError):proposal(MetadataFixture(fault),now_ns=NOW_NS)


@pytest.mark.parametrize('product,multiplier,amount',[('ES',50,125000000),('NQ',20,50000000)])
def test_native_index_display_factor_adjusts_tick_amount_not_market_prices(product,multiplier,amount):
    from monatise.research.institutional.fixtures import CAPABILITY
    row=dbn.InstrumentDefMsg(publisher_id=1,instrument_id=10252 if product=='ES' else 261401,
        ts_event=NOW_NS-86400*10**9,ts_recv=NOW_NS-86400*10**9+1,raw_symbol=product+'Z6',asset=product,
        exchange='XCME',currency='USD',min_price_increment=250000000,
        min_price_increment_amount=amount,display_factor=10000000,unit_of_measure='IPNT',
        unit_of_measure_qty=multiplier*10**9,instrument_class=dbn.InstrumentClass.FUTURE,security_type='FUT',
        security_update_action=dbn.SecurityUpdateAction.ADD,expiration=NOW_NS+60*86400*10**9,
        maturity_year=2026,maturity_month=12,user_defined_instrument=dbn.UserDefinedInstrument.NO)
    value=validate_index(row,capability=CAPABILITY,publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=NOW_NS)
    assert value.multiplier==Decimal(multiplier) and value.tick_size==Decimal('.25')
    assert quote(value,bid='5000',ask='5000.5').payload[0][0]=='5000'
    bad=dbn.InstrumentDefMsg(publisher_id=1,instrument_id=10252,ts_event=NOW_NS-100,ts_recv=NOW_NS-99,
        raw_symbol='ESZ6',asset='ES',exchange='XCME',currency='USD',min_price_increment=250000000,
        min_price_increment_amount=125000001,display_factor=10000000,unit_of_measure='IPNT',
        unit_of_measure_qty=50*10**9,instrument_class=dbn.InstrumentClass.FUTURE,security_type='FUT',
        security_update_action=dbn.SecurityUpdateAction.ADD,expiration=NOW_NS+60*86400*10**9,
        maturity_year=2026,maturity_month=12,user_defined_instrument=dbn.UserDefinedInstrument.NO)
    with pytest.raises(ValueError,match='convention_contradiction'):
        validate_index(bad,capability=CAPABILITY,publishers={1:('GLBX.MDP3','GLBX')},as_of_ns=NOW_NS)


def test_successful_pinned_sdk_file_transport_closes_lazy_reader(monkeypatch,tmp_path):
    import databento
    import requests
    from monatise.research.databento.acquisition import SDKHistoricalSource
    from monatise.research.databento.controls import ResearchLedger
    from tests.research.test_databento_history import request,preflight,approval,trade,NOW_NS as TEST_NOW
    req=request();fixture=tmp_path/'fixture.dbn.zst';write_dbn(fixture,req,[trade()],compressed=True)
    payload=fixture.read_bytes();handles=[];original=databento.DBNStore.from_file
    def tracked(path):
        value=original(path);handles.append(value._data_source.reader);return value
    monkeypatch.setattr(databento.DBNStore,'from_file',staticmethod(tracked))
    class Response:
        status_code=200;headers={}
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def iter_content(self,chunk_size):yield payload
    monkeypatch.setattr(requests,'post',lambda *args,**kwargs:Response())
    ledger=ResearchLedger(tmp_path/'ledger.sqlite');ledger.configure(approved_budget_usd='2',review_reference='ENGINEERING')
    pre=preflight(req);permit=approval(req,pre);ledger.reserve(req,pre,permit)
    source=SDKHistoricalSource(key='fixture-not-real-private-key',clock_ns=lambda:TEST_NOW)
    source.download(req,tmp_path/'download.dbn.zst',preflight=pre,approval=permit,cost_control=ledger)
    assert handles and all(h.closed for h in handles)
    assert (tmp_path/'download.dbn.zst').read_bytes()==payload


def test_index_archive_bundle_diagnostics_cannot_promote_engineering_or_unknown_billing(tmp_path):
    from dataclasses import asdict
    from monatise.research.databento.archive import NativeDBNArchive
    from monatise.research.databento.acquisition import inspect_request_archive
    from monatise.research.institutional.native import START_NS,END_NS
    archive=NativeDBNArchive(tmp_path/'native-dbn')
    for product,multiplier,iid in [('ES',50,900001),('NQ',20,900002)]:
        for schema in ('definition','trades','ohlcv-1m'):
            start=START_NS//(86400*10**9)*(86400*10**9) if schema=='definition' else START_NS
            end=START_NS if schema=='definition' else END_NS
            request=HistoricalRequest('GLBX.MDP3',schema,((1,iid,product+'Z6'),),start,end,record_limit=100)
            if schema=='definition':
                records=[dbn.InstrumentDefMsg(publisher_id=1,instrument_id=iid,ts_event=start-1,ts_recv=start,
                    raw_symbol=product+'Z6',asset=product,exchange='XCME',currency='USD',min_price_increment=250000000,
                    min_price_increment_amount=int(Decimal('.25')*multiplier*10**9),display_factor=10**9,
                    unit_of_measure='IPNT',unit_of_measure_qty=multiplier*10**9,instrument_class=dbn.InstrumentClass.FUTURE,
                    security_type='FUT',security_update_action=dbn.SecurityUpdateAction.ADD,expiration=NOW_NS+60*86400*10**9,
                    maturity_year=2026,maturity_month=12,user_defined_instrument=dbn.UserDefinedInstrument.NO)]
            elif schema=='trades':
                records=[dbn.TradeMsg(publisher_id=1,instrument_id=iid,ts_event=start+1,ts_recv=start+2,
                    price=5000*10**9,size=2,action=dbn.Action.TRADE,side=dbn.Side.NONE,depth=0,sequence=1,flags=0)]
            else:
                records=[dbn.OHLCVMsg(rtype=dbn.RType.OHLCV_1M,publisher_id=1,instrument_id=iid,
                    ts_event=start+i*60*10**9,open=(5000+i)*10**9,high=(5001+i)*10**9,
                    low=(4999+i)*10**9,close=(5000+i)*10**9,volume=2) for i in range(15)]
            write_dbn(archive.staging(request.sha256),request,records,compressed=True);h=archive.seal(request.sha256)
            manifest=dict(request=asdict(request),status='ARCHIVED',evidence_kind='ENGINEERING_SYNTHETIC',archive_sha256=h,
                coverage=inspect_request_archive(archive.verify(h),request),preflight=dict(observed_at_ns=NOW_NS,
                    metadata_sha256=digest('ENGINEERING_METADATA'),estimated_usd='0'),retrieval_ns=NOW_NS,
                ingestion_ns=NOW_NS+1,actual_billed_usd=None,actual_cost_status='UNKNOWN')
            (tmp_path/('result-'+request.sha256+'.json')).write_text(json.dumps(manifest,sort_keys=True))
    first=diagnose(tmp_path,allow_engineering=True);second=diagnose(tmp_path,allow_engineering=True)
    assert first==second and first['quarantined_for_billing'] and set(first['products'])=={'ES','NQ'}
    for product in first['products'].values():
        assert product['counts']=={'definitions':1,'trades':1,'candles':15} and product['missing_minute_opens_ns']==[]
        assert product['evidence_kind']=='ENGINEERING_SYNTHETIC' and not product['research_admission_eligible']
        assert product['indicators']['trades']['cvd'] is None and product['incomplete_h1']
    with pytest.raises(ValueError,match='reviewed_exact'):diagnose(tmp_path)
    file=next(tmp_path.glob('result-*.json'));value=json.loads(file.read_text());value['coverage']['transport_complete']=False
    file.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='incomplete_or_revised'):diagnose(tmp_path,allow_engineering=True)
