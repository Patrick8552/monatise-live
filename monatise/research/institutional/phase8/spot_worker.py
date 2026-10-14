"""Frozen-engine subprocess: genuine chart diagnostics or existing broker replay.

No broker/source readiness is fabricated to force the canonical graph to pass.
"""
from dataclasses import replace
from datetime import datetime,UTC
from pathlib import Path
from types import SimpleNamespace
import json
from monatise.application.gold_analysis import GoldLayerEvaluator,GoldPolicy,sweep_reversal
from monatise.application.hierarchy.coordinator import TimeframeSnapshot,HierarchyConfiguration
from monatise.application.hierarchy.models import EvidenceIdentity,EvidenceContext,Provenance,StrategicState,DataQualityState,SetupState,TriggerState
from monatise.application.hierarchy.policy import SHARED_TIMEFRAME_POLICY as TF
from monatise.core.models import Candle
from monatise.engines.market_data.models import MarketSnapshot,DataQuality,DataStatus
from monatise.engines.fibonacci_liquidity import FibonacciLiquidityEngine,FibonacciRequest
from monatise.research.gold_fib.models import H1ParentSnapshot,encode
from monatise.research.gold_fib.episode import H1StructuralEpisodeAdapter,GoldH1StructuralLegSelector
from .spot import SpotObservationLedger,ObservedChartCandle,SECONDS
from . import SAFETY,BASIS_STATUS

def instant(ns):return datetime.fromtimestamp(ns/1e9,UTC)


class ChartGoldDiagnostics(GoldLayerEvaluator):
    def __init__(self):super().__init__(configuration=HierarchyConfiguration(strategy_version=GoldPolicy().strategy),asset_route='gold')
    def _market(self,snapshot):
        candles=tuple(Candle(r.open_time.isoformat(),r.open,r.high,r.low,r.close,volume=r.volume) for r in snapshot.candles)
        if not candles:return None
        latest=snapshot.latest_finalized
        return MarketSnapshot('XAU/USD',snapshot.timeframe,latest.close,candles,
            DataQuality(DataStatus.DEGRADED,'Safari TradingView FXCM',snapshot.observed_at,latest.scheduled_close_time,
                (snapshot.observed_at-latest.scheduled_close_time).total_seconds(),('BROKER_SESSION_UNVERIFIED','VOLUME_UNAVAILABLE','HISTORICAL_RECEIVE_TIMES_UNAVAILABLE')),
            metadata={'chart_price_only':True,'broker_certified':False})


