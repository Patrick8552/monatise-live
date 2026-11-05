"""Databento field semantics, separate from Monatise strategy thresholds.

Sources reviewed 2026-11-04:
https://databento.com/docs/conventions/common-fields-enums-types
https://databento.com/docs/schemas/ohlcv
"""
F_BAD_TS_RECV = 8
F_MAYBE_BAD_BOOK = 4
F_SNAPSHOT = 32


def record_quality(flags):
    """Snapshot/replay provenance is not itself a corrupted timestamp or book."""
    if type(flags) is not int or not 0 <= flags <= 255:
        raise ValueError('native_uint8_flags_required')
    return tuple(reason for flag, reason in (
        (F_BAD_TS_RECV, 'NATIVE_BAD_TS_RECV'),
        (F_MAYBE_BAD_BOOK, 'NATIVE_MAYBE_BAD_BOOK'),
    ) if flags & flag)


def informational_flags(flags):
    record_quality(flags)
    return ('NATIVE_REPLAY_SNAPSHOT',) if flags & F_SNAPSHOT else ()


def market_event_signature(schema,row):
    """Exchange-event payload identity, independent of capture timing metadata.

    Repeated identical normalized records within one source remain distinct by
    their occurrence count in the caller. Native bytes/receive timestamps stay
    in the source journal and alias audit; they are not rewritten.
    """
    if schema not in ('trades','mbp-1'):
        raise ValueError('native_event_schema_required')
    signature=(schema,int(row.publisher_id),int(row.instrument_id),int(row.ts_event),
        int(row.sequence),str(row.action),str(row.side),int(row.depth),int(row.price),int(row.size),
        int(row.flags)&2)
    if schema=='mbp-1':
        signature+=(tuple((int(p.bid_px),int(p.ask_px),int(p.bid_sz),int(p.ask_sz),
                           int(p.bid_ct),int(p.ask_ct)) for p in row.levels),)
    return signature


class EventOccurrences:
    """Match overlap copies while preserving repeated events inside each source."""
    def __init__(self):
        from collections import Counter
        self.counts=Counter()
        self.ordinals={}

    def key(self,schema,source_hash,ordinal,row):
        signature=market_event_signature(schema,row)
        source_record=(schema,source_hash,ordinal)
        if source_record in self.ordinals:
            prior_signature,occurrence=self.ordinals[source_record]
            if prior_signature!=signature:raise ValueError('SOURCE_ORDINAL_PAYLOAD_CONFLICT')
        else:
            counter_key=(schema,source_hash,signature)
            occurrence=self.counts[counter_key];self.counts[counter_key]+=1
            self.ordinals[source_record]=(signature,occurrence)
        return signature,occurrence
