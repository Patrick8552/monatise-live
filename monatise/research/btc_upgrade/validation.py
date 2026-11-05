"""Source-bound chronological validation and honest counterfactual attribution."""
from collections import Counter
from pathlib import Path
from decimal import Decimal as D
import json,time
from monatise.research.unified.models import encode,digest,current_quote,QuoteUnavailable
from monatise.research.unified.outcomes import performance,ShadowOutcomes
from monatise.research.unified.store import Store
from .service import BTCService
from .news import NewsReview
from . import require_btc,code_hash

def observe_rejected_plan(plan,selected_ns,snapshot,policy):
    """Hypothetical next-L1 entry/outcome; unavailable intervals never become wins."""
    d=D(1 if plan['side']=='BUY' else -1);inst=snapshot.instrument;slip=policy.slippage_ticks_per_side*inst.tick
    fee=policy.fee_ticks_per_side*inst.tick*inst.multiplier;fill=None
    events=sorted(snapshot.quotes+snapshot.quote_invalidations,key=lambda q:(q.available_ns,q.receive_ns,q.sequence or -1,q.native_ordinal or -1))
    for q in events:
        if q.available_ns<=selected_ns or q.receive_ns<=selected_ns:continue
        covered=any(c.kind=='mbp-1' and c.covers(selected_ns,q.receive_ns+1,snapshot.cutoff_ns) for c in snapshot.coverage)
        if isinstance(q,QuoteUnavailable) or q.quality or not covered:
            if fill is not None:return {'status':'UNRESOLVED','reason':'L1_COVERAGE_OR_QUOTE_FAILURE','hypothetical':True}
            continue
        if not 0<=q.available_ns-q.receive_ns<=policy.quote_age_ns:continue
        if fill is None:
            if q.available_ns>=plan['expires_ns']:break
            px=(q.ask if d>0 else q.bid)+d*slip
            if D(plan['entry_low'])<=px<=D(plan['entry_high']):fill=(px,q.available_ns)
            continue
        market=q.bid if d>0 else q.ask;stop=D(plan['stop']);target=D(plan['targets'][0]['price'])
        if d*(market-stop)<=0 or d*(market-target)>=inst.tick:
            stopped=d*(market-stop)<=0;exit=(market if stopped else target)-d*slip
            pnl=d*(exit-fill[0])*inst.multiplier-2*fee
            return {'status':'RESOLVED','hypothetical_net_pnl':str(pnl),'exit_ns':q.available_ns,'stop':stopped,'hypothetical':True,'broker_performance':False}
    return {'status':'OPEN_CENSORED' if fill else 'NO_OBSERVED_FILL','hypothetical':True}

