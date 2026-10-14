import json,os,subprocess,sys
from pathlib import Path
import pytest
from monatise.research.institutional.phase8.spot_runner import run

@pytest.fixture(scope='module')
def synthetic_broker_archive(tmp_path_factory):
    frozen=os.environ.get('GC_H1_RESEARCH_CHECKOUT')
    if not frozen:pytest.skip('pinned frozen checkout supplied by full research harness')
    root=tmp_path_factory.mktemp('phase8-frozen-bridge');p=root/'input.json'
    code="import json,sys;from tests.research.gold_fib_fixtures import archive;json.dump(archive(),open(sys.argv[1],'w'))"
    subprocess.run([sys.executable,'-c',code,str(p)],cwd=frozen,check=True,
        env={'PATH':os.environ.get('PATH',''),'LANG':'en_US.UTF-8'},capture_output=True,text=True)
    assert json.loads(p.read_text())['evidence_kind']=='ENGINEERING_SYNTHETIC'
    out=run(p,root/'output.json',frozen_checkout=frozen)
    return out,frozen,p,root

def test_existing_canonical_graph_runs_in_isolation_without_source_certificate(synthetic_broker_archive):
    result,_,_,_=synthetic_broker_archive
    assert result['canonical_frozen_offline_graph_invoked']
    assert result['frozen_replay']['records'] and result['genuine_input_certificate'] is False
    assert result['basis_status']=='DEFERRED_NOT_CERTIFIED'
    assert not result['execution_eligible'] and not result['gil_enabled']

def test_fresh_output_and_pinned_checkout_cannot_be_bypassed(synthetic_broker_archive):
    _,frozen,p,root=synthetic_broker_archive
    with pytest.raises(ValueError,match='fresh_output'):run(p,root/'output.json',frozen_checkout=frozen)
