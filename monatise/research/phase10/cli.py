"""Opt-in local native analysis. This command never connects to a data provider."""
import argparse,json,sys,time,sqlite3
from datetime import datetime
from .access import AnalysisRequest
from .source import load_capture
from . import SAFETY


def main(argv=None):
    parser=argparse.ArgumentParser(description='Read-only native GC/ES/NQ analysis from an existing private capture. No downloads, trading or deployment.')
    source=parser.add_mutually_exclusive_group()
    source.add_argument('--capture',help='Existing private capture containing reviewed analysis-inputs.json')
    source.add_argument('--capture-pointer',help='Reviewed local file naming the current exact capture; no discovery or connection')
    instruments=parser.add_mutually_exclusive_group()
    instruments.add_argument('--symbols',nargs='+',help='Exact loaded contracts or unique loaded GC/ES/NQ products')
    instruments.add_argument('--request',help='For example: Analyse GC, ES and NQ using Databento')
    parser.add_argument('--history-manifest',help='Optional separately reviewed native warm-up history')
    parser.add_argument('--timeframes',nargs='+',default=['1m','5m','15m','1h','4h'])
    parser.add_argument('--mandatory',nargs='+',default=['price:1m'])
    parser.add_argument('--as-of',help='Timezone-aware ISO timestamp; default current UTC time')
    parser.add_argument('--maximum-records',type=int,default=2000000)
    parser.add_argument('--format',choices=['json','text'],default='json')
    parser.add_argument('--list-instruments',action='store_true')
    args=parser.parse_args(argv)
    if args.list_instruments:
        from .instruments import audit_catalog
        print(json.dumps(audit_catalog(),sort_keys=True));return 0
    if not (args.capture or args.capture_pointer) or not (args.symbols or args.request):
        parser.error('a capture source and symbols or a read-only request are required')
    try:
        cutoff=time.time_ns()
        if args.as_of:
            instant=datetime.fromisoformat(args.as_of.replace('Z','+00:00'))
            if instant.tzinfo is None:raise ValueError('explicit_as_of_timezone_required')
            cutoff=int(instant.timestamp()*10**9)
            if cutoff>time.time_ns():raise ValueError('future_analysis_cutoff_forbidden')
        from .requests import request_symbols,exact_symbols,capture_from_pointer
        wanted=request_symbols(args.request) if args.request else tuple(args.symbols)
        target=capture_from_pointer(args.capture_pointer) if args.capture_pointer else args.capture
        service=load_capture(target,cutoff_ns=cutoff,maximum_records=args.maximum_records,history_manifest=args.history_manifest)
        request=AnalysisRequest(exact_symbols(wanted,service.pipeline),cutoff,tuple(args.timeframes),tuple(args.mandatory))
        result=service.analyse(request)
        from .formatting import text_report
        print(text_report(result) if args.format=='text' else json.dumps(result,sort_keys=True,allow_nan=False));return 0
    except (OSError,ValueError,TypeError,KeyError,ArithmeticError,sqlite3.Error,ImportError) as exc:
        print(json.dumps(dict(availability='UNAVAILABLE',error_type=type(exc).__name__,
            reason='capture_missing_incomplete_invalid_or_outside_read_budget',decision='NO_TRADE',qualification_status='NOT_EVALUATED',**SAFETY)),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
