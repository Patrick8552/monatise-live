from copy import deepcopy
import json
import pytest
from monatise.research.phase10.access import AnalysisRequest,AnalysisService
from monatise.research.phase10.cli import main
from tests.research.phase9.test_pipeline import pipeline,trade,add,NOW_NS


def test_request_keeps_missing_optional_layers_separate_from_trade_qualification():
    p,c=pipeline();assert add(p,trade(c),'trades',1)['accepted']
    r=AnalysisService(p).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS,mandatory=('trade_features',)))
    a=r['instruments'][c.metadata.raw_symbol]
    assert a['components']['trade_features']['available']
    assert not a['components']['price:1h']['available']
    assert not a['components']['mbp-1']['available']
    assert a['basis_status']=='NOT_APPLICABLE' and not r['options_required']
    assert a['decision']=='NO_TRADE' and a['qualification_status']=='NOT_EVALUATED'
    assert not a['execution_eligible'] and not a['gil_enabled']

@pytest.mark.parametrize('health',[{'quarantined':True,'status':'STOPPED'},{'stale_checkpoint':True}])
def test_stopped_or_stale_capture_cannot_be_reported_as_live_available(health):
    p,c=pipeline();add(p,trade(c),'trades',1)
    a=AnalysisService(p,source_health=lambda now:health).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS,mandatory=('trade_features',)))['instruments'][c.metadata.raw_symbol]
    assert a['availability']=='UNAVAILABLE'
    assert a['calculated_availability']!='UNAVAILABLE'
    assert a['capture_health']==health and not a['live_analysis_certified']


def test_unknown_contract_does_not_block_loaded_contract():
    p,c=pipeline();add(p,trade(c),'trades',1)
    result=AnalysisService(p).analyse(AnalysisRequest(('UNKNOWN',c.metadata.raw_symbol),NOW_NS))
    assert result['instruments']['UNKNOWN']['availability']=='UNAVAILABLE'
    assert result['instruments'][c.metadata.raw_symbol]['components']['trade_features']['available']

@pytest.mark.parametrize('kwargs',[{'symbols':('NQZ6','NQZ6')},{'cutoff_ns':True},{'timeframes':('2m',)},{'mandatory':('trade',)},{'symbols':()}])
def test_invalid_request_is_rejected_before_analysis(kwargs):
    with pytest.raises(ValueError):AnalysisRequest(**dict(dict(symbols=('NQZ6',),cutoff_ns=NOW_NS),**kwargs))


def test_cli_reports_unavailable_without_creating_source_files(tmp_path,capsys):
    target=tmp_path/'does-not-exist'
    assert main(['--capture',str(target),'--symbols','NQZ6'])==2
    assert not target.exists()
    assert json.loads(capsys.readouterr().err)['availability']=='UNAVAILABLE'


def test_cli_rejects_naive_cutoff(tmp_path,capsys):
    assert main(['--capture',str(tmp_path),'--symbols','NQZ6','--as-of','2026-10-15T00:00:00'])==2
    assert json.loads(capsys.readouterr().err)['error_type']=='ValueError'


def test_catalog_lists_candidates_without_enabling_them(capsys):
    assert main(['--list-instruments'])==0
    value=json.loads(capsys.readouterr().out)
    assert set(value['candidates'])=={'YM','RTY','CL','SI'}
    assert value['supported_research_products']==['GC','ES','NQ']
    assert all(not x['analytical_support_enabled'] for x in value['candidates'].values())


def test_human_report_shows_missing_history_and_never_qualifies_trade():
    from monatise.research.phase10.formatting import text_report
    p,c=pipeline();add(p,trade(c),'trades',1)
    text=text_report(AnalysisService(p).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS,mandatory=('trade_features',))))
    assert 'VWAP' in text and 'insufficient_validated_history' in text
    assert 'NOT_EVALUATED' in text and 'NO_TRADE' in text
