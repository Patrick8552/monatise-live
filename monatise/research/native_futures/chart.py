"""Loopback-only chart of the same verified native frames used by analysis.

Export/refresh runs separately from capture. Serving reads a checked snapshot;
no SDK clients, subscriptions, broker APIs, external scripts or order endpoints.
"""
import argparse
from copy import deepcopy
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import time

from monatise.research.institutional.models import digest
from monatise.research.phase10.access import AnalysisRequest
from monatise.research.phase9.rotation import atomic_json
from .cache import checked

TIMEFRAMES=('1m','5m','15m','1h','4h')


def chart_snapshot(service, *, cutoff_ns, capture_id, reader_commit):
    """Never reconstruct bars in JavaScript or make an unverified frame usable."""
    from monatise.research.phase10.market_info import FuturesMarketInfo
    if not isinstance(service,FuturesMarketInfo):raise ValueError('dedicated_native_service_required')
    symbols=tuple(g.contract.metadata.raw_symbol for g in service.pipeline.gates.values())
    report=service.analyse(AnalysisRequest(symbols,cutoff_ns,timeframes=TIMEFRAMES))
    charts={}
    for iid,g in service.pipeline.gates.items():
        symbol=g.contract.metadata.raw_symbol;info=report['instruments'][symbol]
        _,gate,frames,_,_=service._frames(iid,cutoff_ns)
        charts[symbol]={}
        for tf in TIMEFRAMES:
            part=info.get('components',{}).get('price:'+tf,{})
            if info['availability']=='UNAVAILABLE' or not part.get('available'):
                charts[symbol][tf]=dict(available=False,reason=info.get('reason') or part.get('reason') or 'source_unavailable',bars=[])
                continue
            rows=frames.get(tf,())[-512:]
            # _instrument already verified all lineage, calendar and schema faults.
            # The chart must be exactly its native frame, not an approximation.
            native=part['native_analysis']
            if native.get('available') and digest(rows)!=native['source_sha256']:
                raise ValueError('chart_analysis_frame_mismatch')
            bars=[]
            for b in rows:
                prices=[str(Decimal(v)/10**9) for v in b.prices_fixed]
                bars.append(dict(time_ms=b.open_ns//10**6,open_ns=str(b.open_ns),close_ns=str(b.close_ns),
                    open=prices[0],high=prices[1],low=prices[2],close=prices[3],volume=b.volume,
                    bar_sha256=digest(b),source_hashes=list(b.source_hashes),evidence_kind=b.evidence_kind))
            from .technicals import close_indicators
            indicators=close_indicators(tuple(b.prices_fixed[3] for b in rows),include_series=True) if native.get('available') else dict(available=False,reason=native.get('reason'))
            charts[symbol][tf]=dict(available=True,bars=bars,indicators=indicators,frame_sha256=digest(rows),
                analysis_frame_matched=bool(native.get('available')),synthetic_bars=0,
                display_limit=512,total_validated_bars=part['validated_candle_count'])
    # Keep the complete analysis digest while bounding browser-only volume data.
    browser_report=deepcopy(report)
    for info in browser_report['instruments'].values():
        metrics=info.get('components',{}).get('trade_features',{}).get('result',{})
        metrics.pop('cvd_path',None)
        profile=metrics.get('profile',[])
        metrics['profile_total_price_levels']=len(profile)
        metrics['profile']=sorted(profile,key=lambda v:(-v[1],Decimal(v[0])))[:30]
        metrics['profile_display_scope']='TOP_30_EXECUTED_VOLUME_PRICES; SAME_RETAINED_TRADE_WINDOW'
        info['original_analysis_snapshot_sha256']=info.pop('reproducibility_sha256',None)
        info['reproducibility_sha256']=digest(info)
    browser_report['original_analysis_snapshot_sha256']=browser_report.pop('reproducibility_sha256')
    browser_report['browser_projection']='BOUNDED_PROFILE_AND_NO_CVD_PATH'
    browser_report['reproducibility_sha256']=digest(browser_report)
    return dict(version='native-futures-chart-v1',capture_id=str(capture_id),reader_commit=reader_commit,
        exported_at_ns=time.time_ns(),cutoff_ns=cutoff_ns,analysis_sha256=report['reproducibility_sha256'],
        analysis=browser_report,charts=charts,chart_clock='UTC_BUCKET_START',
        price_clock='DATABENTO_OHLCV_TRADE_RECEIVE_TIME',external_chart_feed=False,
        forming_bars_included=False,orders_enabled=False,synthetic_bars=0)


