"""Frozen-manifest replay. Each stream has isolated mutable decision/outcome state."""
from collections import Counter
from dataclasses import replace
from pathlib import Path
import json
from .models import WIDTHS, encode, digest
from .service import DecisionService
from .store import Store
from .outcomes import ShadowOutcomes,performance


def cutoffs(archive):
    if archive.mode=='AS_RECORDED':
        # Genuine capture/admission observations, not fabricated prior live cycles.
        return sorted({b.available_ns for b in archive.bars}|{c.available_ns for c in archive.coverage})
    return sorted({b.available_ns for b in archive.bars if b.close_ns%WIDTHS['5m']==0})


def run_replay(archive,policy,database,*,experiment='unified',pathways=('A','B','C'),
               start_ns=None,end_ns=None,split_ns=None,progress=None):
    store=Store(database)
    engine=DecisionService(store,policy,stream=experiment,pathways=pathways)
    outcomes=ShadowOutcomes(store,experiment,policy)
    totals=Counter();reasons=Counter();candidate_reasons=Counter();examples=[];decisions=[]
    try:
        times=[t for t in cutoffs(archive) if (start_ns is None or t>=start_ns) and (end_ns is None or t<=end_ns)]
        for i,t in enumerate(times):
            if t<archive.definition_available_ns:continue
            snapshot=archive.snapshot(t)
            outcomes.advance(snapshot)
            decision=engine.evaluate(snapshot,str(t))
            totals[decision['trade_action']]+=1;reasons[decision['reason']]+=1
            for c in decision['candidate_audit']:
                if c['stage']=='TRIGGERED':candidate_reasons.update(c['reasons'])
            if len(examples)<3 and decision['trade_action']!='NO_TRADE':examples.append(decision)
            decisions.append({'cutoff_ns':t,'decision_id':decision['decision_id'],
                              'action':decision['trade_action'],'reason':decision['reason'],
                              'opportunity_id':decision['selected_opportunity_id'],
                              'selection_event_id':decision['selection_event_id'],
                              'is_new_selection':decision['is_new_selection']})
            if progress and i%100==0:progress({'experiment':experiment,'cycles':i+1,'total':len(times)})
        if times:outcomes.advance(archive.snapshot(times[-1]))
        phases={}
        if split_ns is not None:
            for name,predicate in [('development',lambda t:t<split_ns),('retrospective_chronological_holdout',lambda t:t>=split_ns)]:
                phase=[d for d in decisions if predicate(d['cutoff_ns'])]
                phases[name]={'cycles':len(phase),'actions':dict(Counter(d['action'] for d in phase)),
                             'new_selections':sum(d['is_new_selection'] for d in phase)}
        market_count=store.db.execute('SELECT COUNT(*) FROM market_opportunities').fetchone()[0]
        classification_count=store.db.execute('SELECT COUNT(*) FROM classifications WHERE stream=?',(experiment,)).fetchone()[0]
        return encode({'experiment':experiment,'pathways':pathways,'policy_hash':policy.hash,
                       'manifest_hash':archive.manifest_hash,'archive':archive.report,
                       'cycles':len(decisions),'actions':dict(totals),'reason_counts':dict(reasons),
                       'triggered_candidate_rejections':dict(candidate_reasons),
                       'canonical_market_opportunities':market_count,'classification_records':classification_count,
                       'decision_sequence_hash':digest(decisions),'decisions':decisions,
                       'performance':performance(store,experiment),'phase_counts':phases,
                       'examples':examples,'last_decision':decision if decisions else None,
                       'validation_status':'EXPLORATORY_REPLAY_NOT_PROFITABILITY_VALIDATION',
                       'out_of_sample_status':'NOT_UNTOUCHED_ALREADY_INSPECTED_DATA',
                       'forward_shadow_status':'NOT_RUN_NO_FUTURE_CAPTURE_ACQUIRED',
                       'mode':'SHADOW','execution_eligible':False})
    finally:store.close()


