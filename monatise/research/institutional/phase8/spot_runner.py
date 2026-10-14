"""Credential-free subprocess boundary to the pinned frozen selector/Gold graph."""
from pathlib import Path
import json,os,subprocess,sys
from monatise.research.gold_retrospective.runner import verify_research_checkout

def run(input_path,output_path,*,frozen_checkout,timeout_seconds=120):
    frozen=verify_research_checkout(frozen_checkout);source=Path(input_path).resolve();destination=Path(output_path).resolve()
    if source.stat().st_size>50_000_000 or destination.exists():raise ValueError('bounded_input_and_fresh_output_required')
    env={'PATH':str(Path(sys.executable).parent)+os.pathsep+'/usr/bin:/bin','LANG':'en_US.UTF-8'}
    result=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('spot_bootstrap.py')),str(frozen),
        str(Path(__file__).resolve().parents[4]),str(source),str(destination)],env=env,capture_output=True,text=True,timeout=timeout_seconds)
    if result.returncode:raise RuntimeError('isolated_Gold_research_failed:'+result.stderr[-2000:])
    output=json.loads(destination.read_text())
    if output.get('execution_eligible') is not False or output.get('gil_enabled') is not False:raise ValueError('research_isolation_output_failure')
    return output
