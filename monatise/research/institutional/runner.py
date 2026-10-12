"""Credential-free -I runner; fresh immutable outputs and deterministic repeats."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from importlib.metadata import version

from monatise.research.databento.candles import ResearchArtifactStore
from . import VERSION, BASELINE, SAFETY
from .models import digest


def source_hashes(repository):
    root=Path(repository)
    files=list((root/'monatise').rglob('*.py'))+[root/'tests/research/gc_qualification_fixtures.py']
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def isolated(request_file,output_file):
    repository=Path(__file__).resolve().parents[3]
    output_file=Path(output_file).resolve()
    if output_file.exists(): raise ValueError('fresh_preview_output_required')
    env={'PATH':str(Path(sys.executable).parent)+os.pathsep+'/usr/bin:/bin','LANG':'C'}
    result=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('bootstrap.py')),
        str(repository),str(Path(request_file).resolve()),str(output_file)],env=env,capture_output=True,text=True,timeout=900)
    if result.returncode:
        raise RuntimeError('isolated_institutional_worker_failed: '+result.stderr[-3000:])
    return json.loads(output_file.read_text())


def run(*,output,data_root=None,prepared_file=None):
    root=Path(__file__).resolve().parents[3]
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    if bool(data_root)!=bool(prepared_file): raise ValueError('paired_native_source_paths_required')
    hashes=source_hashes(root)
    request=dict(schema=VERSION,source_baseline=BASELINE,source_hashes=hashes,
        data_root=str(Path(data_root).resolve()) if data_root else None,
        prepared_file=str(Path(prepared_file).resolve()) if prepared_file else None,
        runtime=dict(python=sys.version,databento_dbn=version('databento-dbn')),**SAFETY)
    request['input_sha256']=digest(request)
    with (output/'input.json').open('x') as f: json.dump(request,f,sort_keys=True,indent=2)
    try:
        first=isolated(output/'input.json',output/'preview-01.json')
        second=isolated(output/'input.json',output/'preview-02.json')
        if (first!=second or (output/'preview-01.json').read_bytes()!=(output/'preview-02.json').read_bytes()
                or source_hashes(root)!=hashes):
            raise ValueError('nondeterministic_preview_or_source_change')
        store=ResearchArtifactStore(output/'immutable')
        store.publish('replays',first)
        native=first.get('native_gc')
        if native:
            store.publish('normalized',native['normalized']);store.publish('indicators',native['indicators'])
        summary=dict(schema='phase4-acceptance-v1',source_baseline=BASELINE,source_hashes=hashes,runtime=request['runtime'],
            input_sha256=request['input_sha256'],replay_sha256=hashlib.sha256((output/'preview-01.json').read_bytes()).hexdigest(),
            repeat_equal=True,normalized_gc_sha256=native['normalized_sha256'] if native else None,
            native_gc_counts=native['counts'] if native else None,
            dataset_identities=['GLBX.MDP3'] if native else [],
            native_definitions=[native['contract']] if native else [],
            mapping_status={k:v.get('mapping_status',v.get('preview',{}).get('mapping_status')) for k,v in first['authentic_examples'].items()},
            indicator_availability={k:v['status'] for k,v in native['indicators'].items()} if native else {},
            authentic_preview_status={k:v.get('decision',v.get('preview',{}).get('decision')) for k,v in first['authentic_examples'].items()},
            engineering_preview_status={k:v.get('decision',v.get('preview',{}).get('decision')) for k,v in first['engineering_examples'].items()},
            authentic_options_status=first['authentic_options']['status'],engineering_options_status=first['engineering_options']['status'],
            incremental_provider_usage_usd='0',credit_used_usd='0',actual_downloads=0,
            production_registration=False,**SAFETY)
        store.publish('quality',summary)
        with (output/'summary.json').open('x') as f: json.dump(summary,f,sort_keys=True,indent=2)
        return summary
    except Exception as exc:
        with (output/'quarantine.json').open('x') as f:
            json.dump(dict(status='QUARANTINED_INCOMPLETE_PHASE4_RUN',error_type=type(exc).__name__,**SAFETY),f,sort_keys=True)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-root',type=Path)
    parser.add_argument('--prepared-file',type=Path)
    summary=run(**vars(parser.parse_args()))
    print(json.dumps({k:v for k,v in summary.items() if k not in {'source_hashes','native_definitions'}},sort_keys=True,indent=2))
