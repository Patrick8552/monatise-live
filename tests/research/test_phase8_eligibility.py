from types import SimpleNamespace as NS
import databento_dbn as dn
from monatise.research.institutional.phase8.eligibility import oi_eligibility,quote_eligibility,pair_eligibility

NOW=1791940000000000000

def oi(quantity=0,reference=NOW-86400*10**9):
    return dn.StatMsg(publisher_id=1,instrument_id=1,ts_event=NOW-100,ts_recv=NOW-99,
        ts_ref=reference,quantity=quantity,price=0,stat_type=dn.StatType.OPEN_INTEREST,update_action=dn.StatUpdateAction.NEW)

def review(record=None,**kwargs):
    return oi_eligibility(record,identity=(1,1),available_ns=NOW-1,local_cutoff_ns=NOW,
        market_cutoff_ns=NOW,captured=kwargs.pop('captured',True),entitled=kwargs.pop('entitled',True),**kwargs)

def test_absence_is_unknown_never_published_zero_or_not_published():
    assert review()['status']=='UNKNOWN' and review()['value'] is None
    assert review(captured=False)['status']=='NOT_CAPTURED'
    assert review(entitled=False)['status']=='NOT_ENTITLED'
    assert review(explicit_nonpublication={'publisher_reference':'reviewed-synthetic-notice','sha256':'a'*64})['status']=='NOT_PUBLISHED'

def test_native_zero_positive_and_stale_reference_remain_distinct():
    assert review(oi())['status']=='PUBLISHED_ZERO'
    assert review(oi(25))['status']=='PUBLISHED_NONZERO'
    stale=review(oi(reference=NOW-5*86400*10**9))
    assert stale['status']=='STALE' and stale['value'] is None and stale['observed']['contracts']==0

def quote(bid=4200*10**9,ask=4200.1*10**9,event=NOW-100,identity=1):
    return NS(publisher_id=1,instrument_id=identity,ts_event=event,ts_recv=NOW-90,sequence=1,flags=0,
        levels=[NS(bid_px=int(bid),ask_px=int(ask),bid_sz=1,ask_sz=1)])

def qreview(q):return quote_eligibility(q,identity=(1,1),market_cutoff_ns=NOW,available_ns=NOW-1,local_cutoff_ns=NOW)

def test_one_sided_and_stale_quote_reasons_are_not_hidden_by_valid_old_book():
    r=qreview(quote(bid=2**63-1));assert not r['eligible'] and 'no_observed_bid' in r['reasons'] and 'one_sided_market' in r['reasons']
    r=qreview(quote(event=NOW-31*10**9));assert r['status']=='STALE'
    assert 'crossed_market' in qreview(quote(4201*10**9,4200*10**9))['reasons']
    assert 'contract_identity_mismatch' in qreview(quote(identity=2))['reasons']

def test_existing_one_second_pair_gate_not_relaxed():
    a=qreview(quote());b=qreview(quote(event=NOW-2*10**9))
    assert a['eligible'] and b['eligible'] and not pair_eligibility(a,b)['eligible']
