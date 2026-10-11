"""Controlled native-tick OHLC fixtures. All decisions use actual Gold engines."""
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from math import sin

from monatise.research.gc_fib.candles import GCBar, GCIdentity, INTERVALS
from monatise.research.gc_qualification import AVAILABILITY, BASELINE, FROZEN, SAFETY, VERSION
from monatise.research.gc_qualification.models import digest

NOW_NS = int(datetime(2026,10,5,16,tzinfo=UTC).timestamp())*10**9+10*10**9


def fixture(*, short=False, positive=True):
    tail = [(2501,2502,2499,2500),(2500,2503,2499,2501),(2501,2502,2490,2495),
        (2495,2504,2493,2500),(2500,2507,2498,2505),(2505,2510,2502,2506),
        (2506,2507,2498,2502),(2502,2504,2495,2499),
        (2499,2503,2489.9 if positive else 2488,2496),(2496,2516,2495,2515),
        (2515,2516,2509,2512),(2512,2520,2511,2519)]
    bars = []
    for tf,width in INTERVALS.items():
        values = [(round(2470+sin(i*.7)*8,1),round(2472+sin(i*.7)*8,1),
                   round(2468+sin(i*.7)*8,1),round(2470.5+sin(i*.7)*8,1)) for i in range(60)] + tail
        if tf == "1m" and positive:
            values = [(2490,2490,2489.9,2490)]*46
            values += [(2489.4,2489.6,2489.4,2489.6),(2489.6,2489.8,2489.6,2489.8),
                       (2489.8,2490,2489.8,2490),(2490,2490,2489.9,2490)]
            values += [(2490,2519,2489.9,2518.9)]
            values += [(2519,2519.2,2518.8,2519.1)]*21
        boundary = (NOW_NS//10**9//width*width)*10**9
        for i,prices in enumerate(values):
            if tf == "4h": prices = tuple(p+100 for p in prices)
            o,h,l,c = prices
            if short: o,h,l,c = 5000-o,5000-l,5000-h,5000-c
            opened = boundary-(len(values)-i)*width*10**9
            p = tuple(str(Decimal(str(x)).quantize(Decimal('.1'))) for x in (o,h,l,c))
            bars.append(asdict(GCBar(GCIdentity(),tf,opened,opened+width*10**9,
                opened+(width+10)*10**9,NOW_NS+86400*10**9,NOW_NS+86400*10**9,
                *p,1000+i,(digest(dict(tf=tf,opened=opened,prices=p)),),"ENGINEERING_SYNTHETIC")))
    expiration = NOW_NS+90*86400*10**9
    terms = (("unit_of_measure","TRYOZ"),("min_price_increment","100000000"),
             ("unit_of_measure_qty","100000000000"),("display_factor","100000000"),
             ("min_price_increment_amount","1000000000"),("expiration",str(expiration)))
    config = dict(start_ns=NOW_NS-60*10**9,end_ns=NOW_NS+60*10**9,
                  source_commit=BASELINE,frozen_commit=FROZEN,quote_max_age_ns=60*10**9)
    quote = dict(event_ns=NOW_NS-10**9,receive_ns=NOW_NS-10**9,
        admission_ns=NOW_NS+86400*10**9,retrieval_ns=NOW_NS+86400*10**9,
        bid="2519.0" if not short else "2480.8",ask="2519.2" if not short else "2481.0",
        archive_sha256="a"*64,record_sha256="b"*64,ordinal=1)
    return dict(schema=VERSION,historical_availability=AVAILABILITY,pit_verified=False,**SAFETY,
        configuration=config,configuration_sha256=digest(config),bars=bars,cutoffs_ns=[NOW_NS],
        contract=dict(identity=asdict(GCIdentity()),definition_sha256="c"*64,catalog_sha256="d"*64,
            definition_event_ns=NOW_NS-30*86400*10**9,definition_receive_ns=NOW_NS-29*86400*10**9,
            expiration_ns=expiration,tick_size=".1",multiplier="100",monetary_tick_usd="10",native_terms=terms),
        sessions=[dict(start_ns=(NOW_NS//(60*10**9)-60000)*60*10**9,
            end_ns=(NOW_NS//(60*10**9)+100)*60*10**9)],
        source_archives=[],derived_input_sha256="e"*64,session_review_sha256="f"*64,
        quote_coverage=[[NOW_NS-86400*10**9,NOW_NS+86400*10**9]],quotes={str(NOW_NS):quote},frozen_associations=[])
