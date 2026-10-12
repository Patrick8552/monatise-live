"""Local reviewed quote-file admission, never terminal/login/export execution."""
from dataclasses import dataclass, asdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.broker_xauusd.models import BrokerIdentity
from .models import digest, hash_required, number
from .mapping import BrokerQuote

UNITS={'XAU/USD':'USD_PER_TRYOZ','US500.cash':'INDEX_POINT','US100.cash':'INDEX_POINT'}
KINDS={'POINT_IN_TIME_OBSERVATION','RETROSPECTIVE_HISTORICAL_DOWNLOAD','ENGINEERING_SYNTHETIC'}


@dataclass(frozen=True)
class BrokerSpecification:
    broker: str
    server: str
    account_reference: str
    instrument: str
    native_symbol: str
    currency: str
    price_unit: str
    digits: int
    tick_size: Decimal
    point: Decimal
    contract_size: Decimal
    source_sha256: str
    available_ns: int

    def __post_init__(self):
        timestamp_ns(self.available_ns);hash_required(self.source_sha256)
        for value in (self.broker,self.server,self.account_reference,self.native_symbol):
            if not isinstance(value,str) or not value.strip() or len(value)>128:
                raise ValueError('complete_broker_server_symbol_identity_required')
        if self.instrument not in UNITS or self.price_unit!=UNITS[self.instrument] or self.currency!='USD':
            raise ValueError('reviewed_broker_price_units_required')
        if self.instrument=='XAU/USD':
            BrokerIdentity(self.broker,self.account_reference,self.server,self.native_symbol)
        elif self.native_symbol!=self.instrument:
            raise ValueError('exact_registered_index_symbol_required')
        if type(self.digits) is not int or not 0<=self.digits<=12:
            raise ValueError('bounded_broker_precision_required')
        for key in ('tick_size','point','contract_size'):
            object.__setattr__(self,key,number(getattr(self,key),positive=True))
        if self.point!=Decimal(10)**-self.digits or self.tick_size%self.point:
            raise ValueError('contradictory_broker_precision_or_tick')

    @property
    def namespace(self):
        return 'BROKER:'+digest(asdict(self))


@dataclass(frozen=True)
class BrokerSessions:
    specification_namespace: str
    source_sha256: str
    review_reference: str
    intervals: tuple

    def __post_init__(self):
        hash_required(self.source_sha256)
        if not self.review_reference or not self.specification_namespace or not isinstance(self.intervals,tuple) or not 1<=len(self.intervals)<=10000:
            raise ValueError('reviewed_broker_session_required')
        previous=0
        for pair in self.intervals:
            if not isinstance(pair,tuple) or len(pair)!=2:raise ValueError('immutable_session_intervals_required')
            start,end=pair;timestamp_ns(start);timestamp_ns(end)
            if not previous<=start<end:raise ValueError('ordered_nonoverlapping_sessions_required')
            previous=end

    def interval(self,at_ns):
        return next(((a,b) for a,b in self.intervals if a<=at_ns<b),None)


