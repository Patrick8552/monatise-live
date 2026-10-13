"""Explicit native CME live scope and one-use operator permits; no connections."""
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.institutional.models import Contract,number,digest,hash_required
from monatise.research.institutional.normalize import definition,EconomicConvention
from monatise.research.institutional.native_index import validate as index_definition
from monatise.research.databento.datasets import DatasetCapability

SCHEMAS=('definition','trades','mbp-1')
SAFETY=dict(execution_eligible=False,publication_eligible=False,approval_eligible=False,
            production_registered=False,gil_enabled=False)


@dataclass(frozen=True)
class ClockReview:
    """Explicit short-lived independent UTC uncertainty, never a clock rewrite.

    Offsets are UTC minus the original local wall clock. Receipts remain raw;
    bounds only qualify cross-host ordering and conservative freshness. This is
    an operator research review, not authenticated production time certification.
    """
    observed_at_ns: int
    expires_ns: int
    offset_lower_ns: int
    offset_upper_ns: int
    source_sha256: str
    review_reference: str
    drift_bound_ppm: int=100

    def __post_init__(self):
        timestamp_ns(self.observed_at_ns);timestamp_ns(self.expires_ns)
        hash_required(self.source_sha256)
        if (not 0<self.expires_ns-self.observed_at_ns<=300*10**9
                or type(self.offset_lower_ns) is not int or type(self.offset_upper_ns) is not int
                or not -10**9<=self.offset_lower_ns<=self.offset_upper_ns<=10**9
                or self.offset_upper_ns-self.offset_lower_ns>500*10**6
                or type(self.drift_bound_ppm) is not int or not 0<=self.drift_bound_ppm<=1000
                or not isinstance(self.review_reference,str) or not self.review_reference.strip()):
            raise ValueError('bounded_independent_research_clock_review_required')

    def bounds(self,now_ns):
        timestamp_ns(now_ns)
        if not self.observed_at_ns<=now_ns<self.expires_ns:
            raise ValueError('independent_clock_review_expired_or_not_yet_available')
        drift=(now_ns-self.observed_at_ns)*self.drift_bound_ppm//10**6
        return self.offset_lower_ns-drift,self.offset_upper_ns+drift


def native_definition(record, *, capability,publishers,as_of_ns):
    """Reuse native index/discovery seams; genuine GC terms differ from legacy.
    DBN prices stay fixed-point conventional prices. No display-factor rescaling.
    """
    product=str(record.asset)
    if product in {'ES','NQ'}:
        return index_definition(record,capability=capability,publishers=publishers,as_of_ns=as_of_ns)
    if product!='GC':raise ValueError('only_reviewed_GC_ES_NQ_native_futures_supported')
    if (str(record.unit_of_measure)!='TRYOZ' or record.main_fraction!=255
            or str(record.instrument_class)!='F' or str(record.security_type)!='FUT'
            or record.leg_count!=0 or str(record.user_defined_instrument)!='N'):
        raise ValueError('native_GC_outright_terms_required')
    tick=number(record.min_price_increment)/10**9
    size=number(record.unit_of_measure_qty)/10**9
    display=number(record.display_factor,positive=True)/10**9
    amount=number(record.min_price_increment_amount,positive=True)/10**9
    if tick!=Decimal('.1') or size!=100 or amount/display!=tick*size:
        raise ValueError('native_GC_economics_contradictory')
    return definition(record,capability=capability,publishers=publishers,as_of_ns=as_of_ns,
        convention=EconomicConvention('GC',tick,size,'USD_PER_TRYOZ','native-CME-live-GC-v1'))


