"""Opt-in existing genuine DBN files; no downloads, credentials or provider clients."""
from pathlib import Path
from dataclasses import replace
import hashlib
import json
import os
import pytest

ROOT=os.environ.get('MONATISE_UNIFIED_MANIFEST_ROOT')
pytestmark=pytest.mark.skipif(not ROOT,reason='Existing private native archives not configured; never acquired by tests')


@pytest.fixture(params=['gc','btc'])
def inputs(request):
    p=Path(ROOT)/(request.param+'-historical_event_time.json')
    return p,json.loads(p.read_text())


def test_genuine_archive_reconstruction_never_constructs_provider_clients(inputs,monkeypatch):
    import databento as db
    from monatise.research.unified.archive import load_archive
    def forbidden(*a,**k):raise AssertionError('PROVIDER_CONNECTION_FORBIDDEN')
    monkeypatch.setattr(db,'Live',forbidden);monkeypatch.setattr(db,'Historical',forbidden)
    p,_=inputs;a=load_archive(p)
    assert len(a.bars)>1000 and len(a.trades)>0
    assert a.report['provider_connections']==0 and a.report['paid_downloads']==0
    assert a.report['identical_overlap_minutes']>0
    assert all(x['replay_completed']==['definition','mbp-1','ohlcv-1m','trades'] for x in a.report['capture_reconciliation'])
    end=max(b.available_ns for b in a.bars)
    snapshot=a.snapshot(end)
    assert all(b.close_ns<=end and b.available_ns<=end for b in snapshot.bars)
    assert snapshot.instrument.product in ('GC','BTC')
    assert snapshot.instrument.currency=='USD'
    assert snapshot.instrument.price_unit!='NATIVE_CONTRACT_QUOTATION'


def test_source_hash_failure_is_not_silently_ignored(inputs,tmp_path):
    from monatise.research.unified.archive import load_archive
    _,m=inputs;m['definition']['sha256']='0'*64
    bad=tmp_path/'bad.json';bad.write_text(json.dumps(m))
    with pytest.raises(ValueError,match='ARCHIVE_HASH_MISMATCH'):load_archive(bad)


def test_clock_modes_cannot_be_relabelled_or_mixed(inputs,tmp_path):
    from monatise.research.unified.archive import load_archive
    _,m=inputs;m['mode']='AS_RECORDED'
    bad=tmp_path/'clock.json';bad.write_text(json.dumps(m))
    with pytest.raises(ValueError,match='modeled_quote_cannot_claim_as_recorded'):load_archive(bad)


def test_archive_retrieval_and_event_time_are_distinct(inputs):
    from monatise.research.unified.archive import load_archive
    p,_=inputs;event=load_archive(p)
    recorded=load_archive(Path(ROOT)/(event.instrument.product.lower()+'-as_recorded.json'))
    earliest=min(b.available_ns for b in recorded.bars)
    assert any(b.available_ns<earliest for b in event.bars)
    with pytest.raises(ValueError,match='DEFINITION_NOT_YET_AVAILABLE'):
        recorded.snapshot(min(b.available_ns for b in event.bars))


def test_clean_process_imports_native_reader_without_twenty_engines(inputs):
    import subprocess,sys
    p,_=inputs
    code="""import sys,json
from monatise.research.unified.archive import load_archive
load_archive(sys.argv[1])
bad=[m for m in sys.modules if m.startswith(('monatise.engines','monatise.application.gold','monatise.crypto'))]
assert not bad,bad
print(json.dumps({'forbidden_imports':bad,'provider_connections':0}))
"""
    r=subprocess.run([sys.executable,'-c',code,str(p)],capture_output=True,text=True,check=True)
    assert json.loads(r.stdout)['forbidden_imports']==[]


def test_cli_writes_a_no_trade_input_failure_and_nonzero_exit(inputs,tmp_path):
    import subprocess,sys
    _,m=inputs;m['definition']['sha256']='0'*64
    bad=tmp_path/'bad-cli.json';bad.write_text(json.dumps(m));out=tmp_path/'decision.json'
    r=subprocess.run([sys.executable,'-m','monatise.research.unified','inventory','--manifest',str(bad),'--output',str(out)],capture_output=True,text=True)
    assert r.returncode==2
    body=json.loads(out.read_text())
    assert body['trade_action']=='NO_TRADE' and body['reason']=='SOURCE_VALIDATION_FAILED'
    assert body['entry'] is body['stop_loss'] is body['targets'] is None
    assert not body['execution_eligible']
