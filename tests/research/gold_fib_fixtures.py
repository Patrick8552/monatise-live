"""Artificial causal observations, explicitly not a market/performance dataset."""
from datetime import UTC, datetime, timedelta
from math import sin
from dataclasses import asdict

from monatise.core.models import Candle
from monatise.research.gold_fib.models import encode

SOURCE_COMMIT='0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18'
NOW=datetime(2026,10,5,15,4,20,tzinfo=UTC)
SECONDS={'4h':14400,'1h':3600,'15m':900,'5m':300,'1m':60}


def wave(tf, *, short=False):
    # Same canonical acceptance pattern, ending exactly at 15:00 UTC.
    from tests.test_gold_technical_first import synthetic_candles
    return synthetic_candles(tf,short=short)


def h1_leg(*, short=False, forming_b=False, origin_latency=False, aged=False):
    # Three earlier opposing liquidity objectives do not become anchors. Latest
    # pre-break high=2470, most recent origin low=2450, first impulse high=2530.
    mids=[2500+sin(i*.7)*5 for i in range(30)]
    mids += [2520,2551.76,2520,2500,2480,2500,2563.12,2510,2490,
             2500,2579.44,2510,2490,2470,2460,2455,2460,2465,2470,
             2465,2460,2455,2450,2456,2460,2465,2467,2480,2530,
             2520,2510,2505,2512,2519,2518]
    original_length=len(mids)
    if aged:
        mids += [2510+i*.02+sin(i*.7)*2 for i in range(160)]
    bars=[]
    end=datetime(2026,10,5,15,tzinfo=UTC)
    for i,mid in enumerate(mids):
        if i==(56 if origin_latency else 57):  # body displacement across 2470, event must be causal
            o,h,l,c=2466,2482,2465,2480
        else:
            o,h,l,c=(mid-.01,mid+.2,mid-.2,mid) if aged and i>=original_length else (mid-.2,mid,mid-1,mid-.1)
        if i==52:
            o,h,l,c=2451,2452,2450,2451.5
        if i==58:
            o,h,l,c=2525,2530,2524,2529
        if forming_b and i>=58:
            o,h,l,c=2490+(i-58)*10,2500+(i-58)*10,2489+(i-58)*10,2499+(i-58)*10
        if short:
            o,h,l,c=5000-o,5000-l,5000-h,5000-c
        bars.append(Candle((end-timedelta(hours=len(mids)-i)).isoformat(),o,h,l,c,1000+i))
    return tuple(bars)


def entry_bars(*, short=False):
    # Nearer demand zone is behind the real observed price; its upper boundary
    # is the permitted planned entry, not an altered observed executable quote.
    end=datetime(2026,10,5,15,4,tzinfo=UTC)
    values=[2505 for i in range(60)]
    data=[(v,v+.2,v-.2,v+.05) for v in values]
    data += [(2488.5,2488.7,2488.2,2488.3),
             (2488.3,2504,2488.3,2503),
             (2503,2510,2502,2509),
             (2509,2520,2508,2519)]
    data += [(2505,2505.2,2504.8,2505) for i in range(14)]
    data[-1]=(2505,2505.2,2504.8,2505)
    out=[]
    for i,(o,h,l,c) in enumerate(data):
        if short: o,h,l,c=5000-o,5000-l,5000-h,5000-c
        out.append(Candle((end-timedelta(minutes=len(data)-i)).isoformat(),o,h,l,c,1000+i))
    return tuple(out)


