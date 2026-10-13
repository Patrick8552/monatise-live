"""Exchange-side CVD bounds and separate conservative quote-rule diagnostics."""
from bisect import bisect_left
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import json

from monatise.research.databento.datasets import InstrumentMetadata
from monatise.research.databento.archive import NativeDBNArchive, dbn_records, sha256_file
from ..models import Contract, Source, MarketObservation, digest, encode, number
from ..normalize import observation
from ..indicators import unique, provenance
from . import SAFETY


def contract_from(value):
    m = dict(value['metadata']); m['native_terms'] = tuple(tuple(t) for t in m['native_terms'])
    v = dict(value); v['metadata'] = InstrumentMetadata(**m)
    v['tick_size'],v['multiplier'] = number(v['tick_size']),number(v['multiplier'])
    return Contract(**v)


def observation_from(value):
    v = dict(value); v['contract'] = contract_from(v['contract']); v['source'] = Source(**v['source'])
    if v['schema'] in {'mbp-1','mbp-10'}:
        v['payload'] = tuple(tuple(level) for level in v['payload'])
    else:
        v['payload'] = tuple(v['payload'])
    return MarketObservation(**v)


def evaluate(trades, *, quotes=(), start_ns, end_ns, session_reference,
             maximum_quote_age_ns=250_000_000, cutoff_ns=None, mode='RETROSPECTIVE_DIAGNOSTICS',quote_candidates=None):
    if (type(maximum_quote_age_ns) is not int or not 0 < maximum_quote_age_ns <= 10**9
            or mode not in {'RETROSPECTIVE_DIAGNOSTICS','POINT_IN_TIME'}
            or mode == 'POINT_IN_TIME' and cutoff_ns is None):
        raise ValueError('bounded_quote_classification_policy_required')
    values = unique(trades,schema='trades',start_ns=start_ns,end_ns=end_ns,capacity=100000)
    books = unique(quotes,schema='mbp-1',start_ns=start_ns,end_ns=end_ns,capacity=100000)
    if values and any(q.contract != values[0].contract or q.source.evidence_kind != values[0].source.evidence_kind for q in books):
        raise ValueError('quote_trade_contract_or_evidence_mismatch')
    if mode == 'POINT_IN_TIME' and any(max(v.source.admission_ns,v.receive_ns) > cutoff_ns for v in (*values,*books)):
        raise ValueError('future_local_availability_cannot_be_backdated')
    clocks = [q.receive_ns for q in books]
    buy = sell = unknown = inferred_buy = inferred_sell = 0
    details, path = [], []
    for trade in values:
        price,size,side = trade.payload
        if side == 'BUY': buy += size
        elif side == 'SELL': sell += size
        else:
            unknown += size
            i = bisect_left(clocks,trade.receive_ns)-1
            q = books[i] if i >= 0 else None
            if quote_candidates is not None:
                q=quote_candidates.get(trade.source.position)
                if q is not None and q not in books:
                    raise ValueError('candidate_quote_provenance_missing')
            inferred = None; reason = 'no_preceding_captured_quote'
            if q:
                reason = 'quote_not_causally_compatible'
                # Same sequence can be a post-trade snapshot from the same packet.
                # Never skip a bad newest quote to cherry-pick an older useful one.
                if (q.event_ns < trade.event_ns and q.receive_ns < trade.receive_ns
                        and trade.receive_ns-q.receive_ns <= maximum_quote_age_ns
                        and q.sequence is not None and trade.sequence is not None
                        and q.sequence < trade.sequence and not q.flags & (4|8|32)):
                    bid,bs,_,ask,ass,_ = q.payload[0]
                    reason = 'one_sided_or_locked_quote'
                    if bid is not None and ask is not None and bs > 0 and ass > 0 and number(bid) < number(ask):
                        # Exact touch only; outside-spread executions may be spreads,
                        # corrections or stale quotes. They remain unresolved.
                        inferred = 'BUY' if number(price) == number(ask) else 'SELL' if number(price) == number(bid) else None
                        reason = 'exact_preceding_quote_touch' if inferred else 'inside_or_outside_preceding_spread'
            if inferred == 'BUY': inferred_buy += size
            if inferred == 'SELL': inferred_sell += size
            details.append(dict(trade=encode(trade),preceding_quote=encode(q) if q else None,
                                inferred_side=inferred,reason=reason,exchange_reported_side=None))
        path.append(dict(receive_ns=trade.receive_ns,source_position=trade.source.position,
                         known_cvd=buy-sell,unknown_volume=unknown,lower=buy-sell-unknown,upper=buy-sell+unknown))
    total = buy+sell+unknown; remaining = unknown-inferred_buy-inferred_sell
    inputs = provenance(values,start_ns=start_ns,end_ns=end_ns,session_reference=session_reference)
    return dict(status='UNAVAILABLE' if not total else 'INCOMPLETE_CVD' if unknown else 'CAPTURED_EXCHANGE_SIDES',
        buy_volume=buy,sell_volume=sell,unknown_volume=unknown,executed_contracts=total,
        cvd_known=buy-sell,cvd_lower=buy-sell-unknown,cvd_upper=buy-sell+unknown,
        classified_volume_coverage=str(Decimal(buy+sell)/total) if total else None,
        full_exchange_side_cvd=buy-sell if not unknown and total else None,
        bounds_path=path,unknown_trade_investigation=details,
        quote_inference=dict(buy_volume=inferred_buy,sell_volume=inferred_sell,unresolved_volume=remaining,
            combined_delta=buy-sell+inferred_buy-inferred_sell,
            combined_lower=buy-sell+inferred_buy-inferred_sell-remaining,
            combined_upper=buy-sell+inferred_buy-inferred_sell+remaining,
            inferred_is_exchange_reported=False,certified=False),
        inputs=inputs,quotes_sha256=digest(books),cutoff_ns=cutoff_ns,mode=mode,
        methodology='exchange-side-CVD-plus-unknown-volume-bounds-v1',
        quote_rule='strictly-earlier-event-receive-sequence-exact-touch-v1',
        maximum_quote_age_ns=maximum_quote_age_ns,complete_window_certified=False,
        limitation='Captured-window uncertainty bounds; preceding quotes are a heuristic, not recovered exchange sides. '
                   'Archive admission remains retrospective; no historical live availability is asserted.',**SAFETY)


