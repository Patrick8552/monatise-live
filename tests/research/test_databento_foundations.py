"""Real SDK schemas, synthetic market values, authentic saved API metadata."""

import ast
import hashlib
import importlib.metadata
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from monatise.adapters.databento_gold import GCReplay, definition
from monatise.adapters.databento_identity import (
    DatabentoPublisherPolicy, broker_xauusd_namespace, datetime_ns, timestamp_ns,
)
from monatise.application.gold_options import normalize_option
from monatise.research.databento.registry import GoldInstrumentRegistry, STANDARD_OG
from tests.test_databento_gold import definitions, NOW as LEGACY_NOW, PUB

dbn = pytest.importorskip("databento_dbn", reason="optional pinned gold-data SDK required")
NOW = datetime(2026, 10, 11, 14, tzinfo=UTC)
NOW_NS = datetime_ns(NOW)
DAY = 86400 * 1_000_000_000
EXPIRY = NOW_NS + 60 * DAY + 321
FIXTURE = Path(__file__).parents[1] / "fixtures/databento/glbx_metadata_2026-10-11.json"


def policy():
    f = json.loads(FIXTURE.read_text())
    return DatabentoPublisherPolicy.from_metadata(f["publishers"],
        observed_at_ns=datetime_ns(datetime.fromisoformat(f["checked_at"])),
        source_sha256=f["source_sha256"])


def future(**changes):
    args = dict(publisher_id=1, instrument_id=41271, ts_event=NOW_NS-DAY+111,
        ts_recv=NOW_NS-DAY+222, min_price_increment=100_000_000,
        display_factor=1_000_000_000, raw_symbol="GCZ6", asset="GC",
        security_type="FUT", instrument_class=dbn.InstrumentClass.FUTURE,
        security_update_action=dbn.SecurityUpdateAction.ADD,
        expiration=EXPIRY, currency="USD", unit_of_measure="oz",
        unit_of_measure_qty=100_000_000_000, exchange="XCEC", maturity_year=2026,
        maturity_month=12, user_defined_instrument=dbn.UserDefinedInstrument.NO)
    args.update(changes)
    return dbn.InstrumentDefMsg(**args)


def option(**changes):
    args = dict(instrument_id=50001, raw_symbol="OGZ6 C2500", asset="OG",
        security_type="OOF", instrument_class=dbn.InstrumentClass.CALL,
        underlying_id=41271, underlying="GCZ6", strike_price=2_500_000_000_000,
        strike_price_currency="USD", expiration=NOW_NS+30*DAY+321)
    args.update(changes)
    return future(**args)


def ingest(registry, record, *, ordinal=0, at=NOW_NS, **kwargs):
    return registry.ingest(record, ingestion_ns=at, source_ordinal=ordinal,
        evidence_kind="ENGINEERING_SYNTHETIC", **kwargs)


def resolve(registry, iid=41271, *, at=NOW_NS):
    return registry.resolve(publisher_id=1, instrument_id=iid, at_ns=at)


def test_authentic_metadata_fixture_never_claims_market_definitions():
    f = json.loads(FIXTURE.read_text())
    assert f["evidence_kind"] == "AUTHENTIC_PROVIDER_METADATA"
    assert not f["contains_market_definitions"] and not f["contains_credentials"]
    assert f["publishers"][0]["publisher_id"] == 1
    assert f["publishers"][0]["venue"] == "GLBX"
    assert f["raw_contract_mapping"]["result"]["41271"][0]["s"] == "GCZ6"


def test_sdk_pin_and_native_dbn_definition_roundtrip():
    assert importlib.metadata.version("databento") == "0.87.0"
    original = future()
    decoder = dbn.DBNDecoder(has_metadata=False, input_version=3)
    decoder.write(bytes(original))
    decoded = decoder.decode()[0]
    assert bytes(decoded) == bytes(original)
    p = policy()
    value = definition(decoded, publishers=p.mapping, now=NOW, identity_policy=p)
    assert (value.raw_symbol, value.venue, value.publisher_id) == ("GCZ6", "XCEC", 1)


def test_default_shared_behavior_unchanged_and_new_policy_explicit():
    before = definition(definitions(), publishers=PUB, now=LEGACY_NOW)
    assert before == definition(definitions(), publishers=PUB, now=LEGACY_NOW, identity_policy=None)
    with pytest.raises(ValueError, match="publisher"):
        definition(future(), publishers=policy().mapping, now=NOW)
    with pytest.raises(ValueError, match="explicit"):
        definition(future(), publishers=policy().mapping, now=NOW, identity_policy=object())
    r = GCReplay(publishers=policy().mapping, identity_policy=policy())
    assert r.add_definition(future(), now=NOW).instrument_id == 41271
    assert r.coverage is None  # Definition identity does not certify coverage.


