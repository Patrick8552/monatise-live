"""Versioned isolated repeatable Phase 5 acceptance, with no acquisition client."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from importlib.metadata import version

from monatise.research.databento.candles import ResearchArtifactStore
from . import SAFETY
from .models import digest,encode
from .runner import source_hashes,isolated

BASELINE='3007cbc96082a0c09078e3160482dcdd4cdd3af1'


def run(*,output,data_root=None,prepared_file=None,account_observation=None,broker_inputs=None,esnq_root=None):
    root=Path(__file__).resolve().parents[3]
    if bool(data_root)!=bool(prepared_file):raise ValueError('paired_native_source_paths_required')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    hashes=source_hashes(root)
    request=dict(schema='monatise-phase5-research-v1',baseline=BASELINE,source_hashes=hashes,
        runtime=dict(python=sys.version,databento_dbn=version('databento-dbn'),databento=version('databento')),
        data_root=str(Path(data_root).resolve()) if data_root else None,
        prepared_file=str(Path(prepared_file).resolve()) if prepared_file else None,
        account_observation=account_observation,broker_inputs=encode(broker_inputs or {}),
        esnq_root=str(Path(esnq_root).resolve()) if esnq_root else None,**SAFETY)
    request['input_sha256']=digest(request)
    with (output/'input.json').open('x') as out:json.dump(encode(request),out,sort_keys=True,indent=2)
    try:
        a=isolated(output/'input.json',output/'preview-01.json',bootstrap='phase5_bootstrap.py')
        b=isolated(output/'input.json',output/'preview-02.json',bootstrap='phase5_bootstrap.py')
        if (a!=b or (output/'preview-01.json').read_bytes()!=(output/'preview-02.json').read_bytes()
                or hashes!=source_hashes(root)):raise ValueError('phase5_repeat_or_source_mismatch')
        native=a.get('native_gc')
        summary=dict(schema='monatise-phase5-acceptance-v1',baseline=BASELINE,source_hashes=hashes,
            runtime=request['runtime'],input_sha256=request['input_sha256'],repeat_equal=True,
            replay_sha256=hashlib.sha256((output/'preview-01.json').read_bytes()).hexdigest(),
            normalized_gc_sha256=native['normalized_sha256'] if native else None,
            native_gc_counts=native['counts'] if native else None,
            native_esnq_counts={k:v['counts'] for k,v in (a.get('new_native_esnq') or {}).get('products',{}).items()},
            native_esnq_normalized_sha256={k:v['normalized_sha256'] for k,v in (a.get('new_native_esnq') or {}).get('products',{}).items()},
            new_data_billing_quarantined=(a.get('new_native_esnq') or {}).get('quarantined_for_billing'),
            authentic_status={k:v['analytical_qualification'] for k,v in a['authentic_previews'].items()},
            engineering_decisions={k:v['decision'] for k,v in a['engineering_previews'].items()},
            authentic_options_status=a['authentic_options']['status'],
            incremental_usage_usd='0',credit_used_usd='0',cash_spent_usd='0',actual_downloads=0,
            source_acquisition_downloads=a.get('source_acquisition_downloads',0),worker_network_downloads=0,**SAFETY)
        store=ResearchArtifactStore(output/'immutable')
        store.publish('replays',a);store.publish('quality',summary)
        if native:
            store.publish('normalized',native['normalized']);store.publish('indicators',native['indicators'])
        if a.get('new_native_esnq'):
            ResearchArtifactStore(output/'quarantine-diagnostics').publish('quality',a['new_native_esnq'])
        with (output/'summary.json').open('x') as out:json.dump(summary,out,sort_keys=True,indent=2)
        return summary
    except Exception as exc:
        with (output/'quarantine.json').open('x') as out:json.dump(dict(status='QUARANTINED_INCOMPLETE_PHASE5_RUN',
            error_type=type(exc).__name__,**SAFETY),out,sort_keys=True)
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--data-root',type=Path)
    p.add_argument('--prepared-file',type=Path);p.add_argument('--account-review',type=Path)
    p.add_argument('--esnq-root',type=Path)
    args=vars(p.parse_args());account=args.pop('account_review')
    args['account_observation']=json.loads(account.read_text()) if account else None
    summary=run(**args)
    print(json.dumps({k:v for k,v in summary.items() if k!='source_hashes'},sort_keys=True,indent=2))