def investigate_cached(native, *, data_root, prepared_file):
    """Read original MBP-1 positions only; preserve accepted Phase 5 observations."""
    manifest = next(m for m in native['manifests'] if m['schema'] == 'mbp-1')
    prepared = json.loads(Path(prepared_file).read_text()); found = None
    for item in prepared['source_archives']:
        if item['schema'] != 'mbp-1' or item['manifest_sha256'] != manifest['manifest_sha256']:
            continue
        path = Path(data_root)/item['manifest_file']
        if sha256_file(path) != item['manifest_sha256']:
            raise ValueError('cached_quote_manifest_changed')
        value = json.loads(path.read_text()); value = value.get('result',value)
        if value['archive_sha256'] != manifest['archive_sha256']:
            raise ValueError('cached_quote_archive_changed')
        found = value
    if not found:
        raise ValueError('accepted_quote_provenance_required')
    archive = NativeDBNArchive.open_existing(Path(data_root)/'native-dbn')
    path = archive.verify(manifest['archive_sha256'])
    contract = contract_from(native['contract'])
    trades = tuple(observation_from(t) for t in native['normalized']['trades'])
    unknowns = [t for t in trades if t.payload[2] is None]
    selected = []; candidates={}; last = None; target = 0
    import databento_dbn as dbn
    for ordinal,row in enumerate(r for r in dbn_records(path) if not isinstance(r,dbn.Metadata)):
        if target == len(unknowns): break
        while target < len(unknowns) and row.ts_recv >= unknowns[target].receive_ns:
            candidates[unknowns[target].source.position]=None
            if last is not None:
                original,index = last
                # A bad newest quote is a diagnostic rejection, not a reason to
                # normalize or fall back to an older quote.
                if original.flags & (4|8|32):
                    last = None
                else:
                    candidate=observation(original,schema='mbp-1',contract=contract,
                        archive_sha256=manifest['archive_sha256'],ordinal=index,
                        retrieval_ns=found['retrieval_ns'],admission_ns=found['ingestion_ns'],
                        evidence_kind='AUTHENTIC_ARCHIVED_RECORD',enabled_schemas=('mbp-1',))
                    selected.append(candidate)
                    candidates[unknowns[target].source.position]=candidate
            target += 1
        last = (row,ordinal)
    if target < len(unknowns):
        raise ValueError('quote_archive_ended_before_target_trade')
    if sha256_file(path)!=manifest['archive_sha256']:
        raise ValueError('cached_quote_source_changed_during_investigation')
    return evaluate(trades,quotes=selected,quote_candidates=candidates,**native['scope'])