def assess(request):
    if request.get('schema')=='gold-h1-fib-observation-archive-v1':
        from monatise.research.gold_fib.replay import OfflineReplay
        if request.get('evidence_kind') not in {'POINT_IN_TIME_ARCHIVE','ENGINEERING_SYNTHETIC'}:raise ValueError('explicit_broker_archive_evidence_kind_required')
        replay=OfflineReplay().run(request)
        return dict(schema='monatise-phase8-canonical-broker-replay-v1',canonical_frozen_offline_graph_invoked=True,
            evidence_kind=request['evidence_kind'],genuine_input_certificate=False,provenance_certificate='DECLARED_ARCHIVE_KIND_IS_NOT_INDEPENDENT_SOURCE_AUTHENTICATION',
            frozen_replay=replay.data,basis_status=BASIS_STATUS,**SAFETY)
    if request.get('schema')!='monatise-phase8-spot-observations-v1':raise ValueError('explicit_spot_observation_archive_required')
    ledger=SpotObservationLedger()
    if not 1<=len(request['observations'])<=48:raise ValueError('bounded_observation_archive_required')
    for obs in request['observations']:ledger.observe(obs)
    cutoff=ledger.last_receipt;now=instant(cutoff);evaluator=ChartGoldDiagnostics();layers={};frames={};missing=[]
    provenance=Provenance('Safari TradingView FXCM','FXCM','FX:XAUUSD','CSV UTC UNIX verified','chart-observation-not-broker-session-certificate')
    for tf in ('4h','1h','15m','5m','1m'):
        raw=ledger.finalized(tf,cutoff_ns=cutoff)[-evaluator.configuration.candle_limit:]
        if len(raw)<50:missing.append(tf);continue
        frame_now=now
        if tf=='1h':
            frozen=ledger.h1_freezes[(raw[-1]['open_ns'],raw[-1]['content_hash'])]
            raw=frozen['rows'][-evaluator.configuration.candle_limit:];frame_now=instant(frozen['cutoff_ns'])
        normalized=tuple(ObservedChartCandle(r['content_hash'],'XAU/USD',tf,instant(r['open_ns']),instant(r['close_ns']),
            instant(r['open_ns']),instant(r['final_known_ns']),r['open'],r['high'],r['low'],r['close'],r.get('volume'),
            True,r['content_hash'],provenance) for r in raw)
        frame=TimeframeSnapshot('XAU/USD',tf,frame_now,normalized,normalized[-1]);frames[tf]=frame
        layers[tf]=evaluator._analyse_structure(frame,None)
    result=dict(schema='monatise-phase8-frozen-spot-diagnostics-v1',cutoff_ns=cutoff,ledger=ledger.report(),
        canonical_frozen_offline_graph_invoked=False,canonical_Gold_layer_components_invoked=True,
        evidence_kind='AUTHENTIC_CHART_OBSERVATIONS_NOT_BROKER_POINT_IN_TIME_ARCHIVE',
        missing_timeframes=missing,layer_diagnostics=encode(layers),H1_parent=None,episode=None,anchor=None,fibonacci=None,
        M15_pattern=None,M5_confirmed=False,M1_trigger_qualified=False,
        raw_fib_candidates=[],qualified_targets=[],entry=None,stop=None,grid='UNAVAILABLE',decision='NO-TRADE',
        technical_certificate='UNQUALIFIED',basis_status=BASIS_STATUS,
        blockers=['Authenticated_broker_session_and_units_unavailable','Chart_volume_and_original_historical_receive_times_unavailable'],**SAFETY)
    if '1h' not in layers:return result
    layer=layers['1h'];frame=frames['1h'];bar=frame.latest_finalized
    side='long' if layer.structure.bias.value=='bullish' else 'short' if layer.structure.bias.value=='bearish' else 'none'
    state=StrategicState.LONG_ONLY if side=='long' else StrategicState.SHORT_ONLY if side=='short' else StrategicState.NEUTRAL
    identity=EvidenceIdentity.create(kind='phase8-chart-H1-diagnostic',symbol='XAU/USD',timeframe='1h',
        candle_id=bar.candle_id,parent_id=None,strategy_version=GoldPolicy().strategy)
    expiry=bar.scheduled_close_time+TF.analysis_lifetime
    if now>=expiry:
        result['H1_parent']=dict(original_close=bar.scheduled_close_time.isoformat(),expiry=expiry.isoformat(),expired=True,canonical_parent_qualified=False)
        result['blockers'].append('H1_PARENT_EXPIRED');return result
    if any(r['timeframe']=='1h' and r['known_ns']>int(frame.observed_at.timestamp()*10**9) and r['open_ns']<=int(bar.open_time.timestamp()*10**9) for r in ledger.revisions):
        result['blockers'].append('H1_REVISION_INVALIDATED_FROZEN_PARENT');return result
    context=EvidenceContext(identity,bar.open_time,bar.scheduled_close_time,frame.observed_at,expiry,state,side,layer.structure.confidence,
        DataQualityState.DEGRADED,provenance,{'scope':'CHART_DIAGNOSTIC_NOT_QUALIFIED_CANONICAL_PARENT'})
    parent=H1ParentSnapshot.capture(context,frame,layer)
    episode=H1StructuralEpisodeAdapter().assess(parent);anchor=GoldH1StructuralLegSelector().select(parent,episode)
    result.update(H1_parent=dict(context=encode(context),snapshot_hash=parent.record.sha256,
        original_close=bar.scheduled_close_time.isoformat(),expiry=expiry.isoformat(),expiry_renewed=False,
        expired=now>=expiry,canonical_parent_qualified=False),episode=episode.record.data,anchor=anchor.record.data)
    active=episode.record.data.get('active') or {}
    result['H1_episode_audit']=dict(symbol='XAU/USD',source='Safari TradingView FX:XAUUSD / FXCM',timeframe='1h',
        direction=side,parent_context=encode(context),snapshot_hash=parent.record.sha256,
        structural_event=active.get('event'),broken_pivot_id=active.get('broken_pivot_id'),
        origin_anchor=anchor.record.data.get('A'),terminal_anchor=anchor.record.data.get('B'),
        event_known_at=active.get('event_known_at'),origin_known_at=active.get('origin_known_at'),
        expiry=expiry.isoformat(),invalidation=episode.record.data.get('reason'),
        provenance=encode(provenance),canonical_qualified_episode=False)
    if now>=expiry:result['blockers'].append('H1_PARENT_EXPIRED')
    if anchor.constraint:
        request=FibonacciRequest(layer.market,layer.structure,layer.liquidity,layer.zones,layer.reclaim,
            extension_ratios=(1.272,1.414,1.618),anchor_constraint=anchor.constraint)
        fib=FibonacciLiquidityEngine().assess(request);result['fibonacci']=encode(fib)
        result['blockers'].append('RAW_FIB_DOES_NOT_CREATE_EXECUTABLE_TARGET')
    else:result['blockers'].append('H1_ANCHOR_REJECTED:'+str(anchor.record.data['reason']))
    if '15m' in layers:
        result['M15_pattern']=sweep_reversal(layers['15m'].market.candles,side,'15m')
        setup_state,setup_side=evaluator._setup_state(layers['15m'],state)
        result['M15_setup_state']=encode((setup_state,setup_side))
        result['M5_confirmation_state']='NOT_EVALUATED_NO_CONFIRMED_M15_SETUP'
        if setup_state is SetupState.SETUP_CONFIRMED and '5m' in layers:
            try:
                setup=evaluator._context('setup',frames['15m'],context,setup_state,setup_side,layers['15m'].structure.confidence,now,TF.setup_lifetime,evaluator._layer_evidence(layers['15m']))
                setup=replace(setup,data_quality=DataQualityState.DEGRADED)
                evaluator._state['XAU/USD']=SimpleNamespace(setup_context=setup)
                trigger=evaluator._trigger_state(layers['5m'],setup_side)
                result['M5_confirmation_state']=encode(trigger);result['M5_confirmed']=trigger is TriggerState.TRIGGER_CONFIRMED
            except ValueError as exc:result['M5_confirmation_state']=str(exc)
    if '1m' in layers:
        result['M1_observation']=dict(structure=encode(layers['1m'].structure),reclaim=encode(layers['1m'].reclaim),zones=encode(layers['1m'].zones),broker_entry_validation='UNAVAILABLE')
    result['blockers'].append('Complete_aligned_M15_M5_M1_qualification_unavailable')
    return result


def main(input_path,output_path):
    data=assess(json.loads(Path(input_path).read_text()))
    with Path(output_path).open('x') as f:json.dump(data,f,sort_keys=True,indent=2,allow_nan=False)