@dataclass(frozen=True)
class ImportedBrokerQuote:
    specification: BrokerSpecification
    bid: Decimal
    ask: Decimal
    event_ns: int
    receive_ns: int | None
    admission_ns: int
    available_ns: int
    source_sha256: str
    record_sha256: str
    ordinal: int
    evidence_kind: str
    session_sha256: str

    def __post_init__(self):
        for t in (self.event_ns,self.admission_ns,self.available_ns):timestamp_ns(t)
        for h in (self.source_sha256,self.record_sha256,self.session_sha256):hash_required(h)
        if self.receive_ns is not None:
            timestamp_ns(self.receive_ns)
            if not self.event_ns<=self.receive_ns<=self.available_ns:raise ValueError('invalid_broker_receipt_clock')
        if (self.evidence_kind not in KINDS or type(self.ordinal) is not int or self.ordinal<0
                or not self.event_ns<=self.available_ns<=self.admission_ns
                or self.specification.available_ns>self.available_ns):
            raise ValueError('invalid_broker_availability_or_provenance')
        for key in ('bid','ask'):
            value=number(getattr(self,key),positive=True)
            if value%self.specification.tick_size:raise ValueError('broker_quote_off_tick')
            object.__setattr__(self,key,value)
        if self.bid>self.ask:raise ValueError('crossed_broker_quote')

    @property
    def midpoint(self):return (self.bid+self.ask)/2

    def basis_quote(self, *, cutoff_ns):
        if self.receive_ns is None:raise ValueError('broker_receipt_unavailable_not_invented')
        if self.available_ns>cutoff_ns:raise ValueError('broker_observation_not_available_at_cutoff')
        # The Phase 4 mapping model treats this admission clock as availability.
        # Never backdate a historical export to manufacture point-in-time access.
        return BrokerQuote(self.specification.instrument,self.specification.namespace,'USD',self.bid,self.ask,
            self.event_ns,self.receive_ns,self.available_ns,self.record_sha256,
            'ENGINEERING_SYNTHETIC' if self.evidence_kind=='ENGINEERING_SYNTHETIC' else 'AUTHENTIC_ARCHIVED_RECORD',
            self.specification.price_unit)


def import_quotes(path, *, specification, sessions, review, admission_ns, capacity=50000):
    """Sideband review binds source origin/clocks/identity; a label is not proof.

    This authentic-file interface requires an independently reviewed source hash.
    The caller must supply that review; no review is manufactured by the importer.
    Historical imports stay retrospective even when prices themselves are genuine.
    """
    timestamp_ns(admission_ns)
    if (type(capacity) is not int or not 1<=capacity<=50000 or sessions.specification_namespace!=specification.namespace
            or review.get('specification_namespace')!=specification.namespace
            or review.get('session_sha256')!=sessions.source_sha256
            or not review.get('origin_review_reference') or not review.get('clock_review_reference')):
        raise ValueError('independent_source_identity_session_and_clock_review_required')
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>16*1024**2:raise ValueError('bounded_regular_quote_file_required')
    raw=path.read_bytes();source_hash=hashlib.sha256(raw).hexdigest()
    if source_hash!=review.get('source_sha256'):raise ValueError('broker_source_hash_mismatch')
    doc=json.loads(raw)
    if doc.get('schema')!='broker-quote-export-v1' or doc.get('evidence_kind') not in KINDS:
        raise ValueError('unsupported_broker_export')
    kind=doc['evidence_kind']
    if kind!=review.get('evidence_kind') or doc.get('specification_namespace')!=specification.namespace:
        raise ValueError('broker_source_kind_or_identity_mismatch')
    if kind=='POINT_IN_TIME_OBSERVATION' and not review.get('original_capture_proof_reference'):
        raise ValueError('original_capture_proof_required')
    rows=doc.get('quotes')
    if not isinstance(rows,list) or not rows or len(rows)>capacity:raise ValueError('bounded_quote_rows_required')
    result=[];previous=None
    for ordinal,row in enumerate(rows):
        if not isinstance(row,dict) or not isinstance(row.get('bid'),str) or not isinstance(row.get('ask'),str):
            raise ValueError('exact_decimal_broker_prices_required')
        event=row['event_ns'];receipt=row.get('receive_ns')
        available=(row['original_available_ns'] if kind=='POINT_IN_TIME_OBSERVATION' else admission_ns)
        if kind=='ENGINEERING_SYNTHETIC':available=row.get('original_available_ns',admission_ns)
        q=ImportedBrokerQuote(specification,Decimal(row['bid']),Decimal(row['ask']),event,receipt,
            admission_ns,available,source_hash,digest(row),ordinal,kind,sessions.source_sha256)
        if previous is not None and event<previous:raise ValueError('unordered_broker_ticks')
        if sessions.interval(event) is None:raise ValueError('broker_quote_outside_reviewed_session')
        if 'time_msc' in row and (type(row['time_msc']) is not int or row['time_msc']*10**6!=event):
            raise ValueError('native_millisecond_clock_mismatch')
        previous=event;result.append(q)
    return tuple(result)