@pytest.mark.parametrize("changes", [
    {"publisher_id": 4}, {"exchange": "XCME"}, {"exchange": "GLBX"},
    {"exchange": ""}, {"asset": "MGC"}, {"raw_symbol": "GC.v.0"},
    {"security_type": "OOF"}, {"leg_count": 2}, {"currency": "EUR"},
    {"display_factor": 100_000_000}, {"unit_of_measure_qty": 10_000_000_000},
    {"user_defined_instrument": dbn.UserDefinedInstrument.YES},
    {"maturity_month": 11}, {"maturity_year": 2027},
    {"expiration": NOW_NS}, {"ts_event": NOW_NS+1, "ts_recv": NOW_NS+1},
    {"ts_event": NOW_NS+10, "ts_recv": NOW_NS},
    {"ts_recv": (1 << 64)-1},
])
def test_unknown_inconsistent_and_submicrosecond_future_definitions_rejected(changes):
    r = GoldInstrumentRegistry(identity_policy=policy())
    with pytest.raises(ValueError):
        ingest(r, future(**changes))
    assert not r.observations


def test_catalog_exact_identity_immutable_and_no_future_metadata():
    p = policy()
    with pytest.raises(ValueError, match="publisher"):
        p.validate(future(), publishers={1: ("GLBX.MDP3", "XCEC")}, now=NOW)
    with pytest.raises(ValueError, match="unavailable"):
        replace(p, observed_at_ns=NOW_NS+1).validate(future(), publishers=p.mapping, now=NOW)
    mapping = p.mapping
    mapping[1] = ("wrong", "wrong")
    assert p.mapping[1] == ("GLBX.MDP3", "GLBX")
    with pytest.raises(FrozenInstanceError):
        p.observed_at_ns = 1
    with pytest.raises(ValueError):
        replace(p, publishers=list(p.publishers))
    with pytest.raises(ValueError):
        replace(p, publishers=p.publishers+p.publishers)


def test_nanos_raw_hash_and_local_availability_are_authoritative():
    r = GoldInstrumentRegistry(identity_policy=policy())
    record = future()
    v = ingest(r, record, at=NOW_NS+999, historical_retrieval_ns=NOW_NS+888)
    assert v.raw_record_bytes == bytes(record)
    assert v.provenance.record_sha256 == hashlib.sha256(bytes(record)).hexdigest()
    assert v.provenance.event_ns == NOW_NS-DAY+111
    assert v.provenance.provider_receive_ns == NOW_NS-DAY+222
    assert v.provenance.ingestion_ns == v.provenance.availability_ns == NOW_NS+999
    assert v.provenance.historical_retrieval_ns == NOW_NS+888
    assert v.provenance.availability_basis == "LOCAL_OBSERVATION"
    assert v.provenance.sequence is None and v.provenance.validity_flags is None
    assert v.namespace == "COMEX:GC:GCZ6" and "XAU" not in v.namespace
    with pytest.raises(ValueError, match="unavailable"):
        resolve(r, at=NOW_NS+998)
    assert resolve(r, at=NOW_NS+999) is v
    with pytest.raises(FrozenInstanceError):
        v.provenance.event_ns = 1


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "1", (1<<64)-1])
def test_invalid_nanosecond_clocks(value):
    with pytest.raises(ValueError):
        timestamp_ns(value)
    assert timestamp_ns(None, optional=True) is None


def test_duplicates_do_not_renew_original_availability():
    r = GoldInstrumentRegistry(identity_policy=policy())
    first = ingest(r, future())
    assert ingest(r, future(), at=NOW_NS+1000, ordinal=1) is first
    assert len(r.observations) == 1


def test_modify_delete_and_historical_resolution():
    r = GoldInstrumentRegistry(identity_policy=policy())
    first = ingest(r, future())
    changed = ingest(r, future(security_update_action=dbn.SecurityUpdateAction.MODIFY,
        ts_event=NOW_NS-1000, ts_recv=NOW_NS-500), at=NOW_NS+1000, ordinal=1)
    assert resolve(r, at=NOW_NS+999) is first
    assert resolve(r, at=NOW_NS+1000) is changed
    ingest(r, future(security_update_action=dbn.SecurityUpdateAction.DELETE,
        ts_event=NOW_NS, ts_recv=NOW_NS), at=NOW_NS+2000, ordinal=2)
    assert resolve(r, at=NOW_NS+1999) is changed
    with pytest.raises(ValueError, match="deleted"):
        resolve(r, at=NOW_NS+2000)


