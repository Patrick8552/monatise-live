from copy import deepcopy
import pytest
from monatise.research.institutional.phase8.spot import SpotObservationLedger

BASE=1791936000000000000
def observation(received=BASE+100*3600*10**9,timeframe='1h'):
    return dict(symbol='FX:XAUUSD',provider='FXCM',timeframe=timeframe,received_ns=received,
        UTC_bar_export_verified=True,source_sha256='a'*64,
        candles=[dict(open_ns=BASE+i*3600*10**9,open=4200,high=4201,low=4199,close=4200,volume=None) for i in range(50)])

def test_two_actual_observations_do_not_invent_historical_pivot_knowledge():
    ledger=SpotObservationLedger();one=observation();ledger.observe(one)
    assert not ledger.finalized('1h',cutoff_ns=one['received_ns'])
    two=observation(one['received_ns']+10**9);ledger.observe(two);bars=ledger.finalized('1h',cutoff_ns=two['received_ns'])
    assert len(bars)==50 and all(b['final_known_ns']==two['received_ns'] and b['original_candle_receive_ns'] is None for b in bars)
    assert all(b['volume'] is None for b in bars)
    frozen=deepcopy(ledger.h1_freezes)
    ledger.observe(observation(two['received_ns']+10**9))
    assert ledger.h1_freezes==frozen

def test_wrong_timeframe_and_future_finalization_are_rejected_or_excluded():
    ledger=SpotObservationLedger()
    with pytest.raises(ValueError,match='cadence_mismatch'):ledger.observe(observation(timeframe='1m'))
    ledger.observe(observation(BASE+48*3600*10**9));ledger.observe(observation(BASE+48*3600*10**9+10**9))
    assert len(ledger.finalized('1h',cutoff_ns=ledger.last_receipt))==48

def test_revised_price_invalidates_prior_finalization_without_reusing_old_hash():
    ledger=SpotObservationLedger();one=observation();ledger.observe(one);ledger.observe(observation(one['received_ns']+10**9))
    revised=observation(one['received_ns']+2*10**9);revised['candles'][0]['close']=4200.5;ledger.observe(revised)
    assert len(ledger.finalized('1h',cutoff_ns=ledger.last_receipt))==49 and len(ledger.revisions)==1
    with pytest.raises(ValueError,match='ordered'):ledger.observe(revised)
