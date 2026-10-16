"""Verified initial cursor handoff; replay every native event after each anchor.

This prepares a future INITIAL attempt. It never repairs an old capture, changes
an anchor, creates a connection, or turns reviewed replay into elapsed-live proof.
"""
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
import hashlib

from monatise.research.databento.live_journal import verify
from monatise.research.institutional.models import digest


@dataclass(frozen=True)
class BootstrapReview:
    scope_sha256: str
    source_root: str
    journal_hashes: tuple
    cursors: tuple
    policy_hashes: tuple
    review_reference: str
    capture_clock_tolerance_ns: int = 0
    clock_equivalence_review_reference: str = ""
    trade_prefixes: tuple = ()

    @property
    def sha256(self):return digest(self)

    def checkpoints(self, pipeline, scope):
        fresh=review_bootstrap(pipeline,scope,self.source_root,review_reference=self.review_reference,
            capture_clock_tolerance_ns=self.capture_clock_tolerance_ns,
            clock_equivalence_review_reference=self.clock_equivalence_review_reference)
        if fresh!=self:raise ValueError('bootstrap_source_or_policy_changed')
        return {key:dict(event_ns=event,hashes_at_event=list(hashes)) for key,event,hashes in self.cursors}


    def prefix_reviews(self):
        return {key:dict(expected=[dict(record_sha256=h,identity_sha256=i,ts_recv=t) for h,i,t in rows],
            maximum_translation_ns=self.capture_clock_tolerance_ns,review_reference=self.clock_equivalence_review_reference)
            for key,rows in self.trade_prefixes} if self.capture_clock_tolerance_ns else None


