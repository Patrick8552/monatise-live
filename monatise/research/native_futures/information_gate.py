"""Source integrity for native information, without custom statistical price caps.

Databento's normalizers retain schema/identity/tick/flag/clock semantics. This
class checks local provenance and ordering. It supplies no price model, anchor,
MAD threshold, spread cap, signal qualification or automatic recovery.
"""
from collections import OrderedDict,deque
from monatise.research.institutional.models import MarketObservation,digest
from monatise.research.phase9.quality import QualityGate

MODE='DATABENTO_NATIVE_INFORMATION_V1'

class NativeInformationGate:
    lineage_observations=QualityGate.lineage_observations
    transport_gap=QualityGate.transport_gap

    def __init__(self,contract,*,capacity=50000,rolling=True):
        if contract.asset_class!='futures' or contract.metadata.product not in {'GC','ES','NQ'}:
            raise ValueError('reviewed_native_futures_required')
        if type(capacity) is not int or not 1<=capacity<=100000 or type(rolling) is not bool:
            raise ValueError('bounded_native_information_required')
        self.contract,self.capacity,self.rolling=contract,capacity,rolling
        self.positions=OrderedDict();self.last_events={};self.last_received={}
        self.latest={};self.faults={};self.fault_event_ns={};self.fault_details={}
        self.accepted=deque(maxlen=capacity);self.quarantine=deque(maxlen=256)
        self.price_sources={};self.coverage_reviews={};self.evicted_positions=0
        self.trade_sources=deque(maxlen=capacity);self.statistics_sources=deque(maxlen=256)
        self.quality_mode=MODE

    def health(self, *, now_ns, policies=None, schemas):
        """Observation availability, not a locally imposed trading freshness rule.

        A valid old observation remains useful as dated information. Report its
        actual age; do not label it current, synchronized or executable. ``policies``
        is accepted for legacy call compatibility but never applies a TTL here.
        """
        result={}
        for schema in schemas:
            value=self.latest.get(schema);fault=self.faults.get(schema)
            if value is None:
                result[schema]=dict(available=False,reason=fault or 'no_native_observations')
                continue
            source=value.payload[1] if schema.startswith('ohlcv-') else value.payload[2] if schema=='statistics' else value.index_ns
            result[schema]=dict(available=not fault,reason=fault,
                freshness=dict(status='OBSERVED_TIMESTAMP_ONLY',age_ns=now_ns-source,
                    source_ns=source,available_ns=value.source.admission_ns,evaluated_ns=now_ns,
                    local_freshness_cutoff_applied=False,current_or_executable_certified=False),
                event_ns=value.event_ns,receive_ns=value.receive_ns,capture_ns=value.source.retrieval_ns,
                source_sha256=value.source.record_sha256,coverage='CAPTURED_SUBSET_CONTINUITY_UNCERTIFIED')
        return result

    def reject(self,value,reason):
        self.faults[value.schema]=reason
        self.fault_event_ns[value.schema]=min(self.fault_event_ns.get(value.schema,value.event_ns),value.event_ns)
        self.fault_details.setdefault(value.schema,dict(reason=reason,event_ns=value.event_ns,
            record_sha256=value.source.record_sha256,custom_price_anomaly_applied=False))
        self.quarantine.append(dict(source=value.source,reason=reason))
        return dict(accepted=False,duplicate=False,reason=reason,custom_price_anomaly_applied=False)

    def ingest(self,value,*,now_ns):
        if not isinstance(value,MarketObservation) or value.contract!=self.contract:
            raise ValueError('exact_canonical_native_contract_required')
        signature=digest(value);prior=self.positions.get(value.source.position)
        if prior is not None:
            if prior!=signature:return self.reject(value,'source_position_revision')
            return dict(accepted=False,duplicate=True,reason='same_source_position')
        if len(self.positions)>=self.capacity:
            if not self.rolling:return self.reject(value,'quality_capacity_exceeded')
            self.positions.popitem(last=False);self.evicted_positions+=1
        self.positions[value.source.position]=signature
        if value.source.admission_ns>now_ns:return self.reject(value,'not_available_at_cutoff')
        if value.index_ns<self.last_received.get(value.schema,0):
            return self.reject(value,'out_of_order_provider_index_timestamp')
        # Native normalization has already checked fields, native flags and
        # exact contract terms. Large valid movements do not fail a custom cap.
        self.last_events[value.schema]=value.event_ns;self.last_received[value.schema]=value.index_ns
        self.latest[value.schema]=value;self.accepted.append(value)
        if value.schema=='trades':self.trade_sources.append(value)
        if value.schema=='statistics':self.statistics_sources.append(value)
        if value.schema.startswith('ohlcv-'):
            self.price_sources.setdefault(value.schema,deque(maxlen=self.capacity)).append(value)
        return dict(accepted=True,duplicate=False,reason=None,quality_mode=MODE,
            plausibility='NOT_APPLIED',custom_price_anomaly_applied=False)
