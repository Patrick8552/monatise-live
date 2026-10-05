"""DBN-compatible synthetic fixtures; SDK records tested when extra installed."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from monatise.adapters.databento_gold import (
    UNDEF_PRICE,
    UNDEF_TIMESTAMP,
    DatabentoGoldAdapter,
    GCReplay,
    definition,
    ns_time,
    price,
)
from monatise.application.gold_basis import GoldBasisService
from monatise.application.gold_options import normalize_option

NOW = datetime(2026, 10, 5, 15, tzinfo=UTC)
PUB = {4: ("GLBX.MDP3", "XCEC")}


def ns(t):
    return int(t.timestamp()) * 1_000_000_000


def definitions(**changes):
    return SimpleNamespace(
        publisher_id=4,
        instrument_id=100,
        ts_event=ns(NOW - timedelta(days=1)),
        ts_recv=ns(NOW - timedelta(days=1)),
        raw_symbol="GCZ6",
        asset="GC",
        instrument_class="F",
        security_type="FUT",
        leg_count=0,
        user_defined_instrument="N",
        security_update_action="A",
        currency="USD",
        unit_of_measure="oz",
        unit_of_measure_qty=100_000_000_000,
        min_price_increment=100_000_000,
        display_factor=1_000_000_000,
        expiration=ns(NOW + timedelta(days=60)),
        **changes,
    )


def changed_def(**changes):
    d = definitions()
    d.__dict__.update(changes)
    return d


def replay():
    r = GCReplay(publishers=PUB)
    r.add_definition(definitions(), now=NOW)
    r.select(
        100,
        now=NOW,
        session_open=NOW - timedelta(hours=1),
        session_close=NOW + timedelta(hours=8),
    )
    return r


def trade(sequence=1, *, p=2500, size=2, side="B", **changes):
    d = SimpleNamespace(
        publisher_id=4,
        instrument_id=100,
        ts_event=ns(NOW - timedelta(seconds=3) + timedelta(seconds=sequence * 0.1)),
        ts_recv=ns(NOW - timedelta(seconds=3) + timedelta(seconds=sequence * 0.1)),
        sequence=sequence,
        price=int(Decimal(str(p)) * 1_000_000_000),
        size=size,
        side=side,
        action="T",
        flags=0,
    )
    d.__dict__.update(changes)
    return d


def quote():
    return SimpleNamespace(
        publisher_id=4,
        instrument_id=100,
        ts_event=ns(NOW - timedelta(seconds=1)),
        ts_recv=ns(NOW - timedelta(seconds=1)),
        flags=0,
        levels=[
            SimpleNamespace(
                bid_px=2501900000000, ask_px=2502100000000, bid_sz=2, ask_sz=2
            )
        ],
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"instrument_class": "S"},
        {"leg_count": 2},
        {"raw_symbol": "GC.v.0"},
        {"asset": "MGC"},
        {"currency": "EUR"},
        {"display_factor": 100000000},
        {"unit_of_measure_qty": UNDEF_PRICE},
        {"user_defined_instrument": "Y"},
        {"ts_recv": ns(NOW + timedelta(seconds=1))},
        {"security_update_action": "D"},
    ],
)
def test_unknown_metadata_and_non_outrights_rejected(changes):
    with pytest.raises(ValueError):
        definition(changed_def(**changes), publishers=PUB, now=NOW)


@pytest.mark.parametrize("value", [UNDEF_PRICE, 0, -1, True, 1.2])
def test_price_sentinels_never_become_numeric_levels(value):
    with pytest.raises(ValueError):
        price(value)


def test_time_sentinel_and_publisher_identity():
    with pytest.raises(ValueError):
        ns_time(UNDEF_TIMESTAMP)
    with pytest.raises(ValueError):
        definition(definitions(), publishers={4: ("wrong", "XCEC")}, now=NOW)


def test_expected_volume_vwap_profile_cvd_and_schema_deduplication():
    r = replay()
    for t in (
        trade(1, p=2500, size=2),
        trade(2, p=2501, size=3, side="A"),
        trade(3, p=2502, size=5, side="N"),
    ):
        assert r.ingest("trades", t, now=NOW)
        assert not r.ingest("trades", t, now=NOW)
    r.ingest("mbp-1", quote(), now=NOW)
    r.complete_replay(covered_from=r.session[0], covered_to=NOW, now=NOW)
    s = r.snapshot(now=NOW)
    assert s["status"] == "usable" and s["volume"] == 10
    assert Decimal(s["vwap"]) == Decimal("2501.3") and s["poc"] == "2502"
    assert (
        s["cvd_known_side"] == -1
        and s["unknown_side_volume"] == 5
        and s["side_coverage"] == 0.5
    )
    assert not s["cvd_complete"] and s["direction"] is None
    assert r.snapshot(now=NOW + timedelta(seconds=15))["status"] == "unavailable"


@pytest.mark.parametrize(
    "reason", ["feed_gap", "backpressure", "reconnect", "trade_correction"]
)
def test_gap_and_correction_quarantine_without_silent_recovery(reason):
    r = replay()
    r.ingest("trades", trade(), now=NOW)
    r.ingest("mbp-1", quote(), now=NOW)
    if reason == "trade_correction":
        r.ingest("trades", trade(2, action="C"), now=NOW)
    else:
        r.mark_gap(reason)
    assert r.snapshot(now=NOW)["status"] == "unavailable"


def test_roll_clears_statistics_quotes_and_levels():
    r = replay()
    r.ingest("trades", trade(), now=NOW)
    r.ingest("mbp-1", quote(), now=NOW)
    r.add_definition(
        changed_def(
            instrument_id=101,
            raw_symbol="GCG7",
            expiration=ns(NOW + timedelta(days=130)),
        ),
        now=NOW,
    )
    r.select(
        101,
        now=NOW,
        session_open=NOW - timedelta(hours=1),
        session_close=NOW + timedelta(hours=8),
    )
    assert (
        not r.records
        and r.quote is None
        and r.snapshot(now=NOW)["status"] == "unavailable"
    )
    with pytest.raises(ValueError):
        r.ingest("trades", trade(), now=NOW)


def test_backpressure_is_unusable_not_partial_volume():
    r = GCReplay(publishers=PUB, capacity=10)
    r.add_definition(definitions(), now=NOW)
    r.select(
        100,
        now=NOW,
        session_open=NOW - timedelta(hours=1),
        session_close=NOW + timedelta(hours=8),
    )
    for n in range(1, 12):
        r.ingest("trades", trade(n), now=NOW)
    assert len(r.records) == 10 and "bounded_cache_overflow" in r.gaps


def test_live_client_is_lazy_and_requires_explicit_authorization():
    class NeverClient:
        def __call__(self, *args):
            raise AssertionError("network not authorized")

    adapter = DatabentoGoldAdapter(replay(), client_factory=NeverClient())
    with pytest.raises(ValueError):
        asyncio.run(adapter.stream(api_key="placeholder", authorized=False))


def test_actual_sdk_definition_and_trade_messages_offline():
    dbn = pytest.importorskip("databento_dbn")
    args = definitions().__dict__.copy()
    args.update(
        instrument_class=dbn.InstrumentClass.FUTURE,
        security_update_action=dbn.SecurityUpdateAction.ADD,
        user_defined_instrument=dbn.UserDefinedInstrument.NO,
    )
    d = dbn.InstrumentDefMsg(**args)
    r = GCReplay(publishers=PUB)
    r.add_definition(d, now=NOW)
    r.select(
        100,
        now=NOW,
        session_open=NOW - timedelta(hours=1),
        session_close=NOW + timedelta(hours=8),
    )
    t = trade().__dict__.copy()
    t.update(depth=0, action=dbn.Action.TRADE, side=dbn.Side.BID)
    assert r.ingest("trades", dbn.TradeMsg(**t), now=NOW)
    q = quote().__dict__.copy()
    q.update(
        price=UNDEF_PRICE,
        size=0,
        action=dbn.Action.ADD,
        side=dbn.Side.BID,
        depth=0,
        sequence=3,
        levels=dbn.BidAskPair(**q["levels"][0].__dict__),
    )
    r.ingest("mbp-1", dbn.MBP1Msg(**q), now=NOW)
    r.complete_replay(covered_from=r.session[0], covered_to=NOW, now=NOW)
    assert r.snapshot(now=NOW)["status"] == "usable"


def basis():
    b = GoldBasisService()
    for i in range(5):
        at = NOW - timedelta(seconds=5 - i)
        b.add(
            contract="GCZ6",
            broker_bid=2499.9,
            broker_ask=2500.1,
            futures_bid=2509.9,
            futures_ask=2510.1,
            broker_at=at,
            futures_at=at,
            now=NOW,
        )
    return b


def test_basis_expected_midpoint_mapping_uncertainty_roll_and_age():
    b = basis()
    m = b.map_level(2520, contract="GCZ6", now=NOW)
    assert m["basis"] == 10 and m["mapped_low"] == 2510 and m["mapped_high"] == 2510
    assert m["context_only"] and not m["execution_price_authority"]
    with pytest.raises(ValueError):
        b.map_level(2520, contract="GCG7", now=NOW)
    with pytest.raises(ValueError):
        b.map_level(2520, contract="GCZ6", now=NOW + timedelta(seconds=40))
    b.add(
        contract="GCG7",
        broker_bid=2499.9,
        broker_ask=2500.1,
        futures_bid=2529.9,
        futures_ask=2530.1,
        broker_at=NOW,
        futures_at=NOW,
        now=NOW,
    )
    assert len(b.samples) == 1
    with pytest.raises(ValueError):
        b.estimate(contract="GCG7", now=NOW)


@pytest.mark.parametrize("change", ["skew", "crossed", "dispersion", "duplicate"])
def test_bad_basis_quarantines_mapping(change):
    b = basis()
    args = {
        "contract": "GCZ6",
        "broker_bid": 2499.9,
        "broker_ask": 2500.1,
        "futures_bid": 2509.9,
        "futures_ask": 2510.1,
        "broker_at": NOW,
        "futures_at": NOW,
        "now": NOW,
    }
    if change == "skew":
        args["futures_at"] = NOW - timedelta(seconds=2)
    if change == "crossed":
        args["broker_bid"] = 2501
    if change == "duplicate":
        args["broker_at"] = args["futures_at"] = NOW - timedelta(seconds=1)
    if change == "dispersion":
        args["futures_bid"] = 2519.9
        args["futures_ask"] = 2520.1
        b.add(**args)
        with pytest.raises(ValueError):
            b.estimate(contract="GCZ6", now=NOW)
    else:
        with pytest.raises(ValueError):
            b.add(**args)


def test_option_join_uses_own_underlying_and_expiry_and_rejects_weekly_guess():
    r = replay()
    d = changed_def(
        instrument_id=200,
        raw_symbol="OG_SYNTHETIC_CALL",
        asset="OG",
        instrument_class="C",
        underlying_id=100,
        strike_price=2500000000000,
        strike_price_currency="USD",
        expiration=ns(NOW + timedelta(days=30)),
    )
    convention = {
        "family": "OG",
        "style": "American",
        "settlement": "future_delivery",
        "currency": "USD",
        "multiplier": 100,
    }
    option = normalize_option(
        d, futures=r.definitions, publishers=PUB, now=NOW, convention=convention
    )
    assert (
        option.underlying_contract == "GCZ6"
        and option.expiry < option.underlying_expiry
    )
    d.underlying_id = 101
    with pytest.raises(ValueError):
        normalize_option(
            d, futures=r.definitions, publishers=PUB, now=NOW, convention=convention
        )
    d.underlying_id = 100
    d.asset = "OGW"
    with pytest.raises(ValueError):
        normalize_option(
            d, futures=r.definitions, publishers=PUB, now=NOW, convention=convention
        )


def test_rejected_current_basis_quote_quarantines_old_mapping():
    b = basis()
    with pytest.raises(ValueError):
        b.add(
            contract="GCZ6",
            broker_bid=2500,
            broker_ask=2499,
            futures_bid=2510,
            futures_ask=2511,
            broker_at=NOW,
            futures_at=NOW,
            now=NOW,
        )
    with pytest.raises(ValueError, match="insufficient"):
        b.map_level(2520, contract="GCZ6", now=NOW)


def test_exact_trade_identity_correction_is_not_discarded_as_duplicate():
    r = replay()
    original = trade()
    r.ingest("trades", original, now=NOW)
    original.action = "C"
    r.ingest("trades", original, now=NOW)
    assert "unsupported_trade_correction" in r.gaps


def test_bad_quote_and_selected_definition_quarantine_old_gc_evidence():
    r = replay()
    r.ingest("trades", trade(), now=NOW)
    r.ingest("mbp-1", quote(), now=NOW)
    r.complete_replay(covered_from=r.session[0], covered_to=NOW, now=NOW)
    assert r.snapshot(now=NOW)["status"] == "usable"
    q = quote()
    q.levels[0].ask_px = 2499000000000
    with pytest.raises(ValueError):
        r.ingest("mbp-1", q, now=NOW)
    assert r.snapshot(now=NOW)["status"] == "unavailable"
    r = replay()
    with pytest.raises(ValueError):
        r.add_definition(changed_def(currency="EUR"), now=NOW)
    assert "selected_contract_definition_rejected" in r.gaps


def test_session_vwap_cannot_be_certified_from_first_and_last_trade_only():
    r = replay()
    r.ingest("trades", trade(), now=NOW)
    r.ingest("mbp-1", quote(), now=NOW)
    assert r.snapshot(now=NOW)["status"] == "unavailable"
    with pytest.raises(ValueError):
        r.complete_replay(
            covered_from=NOW - timedelta(minutes=5), covered_to=NOW, now=NOW
        )
