"""Versioned credential-free Phase 6 acceptance; no provider acquisition API."""
import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys

from monatise.research.databento.candles import ResearchArtifactStore
from monatise.research.databento.archive import sha256_file
from ..runner import source_hashes
from ..models import digest,encode
from .billing import reservations
from . import BASELINE,VERSION,SAFETY


def isolated(request_file,output_file):
    repository=Path(__file__).resolve().parents[4]
    if Path(output_file).exists():raise ValueError('fresh_phase6_output_required')
    env={'PATH':str(Path(sys.executable).parent)+os.pathsep+'/usr/bin:/bin','LANG':'C'}
    process=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('bootstrap.py')),
        str(repository),str(Path(request_file).resolve()),str(Path(output_file).resolve())],
        env=env,capture_output=True,text=True,timeout=900)
    if process.returncode:
        raise RuntimeError('phase6_isolated_worker_failed: '+process.stderr[-3000:])
    return json.loads(Path(output_file).read_text())


def run(*,output,data_root=None,prepared_file=None,esnq_root=None,ledger_path=None,
        provider_records=(),billing_review=None,admission_review=None,broker_inputs=None,
        provider_account_observation=None,frozen_H1_evidence=None):
    repository=Path(__file__).resolve().parents[4]
    if bool(data_root)!=bool(prepared_file) or bool(esnq_root)!=bool(ledger_path):
        raise ValueError('paired_native_sources_and_ledger_required')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False);output.chmod(0o700)
    hashes=source_hashes(repository); ledger_hash=sha256_file(ledger_path) if ledger_path else None
    request=dict(schema=VERSION,baseline=BASELINE,source_hashes=hashes,
        runtime=dict(python=sys.version,databento=version('databento'),databento_dbn=version('databento-dbn')),
        data_root=str(Path(data_root).resolve()) if data_root else None,
        prepared_file=str(Path(prepared_file).resolve()) if prepared_file else None,
        esnq_root=str(Path(esnq_root).resolve()) if esnq_root else None,
        ledger_source_sha256=ledger_hash,ledger_rows=reservations(ledger_path) if ledger_path else [],
        provider_records=provider_records,billing_review=billing_review,admission_review=admission_review,
        broker_inputs=broker_inputs or {},provider_account_observation=provider_account_observation,
        frozen_H1_evidence=frozen_H1_evidence,**SAFETY)
    request['input_sha256']=digest(request)
    input_file=output/'input.json';input_file.write_text(json.dumps(encode(request),sort_keys=True,indent=2));input_file.chmod(0o600)
    try:
        a=isolated(input_file,output/'replay-01.json');b=isolated(input_file,output/'replay-02.json')
        if (a!=b or (output/'replay-01.json').read_bytes()!=(output/'replay-02.json').read_bytes()
                or hashes!=source_hashes(repository) or ledger_path and ledger_hash!=sha256_file(ledger_path)):
            raise ValueError('repeat_sources_or_readonly_ledger_changed')
        summary=dict(schema='monatise-phase6-acceptance-v1',baseline=BASELINE,input_sha256=request['input_sha256'],
            source_hashes_sha256=digest(hashes),runtime=request['runtime'],repeat_equal=True,
            replay_sha256=sha256_file(output/'replay-01.json'),
            normalized_gc_sha256=a['native_gc']['normalized_sha256'] if a['native_gc'] else None,
            normalized_index_sha256={k:p['normalized_sha256'] for k,p in (a['native_indices'] or {}).get('products',{}).items()},
            billing_status=a['billing']['status'] if a['billing'] else 'NO_REQUESTS',
            research_admission_eligible=a['billing']['research_admission_eligible'] if a['billing'] else False,
            GC_CVD={k:a['gc_cvd'][k] for k in ('buy_volume','sell_volume','unknown_volume','cvd_known','cvd_lower','cvd_upper',
                 'classified_volume_coverage','quote_inference')} if a['gc_cvd'] else None,
            authentic_basis_status=a['authentic_basis']['status'],authentic_options_status=a['authentic_options']['status'],
            authentic_canonical={k:r['status'] for k,r in a['authentic_canonical'].items()},
            engineering_canonical={k:r['status'] for k,r in a['engineering_canonical'].items()},
            new_acquisitions=0,incremental_provider_usage_usd='0',credit_consumed_usd='0',cash_spent_usd='0',
            ledger_unchanged=True,model_versions=a['model_versions'],frozen_H1_evidence=frozen_H1_evidence,**SAFETY)
        store=ResearchArtifactStore(output/'immutable')
        store.publish('replays',a);store.publish('quality',summary)
        (output/'summary.json').write_text(json.dumps(encode(summary),sort_keys=True,indent=2))
        for p in output.iterdir():
            if p.is_file():p.chmod(0o600)
        return summary
    except Exception as exc:
        p=output/'quarantine.json';p.write_text(json.dumps(dict(status='QUARANTINED_INCOMPLETE_PHASE6_RUN',
            error_type=type(exc).__name__,**SAFETY),sort_keys=True));p.chmod(0o600)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('output','data-root','prepared-file','esnq-root','ledger-path'):
        parser.add_argument('--'+name,type=Path,required=name=='output')
    summary=run(**vars(parser.parse_args()))
    print(json.dumps(summary,sort_keys=True,indent=2))