def review_bootstrap(pipeline, scope, root, *, review_reference, capture_clock_tolerance_ns=0, clock_equivalence_review_reference=''):
    """Match sealed native anchor bytes, tied-event prefix and unchanged policies.

    Scope starts at/before the earliest anchor, not at a later aligned minute.
    FeedState's existing verified replay cursor consumes the complete equal-time
    prefix once, then admits every following event, including the startup bridge.
    Missing/mismatched replay prefixes still quarantine the capture.
    """
    import databento_dbn as dn
    if (type(capture_clock_tolerance_ns) is not int or not 0<=capture_clock_tolerance_ns<=1000
            or capture_clock_tolerance_ns and not clock_equivalence_review_reference):
        raise ValueError('explicit_initial_clock_equivalence_review_required')
    root=Path(root).absolute()
    if not review_reference or root.is_symlink() or not root.is_dir():
        raise ValueError('reviewed_sealed_bootstrap_required')
    if set(pipeline.gates)!={c.metadata.instrument_id for c in scope.contracts}:
        raise ValueError('bootstrap_exact_contract_scope_required')
    for c in scope.contracts:
        g=pipeline.gates[c.metadata.instrument_id]
        if g.contract!=c or g.positions or g.accepted or g.faults:
            raise ValueError('bootstrap_requires_pristine_matching_gates')
    cursors=[];hashes=[];policies=[];prefixes=[]
    for schema in scope.schemas:
        if schema=='definition':continue
        if schema not in {'trades','mbp-1','ohlcv-1s','ohlcv-1m'}:raise ValueError('bootstrap_schema_not_reviewed')
        folder=root/schema
        if folder.is_symlink():raise ValueError('bootstrap_symlink_rejected')
        meta=folder/'manifest.json'
        if meta.is_symlink() or meta.stat().st_size>4*1024**2:raise ValueError('bounded_bootstrap_manifest_required')
        header=json.loads(meta.read_text())
        if header['schema']!=schema or header['record_count']>250000 or header['bytes']>128*1024**2:
            raise ValueError('bootstrap_journal_budget_or_schema_mismatch')
        manifest,frames=verify(folder);hashes.append((schema,manifest['raw_sha256']))
        latest={};ties={};identities={};seen=0
        for _,raw in frames:
            seen+=1
            if seen>250000:raise ValueError('bootstrap_record_budget_exceeded')
            rows=dn.DBNDecoder(has_metadata=False,input_version=3).write_and_decode(raw)
            if len(rows)!=1 or bytes(rows[0])!=raw:raise ValueError('bootstrap_native_roundtrip_failed')
            row=rows[0]
            if isinstance(row,(dn.SystemMsg,dn.SymbolMappingMsg)):continue
            if isinstance(row,dn.ErrorMsg):raise ValueError('bootstrap_source_error')
            iid=row.instrument_id
            if iid not in pipeline.gates or row.publisher_id!=pipeline.gates[iid].contract.metadata.publisher_id:
                raise ValueError('bootstrap_native_identity_mismatch')
            expected=dn.TradeMsg if schema=='trades' else dn.MBP1Msg if schema=='mbp-1' else dn.OHLCVMsg
            if (not isinstance(row,expected) or schema.startswith('ohlcv-') and
                    row.rtype!=(dn.RType.OHLCV_1S if schema=='ohlcv-1s' else dn.RType.OHLCV_1M)):
                raise ValueError('bootstrap_native_schema_mismatch')
            if int(getattr(row,'flags',0))&(4|8|32):raise ValueError('bootstrap_native_quality_flag')
            if row.ts_event<latest.get(iid,0):raise ValueError('bootstrap_event_order_regressed')
            if row.ts_event!=latest.get(iid):ties[iid]=[];identities[iid]=[]
            latest[iid]=row.ts_event;ties[iid].append(hashlib.sha256(raw).hexdigest())
            if schema=='trades' and capture_clock_tolerance_ns:
                from .replay_identity import trade_identity
                identities[iid].append((ties[iid][-1],trade_identity(row),row.ts_recv))
            if len(ties[iid])>10000:raise ValueError('bootstrap_tie_budget_exceeded')
        for iid,g in pipeline.gates.items():
            guard=g.guards.get(schema)
            if guard is None or iid not in latest:raise ValueError('bootstrap_missing_scope_anchor')
            if (ties[iid][-1]!=guard.anchor_sha256
                    or scope.start_ns>latest[iid]):
                raise ValueError('bootstrap_anchor_or_replay_start_mismatch')
            # Latest record's exact native price must also equal the guard anchor.
            # Locate it again without trusting a caller-supplied anchor price.
            _,again=verify(folder)
            matched=None;matched_index=None
            for _,raw in again:
                if hashlib.sha256(raw).hexdigest()==guard.anchor_sha256:
                    row=dn.DBNDecoder(has_metadata=False,input_version=3).write_and_decode(raw)[0]
                    matched=Decimal(row.price if schema=='trades' else row.levels[0].ask_px if schema=='mbp-1' else row.close)/10**9
                    from monatise.adapters.databento_identity import timestamp_ns
                    matched_index=timestamp_ns(row.ts_recv if schema in {'trades','mbp-1'} else row.ts_event)
            if matched!=guard.last:raise ValueError('bootstrap_anchor_price_mismatch')
            # Price screening advances in provider-index order. Live replay
            # still seeks by exchange event time. They are independent native
            # clocks; preserve both even when event time exceeds receive time.
            if matched_index!=guard.anchor_ns:raise ValueError('bootstrap_anchor_provider_index_mismatch')
            cursors.append((f'{schema}:{iid}',latest[iid],tuple(ties[iid])))
            policies.append((f'{schema}:{iid}',guard.policy.sha256))
            if schema=='trades' and capture_clock_tolerance_ns:prefixes.append((f'{schema}:{iid}',tuple(identities[iid])))
    return BootstrapReview(scope.sha256,str(root),tuple(hashes),tuple(cursors),tuple(policies),review_reference,capture_clock_tolerance_ns,clock_equivalence_review_reference,tuple(prefixes))
