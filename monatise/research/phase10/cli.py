"""Opt-in local native analysis. This command never connects to a data provider."""
import argparse,json,sys,time,sqlite3
from datetime import datetime
from .access import AnalysisRequest
from .source import load_capture
from . import SAFETY


def main(argv=None):
    parser=argparse.ArgumentParser(description='Read-only native GC/ES/NQ analysis from an existing private capture. No downloads, trading or deployment.')
    parser.add_argument('--capture',help='Existing private capture containing reviewed analysis-inputs.json')
    parser.add_argument('--symbols',nargs='+',help='Exact loaded contracts, e.g. GCZ6 ESZ6 NQZ6')
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
    if not args.capture or not args.symbols:parser.error('--capture and --symbols are required for analysis')
    try:
        cutoff=time.time_ns()
        if args.as_of:
            instant=datetime.fromisoformat(args.as_of.replace('Z','+00:00'))
            if instant.tzinfo is None:raise ValueError('explicit_as_of_timezone_required')
            cutoff=int(instant.timestamp()*10**9)
            if cutoff>time.time_ns():raise ValueError('future_analysis_cutoff_forbidden')
        request=AnalysisRequest(tuple(args.symbols),cutoff,tuple(args.timeframes),tuple(args.mandatory))
        service=load_capture(args.capture,cutoff_ns=cutoff,maximum_records=args.maximum_records)
        result=service.analyse(request)
        from .formatting import text_report
        print(text_report(result) if args.format=='text' else json.dumps(result,sort_keys=True,allow_nan=False));return 0
    except (OSError,ValueError,TypeError,KeyError,ArithmeticError,sqlite3.Error,ImportError) as exc:
        print(json.dumps(dict(availability='UNAVAILABLE',error_type=type(exc).__name__,
            reason='capture_missing_incomplete_invalid_or_outside_read_budget',decision='NO_TRADE',qualification_status='NOT_EVALUATED',**SAFETY)),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
