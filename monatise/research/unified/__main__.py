"""Opt-in offline CLI. No changes to application startup or production scripts."""
import argparse
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import json
from .archive import load_archive,read_json
from .models import encode,digest
from .policy import Policy
from .replay import run_replay,run_comparison


def main(argv=None):
    p=argparse.ArgumentParser(description='Isolated native futures shadow replay; never executes orders')
    p.add_argument('command',choices=('replay','inventory','compare','readiness'))
    p.add_argument('--manifest',required=True)
    p.add_argument('--policy')
    p.add_argument('--flow-policy')
    p.add_argument('--database')
    p.add_argument('--output',required=True)
    p.add_argument('--experiment',default='unified')
    p.add_argument('--pathways',default='ABC')
    p.add_argument('--start-ns',type=int)
    p.add_argument('--end-ns',type=int)
    p.add_argument('--split-ns',type=int)
    args=p.parse_args(argv)
    try:
        archive=load_archive(args.manifest)
    except (ValueError,OSError) as exc:
        failure={'schema_version':'unified-input-failure-v1','trade_action':'NO_TRADE',
                 'reason':'SOURCE_VALIDATION_FAILED','detail':str(exc),'instrument':None,
                 'selected_opportunity_id':None,'entry':None,'stop_loss':None,'targets':None,'net_rr':None,
                 'reconsideration':'Provide a valid hash-bound native archive and explicit replay inputs.',
                 'mode':'SHADOW','execution_eligible':False,'orders_created':0}
        path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(failure,indent=2)+'\n')
        print(json.dumps({'output':str(path),'status':'SOURCE_VALIDATION_FAILED','execution_eligible':False}))
        return 2
    if args.command=='inventory':result=archive.report
    else:
        config=read_json(args.policy) if args.policy else {}
        for name in ('fee_ticks_per_side','slippage_ticks_per_side','min_net_rr'):
            if config.get(name) is not None:config[name]=Decimal(config[name])
        policy=Policy(**config)
        if args.command=='readiness':
            from .readiness import btc_readiness
            cutoff=args.end_ns or max([archive.definition_available_ns]+[x.available_ns for rows in
                (archive.bars,archive.trades,archive.quotes,archive.coverage,archive.quote_invalidations) for x in rows])
            result=btc_readiness(archive,policy,cutoff)
        elif args.command=='compare':
            if not args.database:p.error('--database is required for comparison')
            if args.split_ns is None:p.error('--split-ns is required for comparison')
            policies={'bar-participation':policy}
            if args.flow_policy:
                flow=read_json(args.flow_policy)
                for name in ('fee_ticks_per_side','slippage_ticks_per_side','min_net_rr'):
                    if flow.get(name) is not None:flow[name]=Decimal(flow[name])
                policies['aggressor-required']=Policy(**flow)
            result=run_comparison(archive,policies,args.database,split_ns=args.split_ns,
                                  start_ns=args.start_ns,end_ns=args.end_ns,
                                  progress=lambda x:print(json.dumps(x),flush=True))
        else:
            if not args.database:p.error('--database is required for replay')
            result=run_replay(archive,policy,args.database,experiment=args.experiment,
                              pathways=tuple(args.pathways),start_ns=args.start_ns,end_ns=args.end_ns,
                              split_ns=args.split_ns,progress=lambda x:print(json.dumps(x),flush=True))
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(encode(result),indent=2)+'\n')
    print(json.dumps({'output':str(path),'mode':'SHADOW','execution_eligible':False}))


if __name__=='__main__':raise SystemExit(main())