def export_once(capture,snapshot,*,reader_commit,cutoff_ns=None):
    from monatise.research.phase10.source import load_capture
    now=cutoff_ns or time.time_ns()
    service=load_capture(capture,cutoff_ns=now)
    body=chart_snapshot(service,cutoff_ns=now,capture_id=Path(capture).resolve(),reader_commit=reader_commit)
    atomic_json(snapshot,dict(body=body,sha256=digest(body)))
    atomic_json(str(snapshot)+'.status',dict(status='READY',observed_at_ns=time.time_ns(),error=None))
    return dict(status='READY',instruments=len(body['charts']),bars=sum(len(f['bars']) for x in body['charts'].values() for f in x.values()))


def handler_for(snapshot,source_snapshot=None):
    assets={'/':('chart_ui.html','text/html; charset=utf-8'),'/app.js':('chart_ui.js','text/javascript; charset=utf-8')}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass  # No licensed market data in access logs.
        def do_GET(self):
            host=self.headers.get('Host','')
            if host not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:
                self.send_error(403);return
            try:
                if self.path in assets:
                    name,mime=assets[self.path];data=Path(__file__).with_name(name).read_bytes();status=200
                elif self.path=='/api/chart':
                    body=checked(snapshot)
                    if body.get('version')!='native-futures-chart-v1':raise ValueError('native_chart_required')
                    delivery=dict(response_ns=time.time_ns(),current_source_verification='NOT_CONTEMPORANEOUSLY_VERIFIED')
                    state=Path(str(snapshot)+'.status')
                    delivery['refresh']=json.loads(state.read_text()) if state.exists() else dict(status='UNKNOWN')
                    if source_snapshot:
                        source=checked(source_snapshot)
                        if source['capture_id']!=body['capture_id']:raise ValueError('cross_capture_chart_forbidden')
                        delivery.update(source_status_at_observation=source['status'],source_observed_at_ns=source['observed_at_ns'],source_health=source['health'])
                        quotes={}
                        for symbol,latest in source['instruments'].items():
                            info=body['analysis']['instruments'].get(symbol)
                            if info is None or list(info['contract_identity'])!=latest['identity']:
                                raise ValueError('cross_contract_chart_quote_forbidden')
                            quotes[symbol]=latest['quotes']
                        delivery['quote_snapshots']=quotes
                        delivery['quote_scope']='SOURCE_OBSERVATION_ONLY; ANALYTICAL_FEATURES_NOT_RECOMPUTED'
                    data=json.dumps(dict(body=body,sha256=digest(body),delivery=delivery),separators=(',',':')).encode();mime='application/json';status=200
                else:self.send_error(404);return
            except Exception:
                data=b'{"error":"UNAVAILABLE: chart snapshot integrity or refresh requires review"}';mime='application/json';status=503
            self.send_response(status)
            self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers();self.wfile.write(data)
    return Handler


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('export','serve','refresh'));p.add_argument('--snapshot',required=True)
    p.add_argument('--capture');p.add_argument('--reader-commit');p.add_argument('--source-snapshot')
    p.add_argument('--port',type=int,default=8766);p.add_argument('--duration',type=float,default=3600)
    p.add_argument('--interval',type=float,default=30)
    args=p.parse_args(argv)
    if not 1<=args.duration<=28800 or not 1<=args.port<=65535 or not 5<=args.interval<=300:p.error('bounded local service required')
    if args.action in {'export','refresh'}:
        if not args.capture or not args.reader_commit or len(args.reader_commit)!=40:p.error('explicit capture and reader commit required')
        deadline=time.monotonic()+(args.duration if args.action=='refresh' else 0)
        while True:
            try:result=export_once(args.capture,args.snapshot,reader_commit=args.reader_commit)
            except Exception as exc:
                atomic_json(args.snapshot+'.status',dict(status='REFRESH_FAILED',observed_at_ns=time.time_ns(),error=type(exc).__name__))
                raise
            print(json.dumps(result),flush=True)
            remaining=deadline-time.monotonic()
            if remaining<=0:return 0
            time.sleep(min(args.interval,remaining))
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(args.snapshot,args.source_snapshot))
    server.timeout=1;deadline=time.monotonic()+args.duration
    print(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}',access='LOOPBACK_READ_ONLY',duration=args.duration)),flush=True)
    try:
        while time.monotonic()<deadline:server.handle_request()
    finally:server.server_close()
    return 0


if __name__=='__main__':raise SystemExit(main())