@dataclass(frozen=True)
class LiveScope:
    contracts: tuple[Contract,...]
    start_ns: int
    session_end_ns: int
    session_review_reference: str
    capability: DatasetCapability
    publishers: tuple
    schemas: tuple[str,...]=SCHEMAS
    duration_seconds: int=300
    heartbeat_seconds: int=5
    maximum_market_age_ns: int=10*10**9
    maximum_records: int=100000
    maximum_bytes: int=32*1024**2
    clock_review: ClockReview|None=None

    def __post_init__(self):
        timestamp_ns(self.start_ns);timestamp_ns(self.session_end_ns)
        if (not isinstance(self.contracts,tuple) or not 1<=len(self.contracts)<=3
                or len({c.identity for c in self.contracts})!=len(self.contracts)
                or any(c.asset_class!='futures' or c.metadata.product not in {'GC','ES','NQ'} for c in self.contracts)
                or not isinstance(self.schemas,tuple) or not self.schemas or len(set(self.schemas))!=len(self.schemas)
                or not set(self.schemas)<=set(SCHEMAS) or 'definition' not in self.schemas
                or not self.session_review_reference
                or not isinstance(self.capability,DatasetCapability)
                or not isinstance(self.publishers,tuple) or not self.publishers
                or len({row[0] for row in self.publishers})!=len(self.publishers)
                or any(tuple(row[1:])!=('GLBX.MDP3','GLBX') for row in self.publishers)
                or any(c.metadata.publisher_id not in {row[0] for row in self.publishers} for c in self.contracts)
                or type(self.duration_seconds) is not int or not 1<=self.duration_seconds<=86400
                or type(self.heartbeat_seconds) is not int or not 1<=self.heartbeat_seconds<=30
                or type(self.maximum_market_age_ns) is not int or not 0<self.maximum_market_age_ns<=30*10**9
                or type(self.maximum_records) is not int or not 1<=self.maximum_records<=1000000
                or type(self.maximum_bytes) is not int or not 1024<=self.maximum_bytes<=1024**3
                or self.clock_review is not None and not isinstance(self.clock_review,ClockReview)
                or not self.start_ns<self.session_end_ns
                or any(not c.metadata.receive_ns<=self.start_ns<self.session_end_ns<=c.metadata.expiration_ns for c in self.contracts)):
            raise ValueError('reviewed_bounded_exact_live_scope_required')

    @property
    def sha256(self):return digest(self)

    def validate_at(self,now_ns):
        timestamp_ns(now_ns)
        lower,upper=self.clock_bounds(now_ns)
        if (not self.start_ns<=now_ns<self.session_end_ns or now_ns-self.start_ns>24*3600*10**9
                or now_ns+self.duration_seconds*10**9+max(0,upper)>self.session_end_ns
                or not 0<=now_ns-self.capability.observed_at_ns<=300*10**9):
            raise ValueError('current_reviewed_session_and_bounded_replay_required')
        for schema in self.schemas:self.capability.require(schema,at_ns=now_ns)

    def clock_bounds(self,now_ns):
        return self.clock_review.bounds(now_ns) if self.clock_review else (0,0)


@dataclass(frozen=True)
class LivePermit:
    permit_id: str
    scope_sha256: str
    approved_at_ns: int
    expires_ns: int
    human_approval_reference: str
    live_entitlement_reference: str
    native_lineage_review_reference: str
    subscription_cost_reference: str
    total_monthly_cost_usd: str
    approved_monthly_budget_usd: str
    licensing_use_reference: str
    confirmed_available_sessions: int

    def validate(self,scope,now_ns):
        scope.validate_at(now_ns)
        for t in (self.approved_at_ns,self.expires_ns):timestamp_ns(t)
        if (not self.approved_at_ns<=now_ns<self.expires_ns
                or not 0<self.expires_ns-self.approved_at_ns<=300*10**9
                or self.scope_sha256!=scope.sha256
                or any(not isinstance(v,str) or not v.strip() for v in (self.permit_id,self.human_approval_reference,
                    self.live_entitlement_reference,self.native_lineage_review_reference,self.subscription_cost_reference,
                    self.licensing_use_reference))
                or number(self.total_monthly_cost_usd)<0
                or number(self.approved_monthly_budget_usd)<number(self.total_monthly_cost_usd)
                or type(self.confirmed_available_sessions) is not int
                or not len(scope.schemas)<=self.confirmed_available_sessions<=10):
            raise ValueError('fresh_scope_bound_live_entitlement_cost_and_human_permit_required')


def consume_permit(path,permit,scope,now_ns):
    """Durable one-attempt gate before SDK.subscribe (the connection boundary).
    Receipts are trusted operator inputs, never evidence created by this code.
    Promotional credit is a discount, not a monthly charge limit.
    """
    if not isinstance(permit,LivePermit):raise ValueError('live_permit_required')
    permit.validate(scope,now_ns)
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path,timeout=30,isolation_level=None) as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS live_permits (id TEXT PRIMARY KEY, scope TEXT NOT NULL, receipt TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('INSERT INTO live_permits VALUES (?,?,?)',
                (permit.permit_id,scope.sha256,json.dumps(dict(permit_sha256=digest(permit),consumed_at_ns=now_ns))))
            db.execute('COMMIT')
        except sqlite3.IntegrityError:
            db.execute('ROLLBACK')
            raise ValueError('live_permit_already_consumed_no_automatic_retry') from None
    path.chmod(0o600)
