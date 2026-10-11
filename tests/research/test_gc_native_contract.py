"""Synthetic DBN engineering fixtures; authentic archive is audited separately."""
from dataclasses import replace
from decimal import Decimal
import pytest
from tests.research.test_databento_foundations import future, policy, NOW_NS, DAY
from monatise.adapters.databento_gold import definition, ns_time
from monatise.research.gc_fib.native_contract import reconstruct_native_gcz6
from monatise.research.gc_fib.candles import GCIdentity, from_observation
from monatise.research.databento.acquisition import HistoricalRequest
from monatise.research.databento.replay import normalize_record


def native(**changes):
    return future(**(dict(unit_of_measure="TRYOZ", display_factor=100_000_000,
        min_price_increment_amount=1_000_000_000, main_fraction=255,
        activation=NOW_NS-2*DAY) | changes))


def test_native_terms_validated_without_mutating_bytes_or_legacy_default():
    row=native(); before=bytes(row)
    result=reconstruct_native_gcz6(row,identity_policy=policy(),retrieval_ns=NOW_NS)
    assert bytes(row)==before and result.reference.contract.tick==Decimal('.1')
    assert result.reference.contract.multiplier==100
    assert not result.apply_display_factor_to_dbn_price and not result.trading_eligible
    with pytest.raises(ValueError,match='units'):
        definition(row,publishers={1:('GLBX.MDP3','XCEC')},now=ns_time(NOW_NS))


@pytest.mark.parametrize('changes',[
    {'unit_of_measure':'LBS'},{'currency':'EUR'},{'display_factor':1_000_000_000},
    {'min_price_increment':1_000_000_000},{'unit_of_measure_qty':10_000_000_000},
    {'min_price_increment_amount':2_000_000_000},{'main_fraction':32},
    {'exchange':'XCME'},{'instrument_id':123},{'maturity_month':11},
    {'leg_count':1},{'activation':NOW_NS},{'ts_recv':NOW_NS+1},
    {'expiration':NOW_NS-DAY},
])
def test_native_contradictions_fail_closed(changes):
    with pytest.raises(ValueError):
        reconstruct_native_gcz6(native(**changes),identity_policy=policy(),retrieval_ns=NOW_NS)


def test_native_prices_are_not_scaled_twice_after_reference_validation():
    import databento_dbn as dbn
    reference=reconstruct_native_gcz6(native(),identity_policy=policy(),retrieval_ns=NOW_NS).reference
    start=(NOW_NS-DAY)//(60*10**9)*(60*10**9)
    row=dbn.OHLCVMsg(rtype=dbn.RType.OHLCV_1M,publisher_id=1,instrument_id=41271,
        ts_event=start,open=4000_000_000_000,high=4001_000_000_000,
        low=3999_000_000_000,close=4000_100_000_000,volume=12)
    request=HistoricalRequest('GLBX.MDP3','ohlcv-1m',((1,41271,'GCZ6'),),start,start+60*10**9)
    # Fixture definition event must causally precede this minute.
    reference=replace(reference,definition_event_ns=start-1)
    observation=normalize_record(row,request=request,reference=reference,ordinal=0,
        ingestion_ns=NOW_NS,retrieval_ns=NOW_NS)
    candle=from_observation(observation,identity=GCIdentity(),retrieval_ns=NOW_NS,admission_ns=NOW_NS)
    assert candle.open=='4000' and candle.close=='4000.1'
