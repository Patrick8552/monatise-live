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