def test_rejected_update_quarantines_current_identity_but_retains_history():
    r = GoldInstrumentRegistry(identity_policy=policy())
    first = ingest(r, future())
    with pytest.raises(ValueError):
        ingest(r, future(currency="EUR"), at=NOW_NS+1000, ordinal=1)
    assert r.observations[-1].status == "QUARANTINED"
    assert resolve(r, at=NOW_NS+999) is first
    with pytest.raises(ValueError, match="quarantined"):
        resolve(r, at=NOW_NS+1000)


@pytest.mark.parametrize("changes", [
    {"raw_symbol": "GCG7", "maturity_month": 2, "maturity_year": 2027},
    {"expiration": EXPIRY+1},
    {"ts_event": NOW_NS-2*DAY, "ts_recv": NOW_NS-DAY},
])
def test_id_remapping_and_older_updates_fail_closed(changes):
    r = GoldInstrumentRegistry(identity_policy=policy())
    ingest(r, future())
    with pytest.raises(ValueError):
        ingest(r, future(**changes), at=NOW_NS+1000, ordinal=1)
    with pytest.raises(ValueError):
        resolve(r, at=NOW_NS+1000)


def test_option_exact_parent_join_and_opt_in_normalizer():
    r = GoldInstrumentRegistry(identity_policy=policy())
    parent = ingest(r, future())
    child = ingest(r, option(), at=NOW_NS+1000, ordinal=1, convention=STANDARD_OG)
    assert child.namespace == "COMEX:OG:OGZ6 C2500"
    assert child.canonical.underlying_contract == "GCZ6"
    assert child.underlying_record_sha256 == parent.provenance.record_sha256
    assert resolve(r, 50001, at=NOW_NS+1000) is child
    with pytest.raises(ValueError, match="publisher"):
        normalize_option(option(), futures={41271:parent.canonical},
            publishers=policy().mapping, now=NOW, convention=STANDARD_OG)


@pytest.mark.parametrize("changes", [
    {"underlying_id": 9}, {"underlying": "GCG7"}, {"asset": "OGW"},
    {"security_type": "OPT"}, {"strike_price_currency": "EUR"},
    {"expiration": EXPIRY+1}, {"leg_count": 1}, {"exchange": "XCME"},
])
def test_bad_option_joins_never_gain_identity(changes):
    r = GoldInstrumentRegistry(identity_policy=policy())
    ingest(r, future())
    with pytest.raises(ValueError):
        ingest(r, option(**changes), at=NOW_NS+1000, ordinal=1, convention=STANDARD_OG)
    with pytest.raises(ValueError):
        resolve(r, 50001, at=NOW_NS+1000)


def test_option_identity_and_underlying_update_invalidate_child():
    r = GoldInstrumentRegistry(identity_policy=policy())
    ingest(r, future())
    ingest(r, option(), at=NOW_NS+1000, ordinal=1, convention=STANDARD_OG)
    ingest(r, future(security_update_action=dbn.SecurityUpdateAction.MODIFY,
        ts_event=NOW_NS, ts_recv=NOW_NS), at=NOW_NS+2000, ordinal=2)
    with pytest.raises(ValueError, match="underlying changed"):
        resolve(r, 50001, at=NOW_NS+2000)
    # No silent rebind to the refreshed underlying record.
    with pytest.raises(ValueError, match="identity changed"):
        ingest(r, option(strike_price=2_600_000_000_000), at=NOW_NS+3000,
               ordinal=3, convention=STANDARD_OG)


def test_bounded_registry_and_explicit_ordering():
    r = GoldInstrumentRegistry(identity_policy=policy(), capacity=1)
    ingest(r, future())
    with pytest.raises(ValueError, match="out-of-order"):
        ingest(r, future())
    with pytest.raises(ValueError, match="full"):
        ingest(r, option(), at=NOW_NS+1000, ordinal=1, convention=STANDARD_OG)
    assert len(r.observations) == 1
    with pytest.raises(ValueError, match="coverage lost"):
        resolve(r, at=NOW_NS+1000)
    assert resolve(r, at=NOW_NS).status == "ACTIVE"


def test_same_nanosecond_cutoff_respects_explicit_ordinal():
    r = GoldInstrumentRegistry(identity_policy=policy())
    first = ingest(r, future())
    ingest(r, future(security_update_action=dbn.SecurityUpdateAction.DELETE), ordinal=1)
    assert r.resolve(publisher_id=1, instrument_id=41271, at_ns=NOW_NS,
                     through_ordinal=0) is first
    with pytest.raises(ValueError, match="deleted"):
        resolve(r)


