"""Receive-clock provider interval states; never interpolation or trade repair."""
from monatise.research.databento.candles import WIDTHS

INTERVAL_STATES=('VERIFIED_NO_TRADE','UNKNOWN_COVERAGE','MISSING_OR_REJECTED','OBSERVED_VALID','DISPLAY_INTERPOLATED')


def native_intervals(gate,bars, *, schema,start_ns,end_ns,cutoff_ns,source_unreliable=False):
    step=WIDTHS[schema[6:]]
    if start_ns%step or end_ns%step or not 0<end_ns-start_ns<=100000*step:
        raise ValueError('bounded_aligned_interval_scope_required')
    seen={b.open_ns:b for b in bars if b.schema==schema}
    proofs=tuple(gate.coverage_reviews.values());counts={};intervals=[]
    fault=gate.fault_event_ns.get(schema)
    for start in range(start_ns,end_ns,step):
        bar=seen.get(start)
        proof=next((r for r in proofs if r.available_ns<=cutoff_ns and r.covers(gate.contract.identity,schema,start,start+step)),None)
        rejected=fault is not None and start+step>fault
        state=('MISSING_OR_REJECTED' if rejected else 'OBSERVED_VALID' if bar and bar.retrieval_ns<=cutoff_ns
            else 'VERIFIED_NO_TRADE' if proof and not source_unreliable else 'UNKNOWN_COVERAGE')
        counts[state]=counts.get(state,0)+1
        intervals.append(dict(open_ns=start,state=state,analytical_eligible=not source_unreliable and not rejected and state in {'OBSERVED_VALID','VERIFIED_NO_TRADE'},
            coverage_sha256=proof.sha256 if proof else None))
    return dict(schema=schema,price_clock='PROVIDER_RECEIVE_TIME',counts=counts,intervals=intervals,
        verification_scope='COMPLETE_CAPTURED_PROVIDER_STREAM_WITH_NATIVE_INTERVAL_CONTROL',
        independent_exchange_truth=False,interpolated_bars=0,synthetic_volume=0)