def import_candles(path, *, specification, sessions, review, admission_ns, cutoff_ns,
                   spread_price, confirmation_sha256=None, confirmation_ns=None):
    """Reviewed broker OHLC export for the existing canonical five-timeframe path.

    Volumes are broker tick counts, never exchange contracts. Session gaps require
    the existing calendar integration; this first adapter rejects discontinuities.
    """
    from .signals import CandleEvidence
    from monatise.application.hierarchy.assets import _timestamp
    from monatise.application.hierarchy.policy import INTERVAL_SECONDS
    from monatise.adapters.databento_identity import datetime_ns
    from datetime import datetime,timedelta
    timestamp_ns(admission_ns);timestamp_ns(cutoff_ns)
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>4*1024**2:
        raise ValueError('bounded_regular_candle_export_required')
    raw=path.read_bytes();source_hash=hashlib.sha256(raw).hexdigest();doc=json.loads(raw)
    kind=doc.get('evidence_kind')
    if (doc.get('schema')!='broker-candle-export-v1' or kind not in KINDS
            or kind!=review.get('evidence_kind') or source_hash!=review.get('source_sha256')
            or doc.get('specification_namespace')!=specification.namespace
            or review.get('specification_namespace')!=specification.namespace
            or sessions.specification_namespace!=specification.namespace
            or review.get('session_sha256')!=sessions.source_sha256
            or not review.get('origin_review_reference') or not review.get('clock_review_reference')
            or review.get('volume_kind')!='broker_tick_count'):
        raise ValueError('reviewed_broker_candle_identity_clock_volume_required')
    captured=admission_ns
    if kind in {'POINT_IN_TIME_OBSERVATION','ENGINEERING_SYNTHETIC'}:
        captured=doc.get('original_available_ns')
    if kind=='POINT_IN_TIME_OBSERVATION' and not review.get('original_capture_proof_reference'):
        raise ValueError('original_capture_proof_required')
    timestamp_ns(captured)
    interval=sessions.interval(cutoff_ns)
    if not specification.available_ns<=captured<=admission_ns or interval is None:
        raise ValueError('broker_candle_availability_or_session_invalid')
    rows=doc.get('timeframes')
    if not isinstance(rows,dict) or set(rows)!=set(INTERVAL_SECONDS):
        raise ValueError('canonical_timeframes_incomplete')
    frames={}
    for tf,series in rows.items():
        if not isinstance(series,list) or not 51<=len(series)<=240:
            raise ValueError('bounded_canonical_history_required')
        frames[tf]=[]
        for row in series:
            if (not isinstance(row,dict) or any(not isinstance(row.get(k),str) for k in ('t','o','h','l','c'))
                    or type(row.get('v')) is not int or not 0<=row['v']<2**63):
                raise ValueError('exact_broker_OHLC_and_tick_volume_required')
            prices={k:number(row[k],positive=True) for k in ('o','h','l','c')}
            if any(p%specification.tick_size for p in prices.values()) or not prices['l']<=min(prices['o'],prices['c'])<=max(prices['o'],prices['c'])<=prices['h']:
                raise ValueError('broker_candle_tick_or_geometry_invalid')
            parsed=datetime.fromisoformat(row['t'].replace('Z','+00:00'))
            if parsed.utcoffset()!=timedelta(0):raise ValueError('explicit_UTC_broker_bar_clock_required')
            stamp=datetime_ns(_timestamp(row['t']))
            if sessions.interval(stamp) is None:raise ValueError('broker_bar_outside_reviewed_session')
            frames[tf].append(dict(t=row['t'],**{k:float(v) for k,v in prices.items()},v=row['v']))
    value=CandleEvidence(specification.instrument,specification.namespace,
        'ENGINEERING_SYNTHETIC' if kind=='ENGINEERING_SYNTHETIC' else 'AUTHENTIC_ARCHIVED_RECORD',source_hash,
        captured,interval[1],json.dumps(frames,sort_keys=True),float(specification.point),float(specification.tick_size),
        float(number(spread_price)),review['clock_review_reference'],confirmation_sha256,confirmation_ns)
    value.rows(expected=specification.instrument,now_ns=cutoff_ns)
    return value
