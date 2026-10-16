from dataclasses import replace
import json,hashlib
import pytest
import databento_dbn as dn

from monatise.research.native_futures.history import seed_native_history
from monatise.research.native_futures.analysis import analyse_frame
from monatise.research.phase10.history import complete_parents,JoinedBar
from monatise.research.phase9.lineage import verify_bar_lineage
from tests.research.native_futures.test_information_gate import native_pipeline
from tests.research.phase9.test_pipeline import NOW_NS,NS


def archive(tmp_path, *, partial=False,limit=20000,metadata_end=None):
    p,c=native_pipeline();end=NOW_NS//(3600*NS)*(3600*NS);start=end-3600*NS
    rows=[dn.OHLCVMsg(publisher_id=1,instrument_id=c.metadata.instrument_id,ts_event=start+i*60*NS,
        rtype=dn.RType.OHLCV_1M,open=(2500+i)*NS,high=(2501+i)*NS,low=(2499+i)*NS,
        close=(2500+i)*NS,volume=i+1) for i in range(60) if i!=7]
    metadata=dn.Metadata(dataset='GLBX.MDP3',start=start,end=metadata_end or end,
        stype_in=dn.SType.RAW_SYMBOL,stype_out=dn.SType.INSTRUMENT_ID,
        schema=dn.Schema.OHLCV_1M,symbols=[c.metadata.raw_symbol],partial=[c.metadata.raw_symbol] if partial else [],limit=limit,version=3)
    path=tmp_path/'bars.dbn';path.write_bytes(metadata.encode()+b''.join(bytes(r) for r in rows))
    source=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),records=59,request_limit=20000,
        schema='ohlcv-1m',retrieval_ns=NOW_NS-NS,start_ns=start,end_ns=end)
    return p,c,source,start,end


def test_complete_archive_no_print_does_not_require_a_fabricated_minute(tmp_path):
    p,c,s,start,end=archive(tmp_path);review=seed_native_history(p,[s],cutoff_ns=NOW_NS)
    g=p.gates[c.metadata.instrument_id];minutes=tuple(p.bars[c.metadata.instrument_id]['1m'].values())
    assert len(minutes)==59 and review['synthetic_bars']==0
    assert len(g.coverage_reviews)==1
    proofs=tuple(g.coverage_reviews.values())
    parents,errors=complete_parents(minutes,'1h',p.calendars[c.metadata.instrument_id],coverage_reviews=proofs)
    assert not errors and len(parents)==1
    b=parents[0];assert (b.open_ns,b.close_ns)==(start,end) and len(b.children)==59
    assert b.volume==sum(r.volume for r in minutes)
    assert b.prices_fixed==(minutes[0].prices_fixed[0],max(r.prices_fixed[1] for r in minutes),min(r.prices_fixed[2] for r in minutes),minutes[-1].prices_fixed[3])
    verify_bar_lineage(g,parents,reviewed_history=True)
    result=analyse_frame(minutes,tick_size=c.tick_size,cutoff_ns=NOW_NS,calendar=p.calendars[c.metadata.instrument_id],coverage_reviews=proofs)
    assert result['available'] and len(result['provider_no_print_intervals'])==1 and result['gap_fill_count']==0
    assert not analyse_frame(minutes,tick_size=c.tick_size,cutoff_ns=NOW_NS,calendar=p.calendars[c.metadata.instrument_id])['available']


@pytest.mark.parametrize('change',[dict(partial=True),dict(limit=30000),dict(metadata_end=NOW_NS)])
def test_incomplete_or_mismatched_metadata_cannot_prove_no_print(tmp_path,change):
    p,c,s,_,_=archive(tmp_path,**change);seed_native_history(p,[s],cutoff_ns=NOW_NS)
    assert not p.gates[c.metadata.instrument_id].coverage_reviews
    rows=tuple(p.bars[c.metadata.instrument_id]['1m'].values())
    assert complete_parents(rows,'1h',p.calendars[c.metadata.instrument_id])[0]==()


def test_historical_proof_never_covers_a_later_live_gap_or_another_contract(tmp_path):
    p,c,s,start,end=archive(tmp_path);seed_native_history(p,[s],cutoff_ns=NOW_NS)
    proof=next(iter(p.gates[c.metadata.instrument_id].coverage_reviews.values()))
    assert not proof.covers(c.identity,'ohlcv-1m',end,end+60*NS)
    identity=(*c.identity[:2],c.identity[2]+1,*c.identity[3:])
    assert not proof.covers(identity,'ohlcv-1m',start,end)
    with pytest.raises(ValueError):replace(proof,record_count=proof.request_limit)


def test_complete_minute_response_does_not_prove_seconds_coverage(tmp_path):
    from monatise.research.databento.candles import HistoricalBar
    from monatise.research.institutional.models import digest
    p,c,s,start,end=archive(tmp_path);seed_native_history(p,[s],cutoff_ns=NOW_NS)
    proofs=tuple(p.gates[c.metadata.instrument_id].coverage_reviews.values())
    rows=tuple(HistoricalBar(c.metadata,'1s',start+i*NS,start+(i+1)*NS,
        (2500*NS,2501*NS,2499*NS,2500*NS),1,NOW_NS-NS,(digest(i),),'ohlcv-1s','ENGINEERING_SYNTHETIC')
        for i in range(60) if i!=7)
    result=analyse_frame(rows,tick_size=c.tick_size,cutoff_ns=NOW_NS,calendar=p.calendars[c.metadata.instrument_id],coverage_reviews=proofs)
    assert not result['available'] and result['reason']=='missing_bar_in_reviewed_trading_interval'
