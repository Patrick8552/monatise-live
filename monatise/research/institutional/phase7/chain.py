"""Multi-expiry coverage and proposals over existing exact-contract seams."""
from dataclasses import dataclass
from decimal import Decimal

from ..models import Contract, digest, encode
from ..options import OptionConvention
from ..phase6.acquisition_plan import requests, review
from ...databento.options import OpenInterest
from .basis import Quote
from . import SAFETY


@dataclass(frozen=True)
class ChainLeg:
    contract: Contract
    convention: OptionConvention
    quote: Quote | None
    underlying_quote: Quote | None
    open_interest: OpenInterest | None
    definition_available_ns: int
    settlement_reference: str | None
    strike_increment: str | None
    strike_increment_reference: str | None


@dataclass(frozen=True)
class CoveragePolicy:
    reference: str
    # Exact expected (expiration_ns, strike_fixed, kind) tuples from a reviewed
    # catalog. Counts alone never establish completeness; scope is explicit.
    expected: tuple
    catalog_sha256: str | None = None
    catalog_review_reference: str | None = None
    minimum_expirations: int = 2
    minimum_strikes_per_expiry: int = 8
    maximum_quote_age_ns: int = 30 * 10**9
    maximum_oi_age_ns: int = 4 * 86400 * 10**9
    maximum_skew_ns: int = 10**9


def assess(legs, *, underlying, policy, cutoff_ns, evidence_kind):
    if (not isinstance(underlying,Contract) or underlying.metadata.product != 'GC'
            or evidence_kind not in {'AUTHENTIC_ARCHIVED_RECORD','ENGINEERING_SYNTHETIC'}
            or not policy.reference or not 1 <= len(legs) <= 512
            or not 1 <= len(policy.expected) <= 512 or len(set(policy.expected)) != len(policy.expected)
            or policy.minimum_expirations < 2 or policy.minimum_strikes_per_expiry < 2
            or min(policy.maximum_quote_age_ns,policy.maximum_oi_age_ns) <= 0):
        raise ValueError('bounded_reviewed_chain_scope_required')
    rows=[];seen=set();seen_ids=set();missing=[];totals={'C':0,'P':0};concentrations={};unknown=False
    for leg in legs:
        c=leg.contract;m=c.metadata; key=(m.expiration_ns,m.strike_fixed,m.kind)
        reasons=[]
        if key in seen or c.identity in seen_ids: raise ValueError('duplicate_or_ambiguous_option_identity')
        seen.add(key); seen_ids.add(c.identity)
        if (c.asset_class != 'futures_option' or m.product != 'OG' or m.kind not in {'C','P'}
                or m.underlying_id != underlying.metadata.instrument_id
                or m.publisher_id != underlying.metadata.publisher_id or c.multiplier != underlying.multiplier
                or c.multiplier != 100 or c.price_unit != underlying.price_unit
                or not m.receive_ns <= leg.definition_available_ns <= cutoff_ns < m.expiration_ns <= underlying.metadata.expiration_ns):
            reasons.append('invalid_exact_native_option_underlying_definition')
        if (not isinstance(leg.convention,OptionConvention) or leg.convention.family != 'OG'
                or leg.convention.style != 'American' or leg.convention.definition_sha256 != m.definition_sha256
                or not leg.settlement_reference): reasons.append('exercise_or_settlement_unreviewed')
        if not leg.strike_increment or not leg.strike_increment_reference:
            reasons.append('strike_increment_unreviewed')
        else:
            increment=Decimal(leg.strike_increment)
            if not increment.is_finite() or increment<=0 or Decimal(m.strike_fixed)/10**9 % increment:
                reasons.append('strike_off_reviewed_increment')
        q,u=leg.quote,leg.underlying_quote
        if q is None or u is None: reasons.append('missing_two_sided_option_or_underlying_quote')
        else:
            for quote in (q,u):
                try:
                    quote.event.validate(); b,a=Decimal(quote.bid),Decimal(quote.ask)
                    if (not b.is_finite() or not a.is_finite() or not 0<b<=a
                            or a-b>max(Decimal('.1'),(a+b)*Decimal('.1'))
                            or not quote.event.utc_authority_reference
                            or quote.event.source_sha256 != quote.source_sha256
                            or quote.evidence_kind != evidence_kind
                            or not quote.event.nominal_ns <= quote.provider_receive_ns <= cutoff_ns
                            or quote.available_ns > cutoff_ns
                            or not 0<=cutoff_ns-quote.event.lower_ns<=policy.maximum_quote_age_ns):
                        raise ValueError('invalid')
                except (ValueError,TypeError,ArithmeticError): reasons.append('stale_ambiguous_or_invalid_option_inputs')
            if ((q.instrument_id,q.contract)!=(m.instrument_id,m.raw_symbol)
                    or (u.instrument_id,u.contract)!=(underlying.metadata.instrument_id,underlying.metadata.raw_symbol)
                    or q.publisher != u.publisher or u.publisher != 'GLBX.MDP3/XCEC'
                    or max(abs(q.event.lower_ns-u.event.upper_ns),abs(q.event.upper_ns-u.event.lower_ns))>policy.maximum_skew_ns):
                reasons.append('option_underlying_mismatch_or_skew')
        oi=leg.open_interest
        if (not isinstance(oi,OpenInterest) or (oi.publisher_id,oi.instrument_id)!=(m.publisher_id,m.instrument_id)
                or oi.available_ns>cutoff_ns or not 0<=cutoff_ns-oi.reference_ns<=policy.maximum_oi_age_ns):
            reasons.append('missing_stale_or_unavailable_OI'); oi=None; unknown=True
        strike=str(Decimal(m.strike_fixed)/10**9); group=(str(m.expiration_ns),strike)
        concentration=concentrations.setdefault(group,{'C':None,'P':None})
        if oi is not None:
            totals[m.kind]+=oi.contracts;concentration[m.kind]=oi.contracts
        rows.append(dict(contract=encode(c),quote=encode(q),underlying_quote=encode(u),
            open_interest=encode(oi),rejection_reasons=sorted(set(reasons))))
    missing_keys=set(policy.expected)-seen;unexpected=seen-set(policy.expected)
    expiries=sorted({key[0] for key in seen});strikes={e:{k[1] for k in seen if k[0]==e} for e in expiries}
    if missing_keys: missing.append('missing_catalog_strikes_or_kinds')
    if unexpected: missing.append('observations_outside_reviewed_scope')
    if len(expiries)<policy.minimum_expirations: missing.append('incomplete_expirations')
    if any(len(s)<policy.minimum_strikes_per_expiry for s in strikes.values()): missing.append('insufficient_strike_breadth')
    if any((e,s,k) not in seen for e in expiries for s in strikes[e] for k in ('C','P')): missing.append('missing_call_put_pair')
    if (not policy.catalog_review_reference or policy.catalog_sha256 != digest(policy.expected)):
        missing.append('authoritative_catalog_scope_unverified')
    if any(r['rejection_reasons'] for r in rows): missing.append('invalid_or_incomplete_chain_inputs')
    concentration_rows=[dict(expiration_ns=e,strike=s,call_OI=v['C'],put_OI=v['P'],
        combined_OI=None if None in v.values() else sum(v.values()),scope='selected_contracts_only',
        gamma_wall=False,independently_confirmed_positioning=None) for (e,s),v in sorted(concentrations.items())]
    return dict(status='INSUFFICIENT_CHAIN_COVERAGE' if missing else 'REVIEWED_SCOPE_COVERED',
        evidence_kind=evidence_kind, cutoff_ns=cutoff_ns, scope_complete=not missing, complete_exchange_chain=False,
        scope_sha256=digest(policy.expected), scope_review_reference=policy.catalog_review_reference,
        contracts=rows,selected_contracts=len(rows),expiration_count=len(expiries),
        strike_count_by_expiry={str(e):len(s) for e,s in strikes.items()},
        missing_expected=encode(sorted(missing_keys)), rejection_reasons=missing,
        selected_OI_totals=None if unknown else totals, known_OI_subtotals=totals,
        concentrations=concentration_rows, dealer_positioning=None, **SAFETY)


