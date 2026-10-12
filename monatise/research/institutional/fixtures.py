"""Controlled engineering scenarios, not authentic contracts, prices or returns."""
from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

from monatise.research.databento.datasets import DatasetCapability
from .models import digest
from .normalize import EconomicConvention, definition, observation
from .signals import CandleEvidence
from .mapping import dt

NOW_NS = 1791216016*10**9  # 2026-10-05 16:00:16 UTC; two fixture polls six seconds apart
CAPABILITY = DatasetCapability('GLBX.MDP3',('definition','trades','mbp-1','statistics','status','ohlcv-1m'),
                               NOW_NS-2*86400*10**9,digest('ENGINEERING_SYNTHETIC_METADATA'))
ENABLED = CAPABILITY.schemas


def contract(product='GC', *, option=False):
    import databento_dbn as dbn
    iid, tick, multiplier, unit = {'GC':(41271,'.1','100','USD_PER_TRYOZ'),
        'ES':(900001,'.25','50','INDEX_POINT'),
        'NQ':(900002,'.25','20','INDEX_POINT')}[product]
    family = 'OG' if option else product
    record = dbn.InstrumentDefMsg(publisher_id=1,instrument_id=900003 if option else iid,
        ts_event=NOW_NS-86400*10**9,ts_recv=NOW_NS-86400*10**9+1,
        raw_symbol='OGZ6 C2500' if option else product+'Z6',asset=family,
        exchange='XCEC' if product=='GC' else 'XCME',currency='USD',
        min_price_increment=int(Decimal('.1' if option else tick)*10**9),
        instrument_class=dbn.InstrumentClass.CALL if option else dbn.InstrumentClass.FUTURE,
        security_type='OOF' if option else 'FUT',security_update_action=dbn.SecurityUpdateAction.ADD,
        expiration=NOW_NS+(30 if option else 60)*86400*10**9, maturity_year=2026,maturity_month=12,
        underlying_id=iid if option else 0,strike_price=2500*10**9 if option else 2**63-1,
        user_defined_instrument=dbn.UserDefinedInstrument.NO,unit_of_measure='TRYOZ' if product=='GC' else 'IPNT',
        unit_of_measure_qty=int(Decimal(multiplier)*10**9),display_factor=10**9,min_price_increment_amount=int(Decimal(tick)*Decimal(multiplier)*10**9))
    convention=EconomicConvention(family,Decimal('.1' if option else tick),Decimal(multiplier),unit,
                                  'ENGINEERING_SYNTHETIC_REVIEWED_TERMS')
    return definition(record,capability=CAPABILITY,publishers={1:('GLBX.MDP3','GLBX')},
                      as_of_ns=NOW_NS,convention=convention)


def quote(value, *, receive_ns=NOW_NS-10**9, bid=None, ask=None, ordinal=1):
    import databento_dbn as dbn
    tick=value.tick_size
    centre=Decimal('2519') if value.metadata.product in {'GC','OG'} else Decimal('5000')
    bid=centre if bid is None else Decimal(str(bid))
    ask=centre+tick*2 if ask is None else Decimal(str(ask))
    record=dbn.MBP1Msg(publisher_id=value.metadata.publisher_id,instrument_id=value.metadata.instrument_id,
        ts_event=receive_ns-1,ts_recv=receive_ns,price=int(bid*10**9),size=1,side=dbn.Side.BID,
        action=dbn.Action.MODIFY,depth=0,flags=0,sequence=ordinal,
        levels=dbn.BidAskPair(bid_px=int(bid*10**9),ask_px=int(ask*10**9),bid_sz=10,ask_sz=12,bid_ct=2,ask_ct=3))
    return observation(record,schema='mbp-1',contract=value,archive_sha256=digest('FIXTURE_BOOK_ARCHIVE'),
        ordinal=ordinal,retrieval_ns=receive_ns+1,admission_ns=receive_ns+1,
        evidence_kind='ENGINEERING_SYNTHETIC',enabled_schemas=ENABLED)


def candle_evidence(asset='GC', *, positive=True, short=False):
    # Reuse the existing controlled Gold geometry builder; this is an explicit
    # engineering broker/native-crypto scenario, never a futures-to-spot transform.
    from tests.research.gc_qualification_fixtures import fixture
    raw=fixture(positive=positive,short=short)
    instrument={'GC':'XAU/USD','ES':'US500.cash','NQ':'US100.cash','BTC':'BTC','ETH':'ETH','SOL':'SOL'}[asset]
    frames={tf:[] for tf in ('4h','1h','15m','5m','1m')}
    for row in raw['bars']:
        frames[row['timeframe']].append(dict(t=dt(row['open_ns']).isoformat(),o=float(row['open']),
            h=float(row['high']),l=float(row['low']),c=float(row['close']),v=row['volume']))
    source=digest(dict(kind='ENGINEERING_SYNTHETIC',asset=asset,frames=frames))
    return CandleEvidence(instrument,'ENGINEERING_FIXTURE', 'ENGINEERING_SYNTHETIC',source,NOW_NS-6*10**9,
        NOW_NS+3*3600*10**9,json.dumps(frames,sort_keys=True),.01,.01,.2,'ENGINEERING_SYNTHETIC_CONTINUITY',
        digest(dict(source=source,confirmation_ns=NOW_NS)),NOW_NS)


def positioning(asset='ES'):
    raw=dict(symbol=asset+'=F',underlying_price=2519.,gamma_flip=2400.,call_wall=2700.,put_wall=2300.,
        net_gex=100.,gamma_flip_status='available',as_of=dt(NOW_NS-7*10**9).isoformat(),
        data_as_of=dict(futures_feed=dt(NOW_NS-7*10**9).isoformat(),futures_options_feed=dt(NOW_NS-7*10**9).isoformat()))
    return dict(raw,source='ENGINEERING_FIXTURE_FLASHALPHA',provider_evidence={'levels':dict(raw),'gex':dict(raw)},
        _source_sha256=digest(raw),_evidence_kind='ENGINEERING_SYNTHETIC',_available_ns=NOW_NS-7*10**9)
