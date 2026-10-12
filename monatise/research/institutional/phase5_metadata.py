"""Exact ES/NQ metadata and estimates only; cannot submit historical downloads."""
import argparse
from dataclasses import asdict
from datetime import UTC,datetime,timedelta
import getpass
import json
import os
from pathlib import Path
import time

from monatise.research.databento.acquisition import SDKHistoricalSource,HistoricalRequest
from .models import digest,encode
from .native import START_NS,END_NS


def proposal(source, *, start_ns=START_NS,end_ns=END_NS,now_ns,include_mbp1=False,ledger=None,archive=None):
    """Injected SDK seam is mocked in tests; metadata success is not entitlement.

    Native definitions/economics and reviewed licenses remain mandatory before
    purchase. The private SDK client is reused at its pinned 0.87.0 interface.
    """
    if (type(include_mbp1) is not bool or start_ns!=START_NS or end_ns not in {END_NS,START_NS+1200*10**9}
            or end_ns>now_ns or bool(ledger)!=bool(archive)):
        raise ValueError('bounded_phase5_sample_and_paired_cache_control_required')
    client=source._client
    publishers=client.metadata.list_publishers()
    feed=[p['publisher_id'] for p in publishers if (p['dataset'],p['venue'])==('GLBX.MDP3','GLBX')]
    if len(feed)!=1:raise ValueError('unambiguous_authenticated_feed_publisher_required')
    start_date=datetime.fromtimestamp(start_ns//10**9,UTC).date()
    end_date=start_date+timedelta(days=1)
    symbols=('ESZ6','NQZ6')
    mapping=client.symbology.resolve(dataset='GLBX.MDP3',symbols=list(symbols),stype_in='raw_symbol',
        stype_out='instrument_id',start_date=start_date,end_date=end_date)
    if mapping.get('partial') or mapping.get('not_found'):raise ValueError('complete_symbol_resolution_required')
    requests=[]
    for symbol in symbols:
        intervals=mapping.get('result',{}).get(symbol,[])
        selected=[r for r in intervals if r['d0']<=str(start_date)<r['d1']]
        if len(selected)!=1 or selected[0]['d1']<str(end_date):
            raise ValueError('exact_day_instrument_resolution_required')
        iid=int(selected[0]['s'])
        for schema in ('definition','trades','ohlcv-1m')+(('mbp-1',) if include_mbp1 else ()):
            # Resolve the latest definition published before the analysis window;
            # intraday price/trade acquisition keeps the exact 15/20-minute scope.
            left=start_ns//(86400*10**9)*(86400*10**9) if schema=='definition' else start_ns
            right=start_ns if schema=='definition' else end_ns
            request=HistoricalRequest('GLBX.MDP3',schema,((feed[0],iid,symbol),),left,right,
                record_limit=1000 if schema=='definition' else 100000,wire_byte_limit=16*1024**2)
            estimate=source.preflight(request,now_ns=now_ns)
            if (estimate.request_sha256!=request.sha256 or not estimate.schema_available or not estimate.identities_verified
                    or not estimate.available_from_ns<=left<right<=estimate.available_to_ns):
                raise ValueError('reliable_exact_request_metadata_and_quote_required')
            plan=ledger.plan(request,archive=archive) if ledger else dict(status='CACHE_INSPECTION_REQUIRED')
            requests.append(dict(request=asdict(request),preflight=asdict(estimate),preflight_sha256=estimate.sha256,
                                 cache_plan=plan,native_definition_review='REQUIRED',request_receipt=None))
    return dict(schema='monatise-phase5-exact-metadata-proposal-v1',observed_at_ns=now_ns,requests=requests,
        metadata_sha256=digest(dict(publishers=publishers,symbology=mapping)),
        dataset='GLBX.MDP3',native_definition_economics_verified=False,entitlement='UNVERIFIED',
        credit_balance=None,numeric_credit_only_ceiling=None,residual_cash_exposure=None,
        acquisition_enabled=False,actual_downloads=0,
        pending=['review_exact_native_definitions_economics_and_licenses','current_credit_and_cash_exposure',
                 'cache_and_overlap_review','numeric_credit_only_ceiling','request_specific_one_use_receipts'],
        limitation='Read-only metadata proposal; no credit/billing guarantee or purchase approval is created.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--prompt-key',action='store_true')
    p.add_argument('--include-mbp1',action='store_true');p.add_argument('--portal-window',action='store_true')
    args=p.parse_args()
    if args.output.exists():raise SystemExit('Fresh proposal output required.')
    key=os.environ.get('DATABENTO_API_KEY','').strip()
    if not key and args.prompt_key:key=getpass.getpass('Databento API key (hidden, not saved): ').strip()
    if not key:
        result=dict(schema='monatise-phase5-exact-metadata-proposal-v1',status='BLOCKED_SECURE_API_CREDENTIAL_UNAVAILABLE',
                    acquisition_enabled=False,actual_downloads=0)
    else:
        try:
            result=proposal(SDKHistoricalSource(key=key),now_ns=time.time_ns(),include_mbp1=args.include_mbp1,
                            end_ns=START_NS+1200*10**9 if args.portal_window else END_NS)
        except Exception:
            result=dict(schema='monatise-phase5-exact-metadata-proposal-v1',status='METADATA_CHECK_INCOMPLETE',
                        acquisition_enabled=False,actual_downloads=0,error='Provider details suppressed; no data request made.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as out:json.dump(encode(result),out,sort_keys=True,indent=2,allow_nan=False)
    print(json.dumps(dict(output=str(args.output),sha256=digest(result),status=result.get('status','PROPOSAL_READY'),actual_downloads=0)))
