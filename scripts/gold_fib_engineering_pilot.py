"""Run bounded synthetic engineering cases; does not measure trading performance."""
import argparse
from pathlib import Path

from monatise.research.gold_fib.diagnostics import diagnostics
from monatise.research.gold_fib.models import FrozenRecord
from monatise.research.gold_fib.replay import OfflineReplay, write_immutable
from tests.research.gold_fib_fixtures import archive, range_gate_archive, repeated_setup_archive


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    combined=[]; runs=[]
    for side in ('long','short'):
        for case in ('two-setups','unconfirmed-B','origin-latency','late-history','two-atr','distance-one','distance-two','aged'):
            kw={'short':side=='short'}
            if case=='two-setups':
                data=repeated_setup_archive(**kw)
            elif case in {'two-atr','distance-one','distance-two'}:
                data=range_gate_archive(**kw,case=case)
            else:
                data=archive(**kw,forming_b=case=='unconfirmed-B',
                    origin_latency=case=='origin-latency',late_history=case=='late-history',aged=case=='aged')
            label=side+'-'+case
            input_record=FrozenRecord.from_value(data)
            write_immutable(args.output/'inputs'/f'{label}.json',input_record.payload+'\n')
            result=OfflineReplay().run(data)
            write_immutable(args.output/'runs'/f'{label}.json',result.payload+'\n')
            rows=result.data['records']
            combined.extend([{**r,'engineering_scenario':label} for r in rows])
            runs.append({'case':label,'input_sha256':input_record.sha256,
                'replay_sha256':result.sha256,'seed_events':len(rows),
                'seed_rejections':result.data['seed_rejections']})
    report=FrozenRecord.from_value({'evidence_kind':'ENGINEERING_SYNTHETIC',
        'warning':'Artificial scenarios are not a representative market dataset. Counterfactual cases test guards; repeated-setup cases test clustering.',
        'runs':runs,'diagnostics':diagnostics(combined),'records':combined})
    write_immutable(args.output/'pilot.json',report.payload+'\n')
    write_immutable(args.output/'pilot-sha256.txt',report.sha256+'\n')
    print(f'{len(combined)} synthetic seed events; '+str(report.data['diagnostics']['episode_cluster_count'])+' identified episode clusters')


if __name__=='__main__':
    main()
