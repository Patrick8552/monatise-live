"""Causal chart observation ledger, explicitly distinct from broker certification."""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
import hashlib,json

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

SECONDS={'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400}


class SpotObservationLedger:
    def __init__(self):self.rows={};self.last_receipt=0;self.revisions=[];self.observations=[];self.h1_freezes={}

    def observe(self, observation):
        tf=observation['timeframe'];at=observation['received_ns'];raw=observation['candles']
        if (observation['symbol']!='FX:XAUUSD' or observation['provider']!='FXCM' or tf not in SECONDS
                or type(at) is not int or at<=self.last_receipt or not observation.get('UTC_bar_export_verified')
                or not 50<=len(raw)<=5000 or len(observation.get('source_sha256',''))!=64):
            raise ValueError('bounded_ordered_verified_FXCM_chart_observation_required')
        times=[r['open_ns'] for r in raw];step=SECONDS[tf]*10**9
        if times!=sorted(set(times)) or Counter(b-a for a,b in zip(times,times[1:])).most_common(1)[0][0]!=step:
            raise ValueError('declared_timeframe_cadence_mismatch')
        for r in raw:
            values=[r[k] for k in ('open','high','low','close')]
            if (not all(type(v) in (int,float) and isfinite(v) and v>0 for v in values)
                    or not r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high']
                    or r.get('volume') is not None and (not isfinite(r['volume']) or r['volume']<0)):
                raise ValueError('invalid_original_OHLC_or_volume')
            if r['open_ns']+step>at:continue
            key=(tf,r['open_ns']);content=digest({k:r.get(k) for k in ('open_ns','open','high','low','close','volume')})
            previous=self.rows.get(key)
            if previous and previous['content_hash']!=content:
                self.revisions.append(dict(timeframe=tf,open_ns=r['open_ns'],previous_hash=previous['content_hash'],new_hash=content,known_ns=at))
                previous=None
            if previous:
                previous['observation_count']+=1;previous['source_hashes'].append(observation['source_sha256'])
                if previous['final_known_ns'] is None:previous['final_known_ns']=at
            else:
                self.rows[key]=dict(**r,timeframe=tf,close_ns=r['open_ns']+step,first_observed_ns=at,final_known_ns=None,
                    observation_count=1,content_hash=content,source_hashes=[observation['source_sha256']],
                    original_candle_receive_ns=None,source='Safari TradingView FXCM chart',broker_certified=False)
        self.last_receipt=at;self.observations.append(dict(timeframe=tf,received_ns=at,source_sha256=observation['source_sha256']))
        if tf=='1h':
            finalized=self.finalized(tf,cutoff_ns=at)
            if len(finalized)>=50:
                last=finalized[-1];key=(last['open_ns'],last['content_hash'])
                self.h1_freezes.setdefault(key,dict(cutoff_ns=at,rows=deepcopy(finalized)))

    def finalized(self,tf,*,cutoff_ns):
        return tuple(deepcopy(v) for k,v in sorted(self.rows.items()) if k[0]==tf and v['final_known_ns'] is not None and v['final_known_ns']<=cutoff_ns)

    def report(self):
        return dict(observations=self.observations,revisions=self.revisions,finalized_counts={tf:len(self.finalized(tf,cutoff_ns=self.last_receipt)) for tf in SECONDS},
            original_historical_availability_certified=False,no_close_time_assigned_as_receive_time=True,
            broker_certified=False,volume_missing_preserved=True,input_sha256=digest(self.observations))


@dataclass(frozen=True)
class ObservedChartCandle:
    """Price-only diagnostic row; never masquerades as broker NormalizedCandle."""
    candle_id:str
    symbol:str
    timeframe:str
    open_time:object
    scheduled_close_time:object
    provider_timestamp:object
    received_at:object
    open:float
    high:float
    low:float
    close:float
    volume:float|None
    is_final:bool
    content_hash:str
    provenance:object
