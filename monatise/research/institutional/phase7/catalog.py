"""Read-only lifecycle reduction of the captured OG/GC parent catalogue.

Definition transport/lifecycle coverage is separate from quote, OI, Greek and
whole-exchange coverage. A replay-complete control never certifies the latter.
"""
from collections import Counter
import hashlib
from . import SAFETY


def reduce_definitions(records, *, cutoff_ns, replay_completed, source_reference):
    import databento_dbn as dbn
    if type(cutoff_ns) is not int or cutoff_ns <= 0 or not source_reference:
        raise ValueError('catalog_cutoff_and_source_required')
    latest = {}
    hashes = {}
    count = 0
    observed_identities = set()
    excluded_records = 0
    for available_ns, row in records:
        if not isinstance(row, dbn.InstrumentDefMsg):
            continue
        count += 1
        if count > 200000:
            raise ValueError('bounded_catalog_required')
        if (row.publisher_id != 1 or not 0 < row.ts_event <= row.ts_recv
                or not 0 < available_ns <= cutoff_ns
                or str(row.security_update_action) not in {'A','M','D'}):
            raise ValueError('invalid_native_definition_lifecycle')
        identity = (row.publisher_id, row.instrument_id)
        observed_identities.add(identity)
        # A spread has one native definition per leg at the same timestamp.
        # Preserve those raw records, but never reduce/admit them as outrights.
        if (row.leg_count != 0 or str(row.asset) not in {'OG','GC'}
                or str(row.instrument_class) not in {'C','P','F'}):
            excluded_records += 1
            continue
        index = (int(row.ts_recv), int(row.ts_event))
        native_hash = hashlib.sha256(bytes(row)).hexdigest()
        previous = latest.get(identity)
        if previous is not None and index == previous[0] and native_hash != hashes[identity]:
            raise ValueError('ambiguous_same_clock_definition')
        if previous is None or index > previous[0]:
            latest[identity] = (index, available_ns, row)
            hashes[identity] = native_hash
    if not count:
        raise ValueError('native_definitions_required')
    active = {identity:value for identity,value in latest.items()
              if str(value[2].security_update_action) != 'D' and value[2].expiration > cutoff_ns}
    options = {identity:value for identity,value in active.items()
               if str(value[2].asset) == 'OG' and str(value[2].instrument_class) in {'C','P'}
               and value[2].leg_count == 0 and str(value[2].security_type) == 'OOF'}
    selected = {identity:value for identity,value in options.items() if value[2].underlying_id == 41271}
    keys = [(int(v[2].expiration),int(v[2].strike_price),str(v[2].instrument_class)) for v in selected.values()]
    key_set = set(keys)
    if len(key_set) != len(keys):
        raise ValueError('ambiguous_GCZ6_option_economic_identity')
    missing_pairs = sorted((e,s,k) for e,s,_ in keys for k in ('C','P') if (e,s,k) not in key_set)
    strikes = {}
    for e,s,k in keys:
        strikes.setdefault(str(e),set()).add(s)
    rows = [dict(instrument_id=i[1],raw_symbol=str(v[2].raw_symbol),
                 expiration_ns=int(v[2].expiration),strike_fixed=int(v[2].strike_price),
                 kind=str(v[2].instrument_class),underlying_id=int(v[2].underlying_id),
                 native_sha256=hashes[i],available_ns=v[1],
                 native_receive_ns=int(v[2].ts_recv),user_defined_instrument=str(v[2].user_defined_instrument))
            for i,v in sorted(selected.items())]
    result = dict(status='CAPTURED_PARENT_CATALOGUE' if replay_completed else 'INCOMPLETE_PARENT_REPLAY',
        definition_records=count,unique_native_identities=len(observed_identities),
        reviewed_outright_identities=len(latest),excluded_non_outright_records=excluded_records,
        deleted_latest_definitions=sum(str(v[2].security_update_action)=='D' for v in latest.values()),
        active_OG_outright_count=len(options),selected_GCZ6_option_count=len(selected),
        selected_GCZ6_expiration_count=len(strikes),
        selected_strike_counts={e:len(s) for e,s in sorted(strikes.items())},
        selected_strike_bounds_fixed={e:[min(s),max(s)] for e,s in sorted(strikes.items())},
        missing_call_put_pairs=missing_pairs,selected_contracts=rows,
        underlying_counts={str(k):v for k,v in sorted(Counter(v[2].underlying_id for v in options.values()).items())},
        replay_completed=bool(replay_completed),cutoff_ns=cutoff_ns,source_reference=source_reference,
        whole_exchange_chain_certified=False,quote_scope_certified=False,OI_clearing_finality_certified=False,
        clock_certified=False,**SAFETY)
    return result, {i[1]:(v[1],v[2]) for i,v in active.items()}
