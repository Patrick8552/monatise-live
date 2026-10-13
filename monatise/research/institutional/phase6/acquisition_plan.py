"""Bounded exact OG proposals over existing cost/cache seams. No downloader."""
from decimal import Decimal

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.acquisition import HistoricalRequest,DownloadPreflight
from ..options_coverage import select
from ..models import digest,encode,number
from . import SAFETY


def requests(definitions, *, underlying,expiration_ns,strikes_fixed,schema,start_ns,end_ns):
    timestamp_ns(start_ns);timestamp_ns(end_ns)
    maximum={'definition':86400,'statistics':5*86400,'mbp-1':15*60}.get(schema)
    if maximum is None or not 0<end_ns-start_ns<=maximum*10**9:
        raise ValueError('bounded_definition_statistics_or_quote_window_required')
    selected=select(definitions,underlying=underlying,expiration_ns=expiration_ns,strikes_fixed=strikes_fixed)
    if not selected:raise ValueError('exact_reviewed_native_OG_definitions_missing')
    if any(not c.metadata.receive_ns<=start_ns<end_ns<=c.metadata.expiration_ns for c in selected):
        raise ValueError('definitions_must_be_available_for_requested_window')
    # One exact contract per proposal simplifies one-use cost and billing attribution.
    return tuple(HistoricalRequest('GLBX.MDP3',schema,(c.identity[1:4],),start_ns,end_ns,
                                   1000 if schema=='definition' else 50000,16*1024**2) for c in selected)


def review(requests, *, cache_plan,metadata_preflight,now_ns,approved_credit_ceiling_usd='0',
           verified_credit_usd=None,credit_expires_ns=None,credit_checked_ns=None,
           credit_review_reference=None,zero_cash_protection_reference=None):
    """Injected metadata_preflight may use SDKHistoricalSource.preflight outside
    the offline worker. This function never reserves a permit or calls download.
    Listing/cost success remains separate from reviewed schema entitlement.
    """
    timestamp_ns(now_ns)
    if not 1<=len(requests)<=8 or len({r.sha256 for r in requests})!=len(requests):
        raise ValueError('bounded_unique_exact_option_proposals_required')
    ceiling=number(approved_credit_ceiling_usd);rows=[];total=Decimal(0)
    if ceiling<0:raise ValueError('nonnegative_credit_only_budget_required')
    for r in requests:
        if (r.dataset!='GLBX.MDP3' or r.schema not in {'definition','statistics','mbp-1'}
                or len(r.contracts)!=1 or not r.contracts[0][2].startswith('OG')):
            raise ValueError('exact_standard_OG_scope_required')
        cached=cache_plan(r);cost=None;preflight=None;reasons=[]
        if cached['new_download_required']:
            if cached['overlapping_request_hashes']:
                reasons.append('overlapping_range_requires_cache_slicing_or_separate_review')
            try:
                p=metadata_preflight(r)
                if (not isinstance(p,DownloadPreflight) or p.request_sha256!=r.sha256
                        or not 0<=now_ns-p.observed_at_ns<=300*10**9
                        or not p.available_from_ns<=r.start_ns<r.end_ns<=p.available_to_ns
                        or not p.schema_available or not p.identities_verified):
                    raise ValueError('reliable_exact_provider_cost_and_scope_required')
                cost=number(p.estimated_usd);preflight=encode(p);total+=cost
                if p.entitlement!='VERIFIED_OPERATOR':reasons.append('schema_entitlement_not_verified')
            except (ValueError,RuntimeError,TypeError):
                reasons.append('reliable_exact_provider_estimate_unavailable')
        elif cached.get('covering_manifests') and not cached.get('uncovered_ranges'):
            cost=Decimal(0)
        else:
            reasons.append('verified_covering_cache_manifest_required')
        rows.append(dict(request=encode(r),request_sha256=r.sha256,cache_plan=cached,
                         estimated_incremental_usd=None if cost is None else str(cost),preflight=preflight,rejection_reasons=reasons))
    reasons=[]
    if any(r['estimated_incremental_usd'] is None for r in rows):reasons.append('unknown_cost_cannot_download')
    if total>ceiling:reasons.append('approved_credit_only_ceiling_exceeded')
    if total>0:
        if (verified_credit_usd is None or number(verified_credit_usd)<total or credit_expires_ns is None
                or credit_expires_ns<=now_ns or credit_checked_ns is None
                or not 0<=now_ns-credit_checked_ns<=300*10**9
                or not credit_review_reference):reasons.append('fresh_verified_unexpired_credit_required')
        if not zero_cash_protection_reference:reasons.append('zero_cash_protection_unestablished')
        reasons.append('fresh_explicit_request_specific_approval_and_one_use_permits_required')
    return dict(status='PROPOSAL_ONLY',rows=rows,total_known_estimated_usd=str(total),
        rejection_reasons=reasons,input_sha256=digest(dict(rows=rows,now_ns=now_ns,ceiling=str(ceiling))),
        acquisition_enabled=False,approval_created=False,cash_authorized=False,**SAFETY)
