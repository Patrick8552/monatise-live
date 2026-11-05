"""BTC-only native analysis and local shadow decisions, with independent gate attribution."""
import json
from dataclasses import replace
from decimal import Decimal as D
from monatise.research.unified.models import (Candidate,State,current_quote,digest,encode,canonical,identity,fixed_decimal)
from monatise.research.unified.evidence import build_frames
from monatise.research.unified.diagnostics import describe
from monatise.research.unified.arbitration import arbitrate
from monatise.research.unified.eligibility import final_revalidate
from monatise.research.unified.outcomes import ShadowOutcomes
from monatise.research.unified.store import Conflict
from . import VERSION,code_hash,require_btc
from .news import NewsReview
from .risk import ledger_state,gates as risk_gates
from .regime import classify,confirm
from .setups import trend_observations,range_observations,inspect
from .analysis import reference_analysis,intraday_regime

class BTCService:
    def __init__(self,store,policy,*,stream,series_id):
        if not stream or not series_id:raise ValueError('EXPLICIT_BTC_STREAM_AND_SOURCE_SERIES_REQUIRED')
        self.store,self.policy,self.stream,self.series_id=store,policy,stream,series_id
        store.db.execute('CREATE TABLE IF NOT EXISTS btc_regimes(stream TEXT,contract TEXT,body TEXT NOT NULL,PRIMARY KEY(stream,contract))')
    @fixed_decimal
    def evaluate(self,snapshot,cycle,*,news_review=None,manual_pause=False):
        require_btc(snapshot)
        if type(manual_pause) is not bool:raise ValueError('BOOLEAN_MANUAL_PAUSE_REQUIRED')
        review=news_review or NewsReview();news=review.status(snapshot.cutoff_ns)
        # A manifest boolean is not trusted as reviewed calendar coverage.
        events=tuple({digest(n):n for n in snapshot.news+news['events']}.values())
        snap=replace(snapshot,news_coverage=news['available'],news=events)
        frames=build_frames(snap,self.policy.trend)
        conf=digest({'version':VERSION,'code_hash':code_hash(),'policy':self.policy,'series':self.series_id})
        inp=digest({'snapshot':snap.hash,'news_review':review,'configuration':conf,'manual_pause':manual_pause})
        st=self.store;stream=self.stream
        with st.transaction():
            # Stable reviewed series permits append-only captures; exact snapshot/manifest remain in every decision.
            st.bind(stream,conf,digest({'series':self.series_id,'contract':snap.instrument.key}))
            cached=st.cached(stream,snap.instrument.key,cycle,inp)
            if cached is not None:return cached
            st.check_cutoff(stream,snap.instrument.key,snap.cutoff_ns)
            ShadowOutcomes(st,stream,self.policy.trend).advance(snap)
            saved=st.db.execute('SELECT body FROM btc_regimes WHERE stream=? AND contract=?',(stream,snap.instrument.key)).fetchone()
            prior=json.loads(saved['body']) if saved else None
            raw=classify(snap,frames,self.policy.regime);regime=confirm(raw,prior,self.policy.regime.confirmation_closes)
            # Freeze an admitted range. Drifting bounds cannot chase losses.
            if regime['regime']=='RANGE':
                old=prior.get('box') if prior and prior.get('regime')=='RANGE' else None
                box=old or raw.get('range_box')
                latest=frames['5m'].bars[-1]
                buffer=snap.instrument.tick*self.policy.risk.range_stop_buffer_ticks
                broken=bool(box and any(b.low<=D(box['lower'])-buffer or b.high>=D(box['upper'])+buffer for b in frames['5m'].bars if b.open_ns>=box['formed_ns']))
                if box and (broken or not D(box['lower'])<=latest.close<=D(box['upper'])):
                    regime.update(regime='TRANSITION',reason='FROZEN_RANGE_BROKEN',box=None,candidate='BROKEN_RANGE',count=0)
                else:regime['box']=box
            box=regime.get('box') or raw.get('range_box')
            found=trend_observations(snap,self.policy.trend,frames)
            if box:found+=range_observations(snap,frames,self.policy,box)
            checks=[inspect(o,snap,self.policy,frames,regime,box) for o in found]
            risk_state=ledger_state(st,stream,snap.instrument.key,snap.cutoff_ns)
            risk=risk_gates(risk_state,self.policy.risk,manual_pause=manual_pause)
            source=[];q=current_quote(snap)
            if snap.quality:source.append('SOURCE_QUALITY_UNRESOLVED')
            if snap.cutoff_ns>=snap.instrument.expiry_ns:source.append('CONTRACT_EXPIRED')
            if not snap.schedule.contains(snap.cutoff_ns,snap.cutoff_ns+1):source.append('OUTSIDE_REVIEWED_TRADING_SESSION')
            if q is None or q.quality:source.append('ENTRY_QUOTE_UNAVAILABLE')
            elif q.source.startswith('MODELED_SPREAD_FROM_NATIVE_CLOSE'):source.append('OBSERVED_NATIVE_QUOTE_REQUIRED')
            elif snap.cutoff_ns-q.receive_ns>self.policy.trend.quote_age_ns:source.append('ENTRY_QUOTE_STALE')
            candidates=[];audits=[]
            for row in checks:
                o=row['observation'];plan=row['plan'];g=row['gates']
                crisk=risk_gates(risk_state,self.policy.risk,plan,manual_pause)
                reasons=source+news['reasons']+crisk['reasons']+[v for values in g.values() for v in values]
                if st.status(stream,o.opportunity_id) in ('INVALIDATED','EXPIRED','SUPERSEDED'):reasons+=['PERSISTED_TERMINAL_STATE']
                old=st.selected(stream,o.opportunity_id) if o.opportunity_id else None
                if old and st.selection_completed(stream,old['selection']):reasons+=['SELECTED_OPPORTUNITY_ALREADY_COMPLETED']
                if plan and st.exposure_conflict(stream,snap.instrument.key,o.opportunity_id,snap.cutoff_ns):reasons+=['SHADOW_EXPOSURE_RESTRICTION']
                c=Candidate(o,plan,tuple(sorted(set(reasons))),row['context_category']);candidates.append(c)
                st.record_observation(stream,o,snap.cutoff_ns,qualified=c.eligible)
                audits.append({'opportunity_id':o.opportunity_id,'observation_id':o.key,'pathway':o.pathway,'side':o.side,'stage':o.stage,
                    'eligible':c.eligible,'gate_groups':{**g,'source':source,'news':news['reasons'],'risk':crisk['reasons']},
                    'reasons':c.reasons,'market_trigger_ns':o.trigger.at_ns if o.trigger else None,
                    'trigger_available_ns':o.trigger.available_ns if o.trigger else None,
                    'economic_status':'NOT_EVALUATED_SOURCE_QUALITY' if snap.quality else 'PASSED' if plan else 'FAILED' if g['economics'] else 'NOT_EVALUATED_NO_CURRENT_TRIGGER',
                    'tested_net_rr':plan.net_rr if plan else None,'hypothetical_plan':encode(plan) if plan else None,'hypothetical_removed_rule_profitability':'NOT_OBSERVED'})
            st.expire(stream,snap.instrument.key,snap.cutoff_ns)
            selected,reason,arb=arbitrate(candidates);final=[];sid=None;new=False;plan=None
            if selected:
                final=list(final_revalidate(selected.plan,snap,self.policy.trend))
                if final:selected=None;reason='FINAL_REVALIDATION_FAILED'
            if selected:
                sid,new,plan=st.claim(stream,selected,snap.cutoff_ns,conf,snap.hash,selected.observation.pathway,policy=self.policy.trend)
                # Preserve the full upgrade policy alongside the original frozen execution-cost policy in decision provenance.
            if not selected:
                if source:reason='SOURCE_NOT_READY'
                elif news['reasons']:reason='NEWS_PERMISSION_NOT_READY'
                elif risk['reasons']:reason='RISK_PAUSED'
                elif regime['regime']=='UNKNOWN':reason='CONTEXT_UNKNOWN'
                elif regime['regime']=='TRANSITION':reason='REGIME_TRANSITION'
            analysis=reference_analysis(snap,frames,self.policy,checks,news,risk,regime)
            analysis['regime']=intraday_regime(frames,self.policy)
            analysis['quote_freshness_policy']={'conditional_analysis_limit_seconds':str(D(self.policy.analysis_quote_age_ns)/10**9),'entry_limit_seconds':str(D(self.policy.trend.quote_age_ns)/10**9)}
            frame_health={tf:{'data_available':bool(f.bars),'validated_bars':len(f.bars),'confirmed_highs':sum(p.kind=='HIGH' for p in f.pivots),'confirmed_lows':sum(p.kind=='LOW' for p in f.pivots),'structure_state':f.state,'reason':'CONFIRMED_SWING_SEQUENCE_INCOMPLETE' if f.bars and f.state==State.UNAVAILABLE else 'NO_VALIDATED_BARS' if not f.bars else None} for tf,f in frames.items()}
            # Risk pauses do not erase reference evidence, but permission is always separate.
            result=encode({'schema_version':VERSION,'decision_id':identity('btc-decision',stream,snap.instrument.key,cycle,inp),
                'cutoff_ns':snap.cutoff_ns,'instrument':snap.instrument,'manifest_hash':snap.manifest_hash,'snapshot_hash':snap.hash,
                'code_hash':code_hash(),'policy_hash':self.policy.hash,'full_upgrade_policy':self.policy,
                'price_label':'CME FUTURES REFERENCE PRICES','analysis':analysis,'analysis_action':analysis['action'],'preferred_reference_setup':analysis['plan'],'trade_action':selected.observation.side if selected else 'NO_TRADE',
                'reason':reason,'selected_plan':plan,'selection_event_id':sid,'is_new_selection':new,'regime':regime,
                'readiness':{'source':{'available':not source,'reasons':source},
                    'context':{'available':regime['regime']!='UNKNOWN','frame_states':{tf:f.state for tf,f in frames.items()},'frame_health':frame_health},
                    'news':{k:v for k,v in news.items() if k!='events'},'risk':risk,
                    'trigger':{'current_trigger_classifications':sum(o.stage=='TRIGGERED' for o in found),'classifications':len(found)}},
                'candidate_audit':audits,'arbitration_audit':arb,'final_revalidation_reasons':final,
                'evidence_summary':describe(snap,frames),'risk_scope':'LOCAL_SHADOW_REFERENCE_ONE_STANDARD_CME_CONTRACT_NO_CFD_SIZING',
                'cost_basis':self.policy.cost_basis,'mode':'SHADOW','execution_eligible':False,'orders_created':0})
            st.db.execute('INSERT INTO btc_regimes VALUES(?,?,?) ON CONFLICT(stream,contract) DO UPDATE SET body=excluded.body',(stream,snap.instrument.key,canonical(regime)))
            st.commit_decision(stream,snap.instrument.key,cycle,inp,snap.cutoff_ns,result)
            return result
