"""Reason-resolved eligibility. Absence is never a published zero or no-OI claim."""
from decimal import Decimal
from ...databento.options import normalize_open_interest
from ..models import encode

OI_STATES=('PUBLISHED_ZERO','PUBLISHED_NONZERO','NOT_PUBLISHED','NOT_CAPTURED','STALE','NOT_ENTITLED','UNKNOWN')


def oi_eligibility(record, *, identity, available_ns, local_cutoff_ns, market_cutoff_ns,
                   captured, entitled, explicit_nonpublication=None):
    if entitled is False:return dict(status='NOT_ENTITLED',value=None,reasons=['documented_entitlement_denial'])
    if not captured:return dict(status='NOT_CAPTURED',value=None,reasons=['outside_complete_requested_replay'])
    if record is None:
        if explicit_nonpublication and explicit_nonpublication.get('publisher_reference') and len(explicit_nonpublication.get('sha256',''))==64:
            return dict(status='NOT_PUBLISHED',value=None,reasons=['explicit_documented_publisher_nonpublication'])
        return dict(status='UNKNOWN',value=None,reasons=['no_OI_in_captured_window_is_not_evidence_of_zero_or_nonpublication'])
    try:
        oi=normalize_open_interest(record,available_ns=available_ns)
        if (oi.publisher_id,oi.instrument_id)!=identity or oi.available_ns>local_cutoff_ns:
            raise ValueError('OI_identity_or_availability_mismatch')
        if not 0<=market_cutoff_ns-oi.reference_ns<=4*86400*10**9:
            return dict(status='STALE',value=None,observed=encode(oi),reasons=['existing_four_day_OI_reference_age_gate'])
        return dict(status='PUBLISHED_ZERO' if oi.contracts==0 else 'PUBLISHED_NONZERO',value=oi.contracts,observed=encode(oi),reasons=[])
    except (ValueError,TypeError,ArithmeticError) as exc:return dict(status='UNKNOWN',value=None,reasons=[str(exc)])


def quote_eligibility(row, *, identity, market_cutoff_ns, available_ns, local_cutoff_ns):
    if row is None:return dict(status='MISSING_INPUT',eligible=False,reasons=['no_observed_quote_record'],bid=None,ask=None)
    top=row.levels[0];reasons=[];b,a=int(top.bid_px),int(top.ask_px)
    bid=None if b>=2**63-1 or b<=0 or top.bid_sz<=0 else str(Decimal(b)/10**9)
    ask=None if a>=2**63-1 or a<=0 or top.ask_sz<=0 else str(Decimal(a)/10**9)
    if (row.publisher_id,row.instrument_id)!=identity:reasons.append('contract_identity_mismatch')
    if bid is None:reasons.append('no_observed_bid')
    if ask is None:reasons.append('no_observed_ask')
    if (bid is None)!=(ask is None):reasons.append('one_sided_market')
    if bid is not None and ask is not None:
        if b>a:reasons.append('crossed_market')
        if Decimal(ask)-Decimal(bid)>max(Decimal('.1'),(Decimal(bid)+Decimal(ask))*Decimal('.1')):reasons.append('invalid_spread_existing_gate')
    if not 0<row.ts_event<=row.ts_recv<=market_cutoff_ns:reasons.append('invalid_provider_event_receive_clock')
    if not 0<=market_cutoff_ns-row.ts_event<=30*10**9:reasons.append('stale_quote_existing_30_second_gate')
    if not 0<available_ns<=local_cutoff_ns:reasons.append('unavailable_at_local_capture_cutoff')
    if int(row.flags)&(4|8|32):reasons.append('invalid_native_quote_flags')
    return dict(status='ELIGIBLE_ARCHIVED_QUOTE' if not reasons else 'STALE' if 'stale_quote_existing_30_second_gate' in reasons else 'MISSING_INPUT',
        eligible=not reasons,reasons=sorted(reasons),bid=bid,ask=ask,event_ns=int(row.ts_event),provider_receive_ns=int(row.ts_recv),
        local_receive_ns=available_ns,sequence=int(row.sequence),flags=int(row.flags),wall_clock_freshness_certified=False)


def pair_eligibility(option,underlying):
    reasons=[]
    if not option['eligible'] or not underlying['eligible']:reasons.append('option_or_underlying_quote_ineligible')
    elif abs(option['event_ns']-underlying['event_ns'])>10**9:reasons.append('option_underlying_timestamp_mismatch_existing_1_second_gate')
    return dict(eligible=not reasons,reasons=reasons)
