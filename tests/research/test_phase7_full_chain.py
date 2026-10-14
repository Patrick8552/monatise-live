from types import SimpleNamespace as NS
import json
import pytest
from monatise.research.institutional.phase7.full_chain import partition_rows,run


def leg(expiry,strike,kind):
    return NS(contract=NS(metadata=NS(expiration_ns=expiry,strike_fixed=strike,kind=kind)))


def test_full_scope_partition_preserves_each_call_put_pair_and_every_identity():
    rows=[leg(e,s,k) for e,n in ((1,623),(2,907)) for s in range(n) for k in ('C','P')]
    groups=partition_rows(rows)
    assert len(groups)==6 and sum(len(g) for g in groups)==3060
    assert {id(x) for g in groups for x in g}=={id(x) for x in rows}
    for group in groups:
        assert len(group)<=512
        assert {x.contract.metadata.expiration_ns for x in group}=={1,2}
        for x in group:
            m=x.contract.metadata
            assert {y.contract.metadata.kind for y in group
                    if (y.contract.metadata.expiration_ns,y.contract.metadata.strike_fixed)==(m.expiration_ns,m.strike_fixed)}=={'C','P'}


def test_missing_put_is_not_created_by_partitioning():
    rows=[leg(1,4200,'C'),leg(2,4200,'C'),leg(2,4200,'P')]
    groups=partition_rows(rows)
    assert sum(len(g) for g in groups)==3
    assert not any(x.contract.metadata.expiration_ns==1 and x.contract.metadata.kind=='P' for g in groups for x in g)


@pytest.mark.parametrize('rows',[[],[leg(1,1,'C')]*4097])
def test_scope_exhaustion_fails_instead_of_silent_truncation(rows):
    with pytest.raises(ValueError,match='bounded'):partition_rows(rows)


@pytest.mark.parametrize('report',[
    {'status':'QUARANTINED','quality':{'quarantined':True},'replay_completed_schemas':['definition','mbp-1','statistics']},
    {'status':'CAPTURED','quality':{'quarantined':False},'replay_completed_schemas':['definition','statistics']},
])
def test_incomplete_or_quarantined_real_capture_cannot_enter_replay(tmp_path,report):
    (tmp_path/'report.json').write_text(json.dumps(report))
    with pytest.raises(ValueError,match='complete_nonquarantined'):
        run(captures=[tmp_path],rate_evidence=tmp_path/'unavailable-rate')
