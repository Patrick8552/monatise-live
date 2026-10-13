"""Hash-bound, credential-free restart/replay acceptance over private archives."""
import argparse
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys

from monatise.research.databento.candles import ResearchArtifactStore
from ..runner import source_hashes
from ..models import digest
from .replay import sha
from . import SAFETY


def isolated(request_file,output_file):
    root=Path(__file__).resolve().parents[4]
    env={'PATH':str(Path(sys.executable).parent)+os.pathsep+'/usr/bin:/bin','LANG':'C'}
    p=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('bootstrap.py')),str(root),
        str(Path(request_file).resolve()),str(Path(output_file).resolve())],env=env,capture_output=True,text=True,timeout=180)
    if p.returncode:raise RuntimeError('phase7_worker_failed:'+p.stderr[-2500:])
    return json.loads(Path(output_file).read_text())


def run(*, capture, basis_reference, technical_reference, user_evidence_json,user_evidence_text,output):
    capture=Path(capture).resolve();output=Path(output).resolve()
    paths=[capture/'report.json',capture/'scope.json',*(capture/(s+'.native') for s in ('definition','mbp-1','statistics')),
        Path(basis_reference).resolve(),Path(technical_reference).resolve(),Path(user_evidence_json).resolve(),Path(user_evidence_text).resolve()]
    if any(not p.is_file() for p in paths):raise ValueError('genuine_regression_evidence_missing_no_recreation_allowed')
    evidence=json.loads(Path(user_evidence_json).read_text());report=json.loads((capture/'report.json').read_text())
    if evidence['native_source_checks']!=report['source_checks']:raise ValueError('user_report_native_hashes_disagree')
    root=Path(__file__).resolve().parents[4];sources=source_hashes(root)
    request=dict(schema='monatise-phase7-request-v1',capture=str(capture),basis_reference=str(Path(basis_reference).resolve()),
        technical_reference=str(Path(technical_reference).resolve()),files={str(p):sha(p) for p in paths},
        runtime=dict(python=sys.version,databento=version('databento'),databento_dbn=version('databento-dbn')),
        source_hashes_sha256=digest(sources),**SAFETY)
    output.mkdir(parents=True,exist_ok=False);output.chmod(0o700)
    input_file=output/'request.json';input_file.write_text(json.dumps(request,sort_keys=True,indent=2));input_file.chmod(0o600)
    try:
        a=isolated(input_file,output/'replay-01.json');b=isolated(input_file,output/'replay-02.json')
        if (a!=b or sha(output/'replay-01.json')!=sha(output/'replay-02.json')
                or sources!=source_hashes(root) or any(sha(p)!=request['files'][str(p)] for p in paths)):
            raise ValueError('restart_or_source_immutability_failed')
        summary=dict(schema='monatise-phase7-acceptance-v1',request_sha256=digest(request),
            replay_sha256=sha(output/'replay-01.json'),repeat_equal=True,source_unchanged=True,
            runtime=request['runtime'],source_hashes_sha256=request['source_hashes_sha256'],
            evidence_sha256s={p.name:request['files'][str(p)] for p in paths},
            genuine_basis_status=a['basis']['status'],basis_estimate=a['basis']['basis'],
            conditional_uncertainty=a['basis']['conditional_uncertainty'],
            options_status=a['options']['status'],selected_contracts=a['options']['selected_contracts'],
            greeks_statuses=[g['status'] for g in a['greeks']],decision=a['decision']['decision'],
            new_acquisitions=0,incremental_provider_usage_usd='0',credit_consumed_usd='0',cash_spent_usd='0',**SAFETY)
        ResearchArtifactStore(output/'immutable').publish('quality',summary)
        (output/'summary.json').write_text(json.dumps(summary,sort_keys=True,indent=2))
        return summary
    except Exception as exc:
        (output/'quarantine.json').write_text(json.dumps(dict(status='QUARANTINED_INCOMPLETE',error_type=type(exc).__name__,**SAFETY)))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('capture','basis-reference','technical-reference','user-evidence-json','user-evidence-text','output'):
        parser.add_argument('--'+name,required=True,type=Path)
    print(json.dumps(run(**vars(parser.parse_args())),sort_keys=True,indent=2))
