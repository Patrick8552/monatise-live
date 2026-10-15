from decimal import Decimal
from dataclasses import replace
from monatise.research.phase9.quality import PriceGuard
from monatise.research.phase10.market_info import FuturesMarketInfo
from monatise.research.phase10.access import AnalysisRequest
from monatise.research.institutional.models import digest
from tests.research.phase9.test_pipeline import pipeline,add,trade,NOW_NS,NS


def test_first_fault_is_precise_preserved_and_not_an_automatic_reanchor():
    p,c=pipeline('ES');g=p.gates[c.metadata.instrument_id]
    policy=replace(g.policy,floor_ticks=3)
    g.schema_policies['trades']=policy
    guard=PriceGuard(c,policy,anchor='2500',anchor_ns=NOW_NS-54*NS,anchor_sha256=digest('anchor'))
    g.guards['trades']=guard
    assert not add(p,trade(c,price='2501.50'),ordinal=1)['accepted']
    f=dict(g.fault_details['trades']);assert f['excursion_ticks']=='6' and f['bound_ticks']=='3'
    assert f['policy_sha256']==policy.sha256 and g.quarantine[-1]['policy_sha256']==policy.sha256
    assert f['startup_anchor_bridge_review_required'] and not f['corrupt_exchange_record_proven']
    assert not guard.changes and guard.last==Decimal('2500')
    assert add(p,trade(c,price='2500',t=NOW_NS-NS//2),ordinal=2)['accepted']
    assert g.fault_details['trades']==f and g.faults['trades']
    report=FuturesMarketInfo(p,source_health=lambda now:{}).analyse(AnalysisRequest((c.metadata.raw_symbol,),NOW_NS))
    v=report['instruments'][c.metadata.raw_symbol]
    assert not v['components']['trade_features']['available']
    assert not v['validation']['thresholds_relaxed'] and not v['validation']['rejected_records_readmitted']


def test_reviewed_recovery_archives_prior_fault_details():
    p,c=pipeline();g=p.gates[c.metadata.instrument_id]
    assert not add(p,trade(c,price='250000'),ordinal=1)['accepted']
    prior=g.fault_details['trades']
    g.review_recovery('trades',anchor='2500',anchor_ns=NOW_NS-NS,anchor_sha256=digest('reviewed genuine anchor'),review_reference='EXPLICIT_ENGINEERING_REVIEW',expected_fault_sha256=digest(g.faults['trades']))
    assert 'trades' not in g.fault_details and g.reviews[-1]['prior_fault_detail']==prior
    assert len(g.quarantine)==1


def test_instrument_source_quarantine_does_not_erase_other_native_instrument():
    from monatise.research.phase9.pipeline import ResearchPipeline
    from tests.research.phase10.test_workflow import bar
    pg,gc=pipeline('GC');pe,es=pipeline('ES')
    p=ResearchPipeline({**pg.gates,**pe.gates},{**pg.calendars,**pe.calendars},enabled_schemas=pg.enabled_schemas)
    for i,c in enumerate((gc,es)):
        assert add(p,bar(c,NOW_NS//(60*NS)*60*NS-120*NS),'ohlcv-1m',i)['accepted']
        assert add(p,trade(c),ordinal=i+10)['accepted']
    h=dict(quarantined=True,reasons=[],component_rejections={'trades:'+str(gc.metadata.instrument_id):['native_record_or_recovery_validation_failed']})
    r=FuturesMarketInfo(p,source_health=lambda now:h).analyse(AnalysisRequest((gc.metadata.raw_symbol,es.metadata.raw_symbol),NOW_NS))
    a=r['instruments'][gc.metadata.raw_symbol];b=r['instruments'][es.metadata.raw_symbol]
    assert a['availability']=='UNAVAILABLE' and a['validation']['source_quarantine_scope']=='INSTRUMENT_SOURCE_QUARANTINE'
    assert b['availability']=='PARTIAL_MARKET_INFORMATION' and b['components']['trade_features']['available']
    assert b['capture_health']['quarantined']  # Original overall source evidence remains visible.
    h['reasons']=['capture_cancelled']
    global_failure=FuturesMarketInfo(p,source_health=lambda now:h).analyse(AnalysisRequest((es.metadata.raw_symbol,),NOW_NS))
    assert global_failure['instruments'][es.metadata.raw_symbol]['availability']=='UNAVAILABLE'