def run_comparison(archive, policies, database, *, split_ns, progress=None,start_ns=None,end_ns=None):
    """Share only immutable feature work. Mutable streams remain independent."""
    from .evidence import EvidenceCache
    from . import CODE_HASH, BASE_COMMIT
    shared=EvidenceCache();store=Store(database)
    engines={};evaluators={};stats={};sequences={};examples={}
    definitions=[('A-only',('A',),'DOMINANCE'),('B-only',('B',),'DOMINANCE'),
                 ('C-only',('C',),'DOMINANCE'),('unified',('A','B','C'),'DOMINANCE'),
                 ('earliest-baseline',('A','B','C'),'EARLIEST_BASELINE')]
    for variant,policy in policies.items():
        for name,pathways,arbitration_mode in definitions:
            # The full baseline/pathway comparison uses the registered bar
            # participation variant. The stricter flow variant gets its own
            # unified stream; missing executions are never substituted.
            if variant!='bar-participation' and name!='unified':continue
            stream=variant+':'+name
            engines[stream]=DecisionService(store,policy,stream=stream,pathways=pathways,
                                           evidence_cache=shared,arbitration_mode=arbitration_mode)
            evaluators[stream]=ShadowOutcomes(store,stream,policy)
            stats[stream]={'actions':Counter(),'reasons':Counter(),'triggered_rejections':Counter(),
                           'phase_actions':{'development':Counter(),'holdout':Counter()}}
            sequences[stream]=[];examples[stream]=[]
    times=[t for t in cutoffs(archive) if t>=archive.definition_available_ns
           and (start_ns is None or t>=start_ns) and (end_ns is None or t<=end_ns)]
    last={}
    try:
        for i,t in enumerate(times):
            snap=archive.snapshot(t)
            for stream,engine in engines.items():
                evaluators[stream].advance(snap)
                result=engine.evaluate(snap,str(t));last[stream]=result
                x=stats[stream];x['actions'][result['trade_action']]+=1;x['reasons'][result['reason']]+=1
                phase='development' if t<split_ns else 'holdout';x['phase_actions'][phase][result['trade_action']]+=1
                for c in result['candidate_audit']:
                    if c['stage']=='TRIGGERED':x['triggered_rejections'].update(c['reasons'])
                sequences[stream].append({'cycle':str(t),'decision_id':result['decision_id'],'action':result['trade_action'],
                                          'reason':result['reason'],'selection':result['selection_event_id'],
                                          'new_selection':result['is_new_selection']})
                if result['is_new_selection'] and len(examples[stream])<3:examples[stream].append(result)
            if progress and i%100==0:progress({'product':archive.instrument.symbol,'cycle':i+1,'total':len(times),'streams':len(engines)})
        streams={}
        for stream in engines:
            if times:evaluators[stream].advance(archive.snapshot(times[-1]))
            x=stats[stream]
            streams[stream]={'cycles':len(sequences[stream]),'actions':dict(x['actions']),
                             'reasons':dict(x['reasons']),'triggered_candidate_rejections':dict(x['triggered_rejections']),
                             'phase_actions':{k:dict(v) for k,v in x['phase_actions'].items()},
                             'performance_all':performance(store,stream),
                             'performance_development':performance(store,stream,selected_to=split_ns),
                             'performance_retrospective_holdout':performance(store,stream,selected_from=split_ns),
                             'decision_sequence_hash':digest(sequences[stream]),
                             'examples':examples[stream],'last_decision':last.get(stream)}
        return encode({'schema':'unified-comparison-v1','base_commit':BASE_COMMIT,'code_hash':CODE_HASH,
                       'archive':archive.report,'split_ns':split_ns,'evaluation_window':{'start_ns':start_ns,'end_ns':end_ns},'policies':policies,'streams':streams,
                       'baseline':'earliest still-eligible trigger, same gates and exposures; conflicts/ties abstain',
                       'out_of_sample_status':'RETROSPECTIVE_CHRONOLOGICAL_HOLDOUT_NOT_UNTOUCHED',
                       'forward_shadow_status':'NOT_RUN_NO_FUTURE_CAPTURE_ACQUIRED',
                       'profitability_validated':False,'mode':'SHADOW','execution_eligible':False})
    finally:store.close()
