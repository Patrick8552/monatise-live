"""Offline BTC-only interface. This command never opens provider connections."""
from pathlib import Path
from decimal import Decimal
import argparse,json
from monatise.research.unified.archive import load_archive
from monatise.research.unified.models import encode
from monatise.research.unified.policy import Policy
from monatise.research.unified.store import Store
from .policy import BTCPolicy,RegimePolicy,RiskPolicy
from .service import BTCService
from .history import HistoryStore
from .news import load_review,NewsReview

def load_policy(path):
    x=json.loads(Path(path).read_text());t=x['trend']
    for k in ('fee_ticks_per_side','slippage_ticks_per_side','min_net_rr'):t[k]=Decimal(t[k])
    rg=x.get('regime',{})
    for k in ('trend_efficiency','trend_chop_max','range_efficiency_max','range_chop_min','edge_fraction','boundary_drift_fraction'):
        if k in rg:rg[k]=Decimal(rg[k])
    risk=x.get('risk',{})
    for k in ('max_trade_risk_usd','max_open_risk_usd','max_daily_loss_usd'):
        if k in risk:risk[k]=Decimal(risk[k])
    return BTCPolicy(Policy(**t),RegimePolicy(**rg),RiskPolicy(**risk),x.get('range_enabled',False),x.get('cost_basis','UNVERIFIED_RESEARCH_ASSUMPTIONS'),x.get('analysis_quote_age_ns',60*10**9))
def main():
    p=argparse.ArgumentParser(description='BTC native research only; no orders or downloads')
    p.add_argument('command',choices=('evaluate','history'))
    p.add_argument('--manifest',required=True);p.add_argument('--database',required=True);p.add_argument('--output',required=True)
    p.add_argument('--text-output');p.add_argument('--policy');p.add_argument('--news-review');p.add_argument('--stream',default='btc-upgrade');p.add_argument('--series-id',default='btc-native-reviewed-series');p.add_argument('--cutoff-ns',type=int)
    args=p.parse_args();target=Path(args.output)
    if target.exists():p.error('Choose a new output path; audit artifacts are immutable')
    if args.command=='history':
        store=HistoryStore(args.database)
        try:r=store.admit(args.manifest)
        finally:store.close()
    else:
        if not args.policy:p.error('--policy is required')
        archive=load_archive(args.manifest);cutoff=args.cutoff_ns or json.loads(Path(args.manifest).read_text())['as_of_ns'];store=Store(args.database)
        try:r=BTCService(store,load_policy(args.policy),stream=args.stream,series_id=args.series_id).evaluate(archive.snapshot(cutoff),str(cutoff),news_review=load_review(args.news_review) if args.news_review else NewsReview())
        finally:store.close()
    if args.text_output:
        from .formatting import text_report
        t=Path(args.text_output)
        if t.exists():p.error('Choose a new text output path')
        t.parent.mkdir(parents=True,exist_ok=True);t.write_text(text_report(encode(r)))
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(encode(r),indent=2)+'\n');print(json.dumps({'output':str(target),'execution_eligible':False}))
if __name__=='__main__':main()