def archive(*,short=False,forming_b=False,origin_latency=False,late_history=False,aged=False):
    h1=h1_leg(short=short,forming_b=forming_b,origin_latency=origin_latency,aged=aged)
    first=datetime(2026,9,20,tzinfo=UTC); last=datetime(2026,10,10,tzinfo=UTC)
    days=int((last-first).days)
    calendar={'schema':'gold-broker-sessions-v1','account_id':'ENGINEERING_ONLY',
        'server':'SYNTHETIC_NOT_BROKER','symbol':'XAU/USD',
        'source':'artificial engineering calendar; not live broker certification','version':'fixture-v1',
        'valid_from':first.isoformat(),'valid_until':last.isoformat(),
        'offsets':[{'from':first.isoformat(),'until':last.isoformat(),'seconds':0}],
        'sessions':[{'open':(first+timedelta(days=i)).isoformat(),
                     'close':(first+timedelta(days=i+1)).isoformat()} for i in range(days)]}
    # Older H4 bars span >12days; expand bounded calendar backwards.
    first=datetime(2026,9,1,tzinfo=UTC)
    calendar['valid_from']=first.isoformat(); calendar['offsets'][0]['from']=first.isoformat()
    calendar['sessions']=[{'open':(first+timedelta(days=i)).isoformat(),
                     'close':(first+timedelta(days=i+1)).isoformat()} for i in range((last-first).days)]
    observations=[]
    # Explicit two synthetic observations after each bar closes. Only in these
    # artificial fixtures is known-at generated; replay never infers it itself.
    all_bars={tf:(h1 if tf=='1h' else entry_bars(short=short) if tf=='1m' else wave(tf,short=short)) for tf in SECONDS}
    times=set()
    for tf,cs in all_bars.items():
        for c in cs:
            close=datetime.fromisoformat(c.timestamp)+timedelta(seconds=SECONDS[tf])
            times.update([close+timedelta(seconds=10),close+timedelta(seconds=20)])
    for at in sorted(t for t in times if t<NOW):
        batches={tf:[encode(asdict(c)) for c in cs if datetime.fromisoformat(c.timestamp)+timedelta(seconds=SECONDS[tf])+timedelta(seconds=10)<=at] for tf,cs in all_bars.items()}
        batches={tf:cs for tf,cs in batches.items() if cs}
        if late_history and at < NOW-timedelta(seconds=10):
            batches.pop('1h',None)
        observations.append({'at':at.isoformat(),'candles':batches,'warmup_only':True})
    observations.append({'at':NOW.isoformat(),'candles':{tf:[encode(asdict(c)) for c in cs] for tf,cs in all_bars.items()}})
    return {'schema':'gold-h1-fib-observation-archive-v1', 'evidence_kind':'ENGINEERING_SYNTHETIC',
        'source_commit':SOURCE_COMMIT,'source_version':'engineering-fixture-v1',
        'calendar':calendar,'broker_identity':{'account_id':'ENGINEERING_ONLY','server':'SYNTHETIC_NOT_BROKER','symbol':'XAU/USD'},
        'broker_units':{'point':.01,'tick_size':.01,'spread_price':.2},'observations':observations}


def repeated_setup_archive(*, short=False):
    """Two different M15/M5 identities underneath one actual synthetic H1 move."""
    result=archive(short=short)
    data={tf:list(cs) for tf,cs in result['observations'][-1]['candles'].items()}
    def add(tf,o,h,l,c):
        if short: o,h,l,c=5000-o,5000-l,5000-h,5000-c
        last=datetime.fromisoformat(data[tf][-1]['timestamp'])
        data[tf].append(encode(asdict(Candle((last+timedelta(seconds=SECONDS[tf])).isoformat(),o,h,l,c,2000))))
    add('15m',2519,2521,2510,2520)
    for bar in [(2519,2519.5,2515,2516),(2516,2519,2515,2518),(2518,2519,2516,2517),(2517,2526,2516,2525)]:
        add('5m',*bar)
    for _ in range(16):
        add('1m',2505,2505.2,2504.8,2505)
    result['observations'].append({'at':datetime(2026,10,5,15,20,10,tzinfo=UTC).isoformat(),'candles':data,'warmup_only':True})
    result['observations'].append({'at':datetime(2026,10,5,15,20,20,tzinfo=UTC).isoformat(),'candles':data})
    return result


def range_gate_archive(*,short=False,case='two-atr'):
    """Artificial boundary cases for fixed v1 range/distance gates, not markets."""
    result=archive(short=False)
    cs=list(h1_leg())
    overrides={}
    if case=='two-atr':
        overrides={48:(2494,2495,2493,2494.5),49:(2493,2494,2492,2493.5),
            50:(2492,2493,2491,2492.5),51:(2491,2492,2490.5,2491.5),
            52:(2490.5,2491,2490,2490.8)}
        for i in range(53,57): overrides[i]=(2491,2494.9,2490.2,2494)
        overrides[57]=(2491,2509,2490.2,2507)
        overrides[58]=(2491,2510,2490.2,2508)
        for i in range(59,65): overrides[i]=(2491,2509.9,2490.2,2507)
    else:
        span=2000 if case=='distance-one' else 1050
        origin=2500-span
        def project(p): return origin+(p-2450)*span/80
        for i in range(45,65):
            c=cs[i];overrides[i]=tuple(project(p) for p in (c.open,c.high,c.low,c.close))
        for idx,ratio in zip((31,36,40),(1.272,1.414,1.618)):
            p=origin+span*ratio;overrides[idx]=(p-.2,p,p-1,p-.1)
    mapping={cs[i].timestamp:values for i,values in overrides.items()}
    for obs in result['observations']:
        for row in obs['candles'].get('1h',[]):
            if row['timestamp'] in mapping:
                row.update(dict(zip(('open','high','low','close'),mapping[row['timestamp']])))
    if short:
        for obs in result['observations']:
            for rows in obs['candles'].values():
                for row in rows:
                    o,h,l,c=[row[k] for k in ('open','high','low','close')]
                    row.update(open=5000-o,high=5000-l,low=5000-h,close=5000-c)
    return result