def test_valid_refresh_recovers_quarantine_without_using_bad_event_watermark():
    r = GoldInstrumentRegistry(identity_policy=policy())
    ingest(r, future())
    with pytest.raises(ValueError):
        ingest(r, future(ts_event=NOW_NS+DAY, ts_recv=NOW_NS+DAY),
               at=NOW_NS+1000, ordinal=1)
    repaired = ingest(r, future(security_update_action=dbn.SecurityUpdateAction.MODIFY,
        ts_event=NOW_NS, ts_recv=NOW_NS), at=NOW_NS+2000, ordinal=2)
    assert resolve(r, at=NOW_NS+2000) is repaired
    with pytest.raises(ValueError, match="quarantined"):
        resolve(r, at=NOW_NS+1000)


def test_submicrosecond_observation_is_accepted_only_at_exact_cutoff():
    r = GoldInstrumentRegistry(identity_policy=policy())
    record = future(ts_event=NOW_NS+111, ts_recv=NOW_NS+222)
    value = ingest(r, record, at=NOW_NS+222)
    assert value.provenance.provider_receive_ns == NOW_NS+222
    with pytest.raises(ValueError, match="unavailable"):
        resolve(r, at=NOW_NS+221)
    assert resolve(r, at=NOW_NS+222) is value
    with pytest.raises(ValueError, match="contradicts"):
        policy().validate(record, publishers=policy().mapping, now=NOW,
                          cutoff_ns=NOW_NS+2000)


def test_overflow_cutoff_never_moves_forward_or_erases_earlier_ordinal():
    r = GoldInstrumentRegistry(identity_policy=policy(), capacity=1)
    first = ingest(r, future())
    with pytest.raises(ValueError, match="full"):
        ingest(r, option(), ordinal=1, convention=STANDARD_OG)
    assert r.resolve(publisher_id=1, instrument_id=41271, at_ns=NOW_NS,
                     through_ordinal=0) is first
    with pytest.raises(ValueError, match="full"):
        ingest(r, option(), at=NOW_NS+1000, ordinal=2, convention=STANDARD_OG)
    with pytest.raises(ValueError, match="coverage lost"):
        resolve(r)


def test_native_trade_and_quote_schema_reuse_keeps_gc_context_separate():
    r = GCReplay(publishers=policy().mapping, identity_policy=policy())
    r.add_definition(future(), now=NOW)
    r.select(41271, now=NOW, session_open=NOW-timedelta(hours=1),
             session_close=NOW+timedelta(hours=1))
    trade = dbn.TradeMsg(publisher_id=1, instrument_id=41271,
        ts_event=NOW_NS-2_000_000_000, ts_recv=NOW_NS-2_000_000_000,
        price=2_500_000_000_000, size=2, action=dbn.Action.TRADE,
        side=dbn.Side.BID, depth=0, flags=0, sequence=10)
    quote = dbn.MBP1Msg(publisher_id=1, instrument_id=41271,
        ts_event=NOW_NS-1_000_000_000, ts_recv=NOW_NS-1_000_000_000,
        price=(1<<63)-1, size=0, action=dbn.Action.ADD, side=dbn.Side.BID,
        depth=0, flags=0, sequence=11,
        levels=dbn.BidAskPair(bid_px=2_499_900_000_000,
                             ask_px=2_500_100_000_000, bid_sz=2, ask_sz=2))
    assert r.ingest("trades", trade, now=NOW)
    assert r.ingest("mbp-1", quote, now=NOW)
    assert r.snapshot(now=NOW)["status"] == "unavailable"
    r.complete_replay(covered_from=r.session[0], covered_to=NOW, now=NOW)
    result = r.snapshot(now=NOW)
    assert result["symbol"] == result["instrument_namespace"] == "COMEX:GC:GCZ6"
    assert result["context_for"] == "XAU/USD" and not result["execution_price_authority"]
    assert result["cvd_known_side"] == 2 and result["volume"] == 2
    assert broker_xauusd_namespace("FTMO_RESEARCH") == "BROKER:XAUUSD:FTMO_RESEARCH"
    for invalid in ("", "GCZ6:XCEC", "a/b", "user@server", None):
        with pytest.raises(ValueError):
            broker_xauusd_namespace(invalid)


def test_research_has_no_network_publishing_or_execution_construction(monkeypatch):
    import databento
    import socket
    def forbidden(*args, **kwargs):
        pytest.fail("Phase 1 must never construct/connect a provider client")
    monkeypatch.setattr(databento, "Historical", forbidden)
    monkeypatch.setattr(databento, "Live", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    r = GoldInstrumentRegistry(identity_policy=policy())
    ingest(r, future())
    assert resolve(r).namespace.startswith("COMEX:GC:")
    root = Path(__file__).parents[2] / "monatise"
    # Research registry has no production consumer; only optional policy hooks
    # exist in shared normalizers. No feature flag registers this research.
    for path in root.rglob("*.py"):
        if "research" in path.relative_to(root).parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("monatise.research.databento")