def expanded_requests(definitions, *, underlying, expirations_to_strikes, schema, start_ns,end_ns):
    """Bounded multi-expiry batches; retain existing <=4 strikes/8 legs seams."""
    if not 1<=len(expirations_to_strikes)<=6: raise ValueError('maximum_six_expirations')
    proposals={}
    for expiry,strikes in sorted(expirations_to_strikes.items()):
        if not 1<=len(strikes)<=32 or len(set(strikes))!=len(strikes): raise ValueError('maximum_32_unique_strikes_per_expiry')
        ordered=tuple(sorted(strikes))
        for offset in range(0,len(ordered),4):
            for request in requests(definitions,underlying=underlying,expiration_ns=expiry,
                strikes_fixed=ordered[offset:offset+4],schema=schema,start_ns=start_ns,end_ns=end_ns):
                proposals[request.sha256]=request
    if len(proposals)>384: raise ValueError('bounded_total_contract_requests')
    return tuple(proposals[k] for k in sorted(proposals))


def review_expanded(proposals, *, licensing_reference=None, approved_credit_ceiling_usd='0', **kwargs):
    # Global ceiling must not reset at each batch. Existing cost/credit controls
    # remain authoritative; this planner cannot reserve or consume a permit.
    unique={p.sha256:p for p in proposals}
    if not 1<=len(unique)<=384: raise ValueError('bounded_proposal_count_required')
    ordered=tuple(unique[k] for k in sorted(unique)); batches=[]
    for offset in range(0,len(ordered),8):
        batches.append(review(ordered[offset:offset+8],approved_credit_ceiling_usd=approved_credit_ceiling_usd,**kwargs))
    total=sum((Decimal(b['total_known_estimated_usd']) for b in batches),Decimal(0))
    reasons=sorted({r for b in batches for r in b['rejection_reasons']}
        |{r for b in batches for row in b['rows'] for r in row['rejection_reasons']})
    if total>Decimal(approved_credit_ceiling_usd): reasons.append('global_approved_ceiling_exceeded')
    credit=kwargs.get('verified_credit_usd')
    if total>0 and (credit is None or total>Decimal(str(credit))): reasons.append('global_credit_insufficient')
    if not licensing_reference: reasons.append('reviewed_licensing_and_private_storage_required')
    return dict(status='PROPOSAL_ONLY',unique_requests=len(unique),duplicates_removed=len(proposals)-len(unique),
        batches=batches,total_known_estimated_usd=str(total),rejection_reasons=sorted(set(reasons)),
        acquisition_enabled=False,paid_acquisition_requires_explicit_approval=total>0,
        licensing_reference=licensing_reference, **SAFETY)
