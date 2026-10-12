"""Bounded standard OG definition/OI coverage, not a dealer-positioning model."""
from decimal import Decimal
from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.options import OpenInterest
from .models import Contract,digest,encode
from .options import OptionConvention


def select(definitions, *, underlying, expiration_ns, strikes_fixed, kinds=('C','P'), capacity=8):
    timestamp_ns(expiration_ns)
    if (not isinstance(underlying,Contract) or underlying.metadata.product!='GC'
            or underlying.asset_class!='futures' or type(capacity) is not int or not 1<=capacity<=8
            or not isinstance(strikes_fixed,tuple) or not 1<=len(strikes_fixed)<=4
            or len(set(strikes_fixed))!=len(strikes_fixed)
            or any(type(s) is not int or s<=0 for s in strikes_fixed)
            or not isinstance(kinds,tuple) or not kinds or len(set(kinds))!=len(kinds)
            or not set(kinds)<={'C','P'} or len(definitions)>1000):
        raise ValueError('bounded_explicit_standard_OG_selection_required')
    chosen=[];seen=set()
    for value in definitions:
        if not isinstance(value,Contract):raise ValueError('native_normalized_definitions_required')
        m=value.metadata
        if m.product!='OG' or m.expiration_ns!=expiration_ns or m.strike_fixed not in strikes_fixed or m.kind not in kinds:
            continue
        if (value.asset_class!='futures_option' or m.underlying_id!=underlying.metadata.instrument_id
                or m.publisher_id!=underlying.metadata.publisher_id
                or value.multiplier!=underlying.multiplier or m.expiration_ns>underlying.metadata.expiration_ns):
            raise ValueError('exact_option_underlying_economics_required')
        identity=value.identity
        if identity in seen:raise ValueError('ambiguous_option_definition_revision')
        seen.add(identity);chosen.append(value)
    if len(chosen)>capacity:raise ValueError('option_selection_capacity_exceeded')
    return tuple(sorted(chosen,key=lambda c:(c.metadata.strike_fixed,c.metadata.kind,c.identity)))


def coverage(contracts, *, underlying, conventions, open_interest=(), cutoff_ns, evidence_kind,
             settlement_reference=None):
    timestamp_ns(cutoff_ns)
    if evidence_kind not in {'AUTHENTIC_ARCHIVED_RECORD','ENGINEERING_SYNTHETIC'} or len(contracts)>8:
        raise ValueError('bounded_labelled_options_coverage_required')
    identities=set();ois={};rows=[];totals={};strikes={};missing_kinds=set();missing_strikes=set()
    for oi in open_interest:
        if not isinstance(oi,OpenInterest) or oi.available_ns>cutoff_ns:
            raise ValueError('published_available_option_OI_required')
        key=(oi.publisher_id,oi.instrument_id)
        if key in ois:raise ValueError('ambiguous_OI_observation')
        ois[key]=oi
    for c in contracts:
        m=c.metadata;key=(m.publisher_id,m.instrument_id);convention=conventions.get(m.definition_sha256)
        if (c.identity in identities or c.asset_class!='futures_option' or m.product!='OG'
                or m.underlying_id!=underlying.metadata.instrument_id or m.publisher_id!=underlying.metadata.publisher_id
                or underlying.metadata.product!='GC' or c.multiplier!=underlying.multiplier
                or not m.receive_ns<=cutoff_ns<m.expiration_ns<=underlying.metadata.expiration_ns
                or not isinstance(convention,OptionConvention) or convention.family!='OG'
                or convention.definition_sha256!=m.definition_sha256):
            raise ValueError('reviewed_live_standard_OG_definition_required')
        identities.add(c.identity);oi=ois.pop(key,None)
        rows.append(dict(contract=encode(c),exercise=convention.style,
            settlement_reference=settlement_reference,open_interest=encode(oi) if oi else None,
            option_quotes=None,underlying_quotes=None,iv=None,gamma=None))
        strike=str(Decimal(m.strike_fixed)/10**9)
        totals.setdefault(m.kind,0);strikes.setdefault(strike,0)
        if oi:
            totals[m.kind]+=oi.contracts;strikes[strike]+=oi.contracts
        else:
            missing_kinds.add(m.kind);missing_strikes.add(strike)
    if ois:raise ValueError('OI_outside_selected_contracts')
    count=sum(r['open_interest'] is not None for r in rows)
    return dict(status='OBSERVED_PARTIAL_CHAIN' if rows else 'UNAVAILABLE',evidence_kind=evidence_kind,
        underlying=encode(underlying),contracts=rows,cutoff_ns=cutoff_ns,
        selected_contracts=len(rows),contracts_with_published_OI=count,
        selected_call_put_contracts={k:totals.get(k) if k not in missing_kinds else None for k in ('C','P')} if count else None,
        selected_strike_contracts={s:n if s not in missing_strikes else None for s,n in strikes.items()} if count else None,
        observed_call_put_contracts={k:n for k,n in totals.items() if any(r['contract']['metadata']['kind']==k and r['open_interest'] is not None for r in rows)} if count else None,
        observed_strike_contracts={s:n for s,n in strikes.items() if any(str(Decimal(r['contract']['metadata']['strike_fixed'])/10**9)==s and r['open_interest'] is not None for r in rows)} if count else None,
        complete_chain=False,concentration_scope='selected_contracts_only',
        missing=['option_and_underlying_quotes','dated_rate_assumption']+([] if settlement_reference else ['reviewed_settlement_convention'])
                +(['published_open_interest'] if count<len(rows) else []),
        inputs_sha256=digest(dict(rows=rows,underlying=underlying,cutoff_ns=cutoff_ns,evidence_kind=evidence_kind)),
        signed_dealer_gex=None,gamma_flip=None,institutional_positioning=None,
        gil_enabled=False,execution_eligible=False,
        limitation='Selected aggregate OI is not dealer inventory; absence is null, not zero. American gamma remains uncertified.')
