"""Initial anchor identity across tiny capture-clock translations; never recovery.

Exchange event/economics/sequence and publisher-send time must match exactly.
Original native bytes are retained. This only skips an already-reviewed anchor
prefix, never admits a new market observation or resets a price guard.
"""
from monatise.research.institutional.models import digest


def trade_identity(record):
    import databento_dbn as dn
    if not isinstance(record,dn.TradeMsg) or record.ts_in_delta in (-2**31,2**31-1):
        raise ValueError('unclamped_native_trade_identity_required')
    return digest((record.publisher_id,record.instrument_id,record.ts_event,record.price,record.size,
        str(record.action),str(record.side),int(record.flags),record.depth,record.sequence,
        record.ts_recv-record.ts_in_delta))


def verified_prefix_hash(record, *, expected, maximum_translation_ns):
    if type(maximum_translation_ns) is not int or not 0<=maximum_translation_ns<=1000:
        raise ValueError('bounded_reviewed_capture_clock_translation_required')
    if (trade_identity(record)!=expected['identity_sha256'] or
            abs(record.ts_recv-expected['ts_recv'])>maximum_translation_ns or
            record.ts_recv//10**9!=expected['ts_recv']//10**9):
        raise ValueError('bootstrap_native_event_identity_or_clock_mismatch')
    return expected['record_sha256']


def book_pair_review(anchor, replayed):
    """Price-free forensic comparison only; never authorizes replay or admission.

    Capture clocks are distinct from venue event/sending clocks. Report their
    observed relationship without rounding bytes or granting a book tolerance.
    """
    import hashlib
    import databento_dbn as dn
    if not isinstance(anchor,dn.MBP1Msg) or not isinstance(replayed,dn.MBP1Msg):
        raise ValueError('two_native_MBP1_records_required')
    fields=('publisher_id','instrument_id','ts_event','price','size','action','side',
            'depth','flags','sequence','levels')
    same=all(getattr(anchor,k)==getattr(replayed,k) for k in fields)
    unclamped=all(r.ts_in_delta not in (-2**31,2**31-1) for r in (anchor,replayed))
    send_equal=unclamped and anchor.ts_recv-anchor.ts_in_delta==replayed.ts_recv-replayed.ts_in_delta
    exact=bytes(anchor)==bytes(replayed)
    return dict(classification='BYTE_IDENTICAL' if exact else
                'REVIEW_REQUIRED_CAPTURE_CLOCK_DIFFERENCE_ONLY' if same and send_equal else 'DIFFERENT_EVENT_OR_BOOK_STATE',
        anchor_sha256=hashlib.sha256(bytes(anchor)).hexdigest(),
        replayed_sha256=hashlib.sha256(bytes(replayed)).hexdigest(),
        exchange_economics_sequence_and_levels_equal=same,publisher_send_time_equal=send_equal,
        receive_difference_ns=replayed.ts_recv-anchor.ts_recv,
        in_delta_difference_ns=replayed.ts_in_delta-anchor.ts_in_delta,
        same_native_receive_second=anchor.ts_recv//10**9==replayed.ts_recv//10**9,
        book_prefix_tolerance_granted=False,admission_authorized=False,raw_bytes_rewritten=False)