def replay(archive,policy,database,*,stream,series_id,cutoffs,split_ns,freeze_ns,sample_status='RETROSPECTIVE_ALREADY_INSPECTED',news_review=None,progress=None,freeze_receipt=None):
    if archive.instrument.product!='BTC':raise ValueError('BTC_NATIVE_FUTURES_ONLY')
    times=tuple(cutoffs)
    if not times or times!=tuple(sorted(set(times))) or split_ns<=times[0] or split_ns>times[-1]:raise ValueError('BOUNDED_ORDERED_CHRONOLOGICAL_SPLIT_REQUIRED')
    if sample_status not in ('RETROSPECTIVE_ALREADY_INSPECTED','PREREGISTERED_UNSEEN_FORWARD'):raise ValueError('EXPLICIT_SAMPLE_STATUS_REQUIRED')
    if sample_status=='PREREGISTERED_UNSEEN_FORWARD':
        if not freeze_receipt:raise ValueError('PREREGISTERED_SOURCE_BOUND_FREEZE_RECEIPT_REQUIRED')
        receipt=json.loads(Path(freeze_receipt).read_text())
        if receipt.get('code_hash')!=code_hash() or receipt.get('policy_hash')!=policy.hash or receipt.get('observed_ns')!=freeze_ns or receipt.get('forward_start_ns')!=split_ns:
            raise ValueError('FORWARD_FREEZE_CODE_POLICY_OR_CLOCK_MISMATCH')
        if freeze_ns>=split_ns or archive.mode!='AS_RECORDED':raise ValueError('CAUSAL_AS_RECORDED_FORWARD_EVIDENCE_REQUIRED')
        captures=[json.loads((Path(c['capture'])/'receipt.json').read_text()) for c in archive.report['capture_reconciliation']]
        if not any(freeze_ns<=c['started_ns']<split_ns<=times[-1]<=c['ended_ns'] for c in captures):raise ValueError('NEW_POST_FREEZE_NATIVE_CAPTURE_REQUIRED')
    if Path(database).exists():raise ValueError('NEW_REPLAY_LEDGER_REQUIRED')
    store=Store(database);engine=BTCService(store,policy,stream=stream,series_id=series_id);actions=Counter();regimes=Counter();gateepisodes={};decisions=[];rejected={}
    try:
        for i,t in enumerate(times):
            snap=archive.snapshot(t);require_btc(snap);r=engine.evaluate(snap,str(t),news_review=news_review or NewsReview())
            actions[r['trade_action']]+=1;regimes[r['regime']['regime']]+=1;decisions.append({'cutoff':t,'id':r['decision_id'],'action':r['trade_action'],'analysis_action':r['analysis']['action']})
            for c in r['candidate_audit']:
                oid=c['opportunity_id'] or c['observation_id']
                for g,values in c['gate_groups'].items():
                    for reason in values:gateepisodes.setdefault((g,reason),set()).add(oid)
                if c['stage']=='TRIGGERED' and not c['eligible'] and c['hypothetical_plan']:
                    # Keep the first causally observed plan, not a later better-looking revision.
                    rejected.setdefault(oid,{'plan':c['hypothetical_plan'],'selected_ns':t,'reasons':c['reasons']})
            if progress and i%100==0:progress({'cycle':i+1,'total':len(times)})
        last=archive.snapshot(times[-1]);ShadowOutcomes(store,stream,policy.trend).advance(last)
        counterfactual=[]
        for oid,r in rejected.items():counterfactual.append({'opportunity_id':oid,'reasons':r['reasons'],'outcome':observe_rejected_plan(r['plan'],r['selected_ns'],last,policy.trend)})
        return encode({'schema':'btc-upgrade-validation-v1','policy_hash':policy.hash,'code_hash':code_hash(),
            'cycles':len(times),'actions':dict(actions),'regime_counts':dict(regimes),'decision_sequence_hash':digest(decisions),
            'split_ns':split_ns,'freeze_ns':freeze_ns,'sample_status':sample_status,
            'gate_attribution_unique_episodes':[{'group':g,'reason':r,'episodes':len(ids)} for (g,r),ids in sorted(gateepisodes.items())],
            'rejected_plan_followthrough':counterfactual,
            'performance_all':performance(store,stream),'performance_before_split':performance(store,stream,selected_to=split_ns),
            'performance_after_split':performance(store,stream,selected_from=split_ns),
            'out_of_sample_claim':sample_status=='PREREGISTERED_UNSEEN_FORWARD',
            'profitability_validated':False,'broker_costs_verified':policy.cost_basis=='VERIFIED_BROKER_COSTS',
            'execution_eligible':False,'orders_created':0,
            'limitations':['A retrospective split is not untouched out-of-sample testing.','Rejected-plan outcomes are hypothetical next-L1 observations, not proof that removing a rule improves portfolio performance.','Censored/unresolved outcomes are not counted as profitable.','No broker/CFD conversion or live execution.']})
    finally:store.close()


def freeze_policy(policy,path,*,forward_start_ns):
    now=time.time_ns()
    if forward_start_ns<=now:raise ValueError('FUTURE_FORWARD_BOUNDARY_REQUIRED')
    receipt={'schema':'btc-forward-freeze-v1','code_hash':code_hash(),'policy_hash':policy.hash,'observed_ns':now,'forward_start_ns':forward_start_ns,'parameters_tuned_on_future_data':False}
    with Path(path).open('x') as f:json.dump(receipt,f,indent=2)
    return receipt
