"""Artificial engineering data only; no terminal, network or account login."""
import asyncio
import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from monatise.application.persistence import PostgresDocumentStore
from monatise.research.broker_xauusd.archive import BrokerObservationArchive, TABLE
from monatise.research.broker_xauusd.models import BrokerIdentity, TIMEFRAMES, INTERVAL_SECONDS, expected_opens, historical_plan
from monatise.research.broker_xauusd.replay import f0_input, prepare_replay
from tests.test_application_hierarchy import MemoryStore

UTC = timezone.utc
NOW = datetime(2026, 10, 5, 12, 0, 20, tzinfo=UTC)
START = NOW.replace(hour=8, minute=0, second=0)
END = NOW.replace(second=0)


class FixturePostgresStore(PostgresDocumentStore):
    """In-memory fake of research PG only; never used as durability proof."""
    def __init__(self):
        self._table = TABLE
        self.memory = MemoryStore()

    async def get(self, *args):
        return await self.memory.get(*args)

    async def put(self, *args, **kwargs):
        return await self.memory.put(*args, **kwargs)

    async def list_namespace(self, *args):
        return await self.memory.list_namespace(*args)


def manifest(offset=0):
    first = datetime(2026, 9, 1, tzinfo=UTC)
    last = datetime(2026, 10, 10, tzinfo=UTC)
    days = (last-first).days
    return {"schema": "gold-broker-sessions-v1", "account_id": "ENGINEERING_ONLY",
        "server": "SYNTHETIC_NOT_BROKER", "symbol": "XAU/USD",
        "source": "artificial engineering schedule, not broker certification", "version": "fixture-v1",
        "valid_from": first.isoformat(), "valid_until": last.isoformat(),
        "offsets": [{"from": first.isoformat(), "until": last.isoformat(), "seconds": offset}],
        "sessions": [{"open": (first + timedelta(days=i)).isoformat(),
                      "close": (first + timedelta(days=i+1)).isoformat()} for i in range(days)]}


def archive(store=None, *, calendar=None, symbol="XAUUSD"):
    clock = [NOW]
    result = BrokerObservationArchive(store or FixturePostgresStore(),
        identity=BrokerIdentity("SYNTHETIC", "ENGINEERING_ONLY", "SYNTHETIC_NOT_BROKER", symbol),
        calendar_manifest=calendar or manifest(), clock=lambda: clock[0])
    result.fixture_clock = clock
    return result


def payload(a, *, at=NOW, request_id="observation-1", received=None, history=False):
    opens = {tf: expected_opens(a.calendar, tf, START, END) for tf in TIMEFRAMES}
    if history:
        for tf in TIMEFRAMES:
            opens[tf] = tuple(sorted(set(opens[tf]) | {END-timedelta(seconds=i*INTERVAL_SECONDS[tf]) for i in range(1,61)}))
    return {"request_id": request_id, "account_id": a.identity.account_id, "server": a.identity.server,
        "symbol": a.identity.broker_symbol, "captured_at": at.isoformat(), "received_at": (received or at).isoformat(),
        "point": .01, "tick_size": .01, "spread_price": .2,
        "volume_kind": "tick_volume", "timestamp_policy": "current_offset_uncertified_history",
        "broker_time_offset": a.calendar.offset(at), "session_open": True,
        "session_close": a.calendar.session_close(at).isoformat(),
        "timeframes": {tf: [{"t": "provider assertion preserved verbatim",
            "t_broker": int(opened.timestamp()) + a.calendar.offset(opened),
            "o": 2500., "h": 2502., "l": 2498., "c": 2501., "v": 100}
            for opened in opens[tf]] for tf in TIMEFRAMES}}


async def add(a, p=None, *, kind="ENGINEERING_SYNTHETIC", at=None, **kwargs):
    p = p or payload(a)
    a.fixture_clock[0] = at or datetime.fromisoformat(p["received_at"])
    return await a.append(p, evidence_kind=kind, source_reference="synthetic fixture/source-v1",
                          capture_proof_reference="fixture reviewed capture" if kind == "POINT_IN_TIME_OBSERVATION" else None,
                          **kwargs)


async def prepared(a, *, at=NOW, kind="ENGINEERING_SYNTHETIC"):
    return await prepare_replay(a, cutoff=at, start=START, end=END, evidence_kind=kind)


def run(coroutine):
    return asyncio.run(coroutine)


def test_two_observations_finalize_all_timeframes_and_export_deterministically():
    async def scenario():
        a = archive()
        first = NOW - timedelta(seconds=10)
        await add(a, payload(a, at=first, history=True))
        one = await prepared(a, at=first)
        assert all(not c["latest_expected_finalized"] for c in one["coverage"].values())
        await add(a, payload(a, request_id="second", history=True))
        two = await prepared(a)
        assert two == await prepared(a)
        assert all(c["latest_expected_finalized"] for c in two["coverage"].values())
        assert two["f0_input_ready"] and not two["selector_invoked"]
        output = f0_input(a, two)
        assert output["schema"] == "gold-h1-fib-observation-archive-v1"
        assert output["observations"][0]["at"] == first.isoformat()
        assert output["source_commit"].startswith("0f12862")
        assert not two["execution_enabled"]
    run(scenario())


def test_duplicate_import_and_duplicate_capture_do_not_finalize():
    async def scenario():
        a = archive()
        p = payload(a)
        assert await add(a, p) == await add(a, p)
        await add(a, {**p, "request_id": "same-capture-new-id"})
        r = await prepared(a)
        assert len(await a.batches(cutoff=NOW)) == 2
        assert all(not c["latest_expected_finalized"] for c in r["coverage"].values())
        assert any(x["reason"] == "DUPLICATE_CAPTURE" for x in r["rejections"])
    run(scenario())


def test_revision_reopens_finalization_and_preserves_old_cutoff():
    async def scenario():
        a = archive()
        await add(a, payload(a, at=NOW-timedelta(seconds=10)))
        await add(a, payload(a, request_id="two"))
        before = await prepared(a)
        p = payload(a, at=NOW+timedelta(seconds=10), request_id="revision")
        p["timeframes"]["1h"][-1]["c"] = 2499
        await add(a, p)
        after = await prepared(a, at=NOW+timedelta(seconds=10))
        assert after["coverage"]["1h"]["latest_expected_finalized"] is False
        assert any(e["revision"] for e in after["events"])
        assert await prepared(a) == before
        p.update(request_id="revision-confirm", captured_at=(NOW+timedelta(seconds=20)).isoformat(), received_at=(NOW+timedelta(seconds=20)).isoformat())
        await add(a, p)
        final = await prepared(a, at=NOW+timedelta(seconds=20))
        assert final["coverage"]["1h"]["latest_expected_finalized"]
        assert len(await a.batches(cutoff=NOW+timedelta(seconds=20))) == 4
    run(scenario())


def test_forming_capture_delivered_late_cannot_finalize_by_receipt_clock():
    async def scenario():
        a = archive()
        p = payload(a, at=END+timedelta(seconds=5), received=NOW)
        await add(a, p)
        await add(a, payload(a, at=NOW+timedelta(seconds=1), request_id="first-closed"))
        r = await prepared(a, at=NOW+timedelta(seconds=1))
        assert not r["coverage"]["1h"]["latest_expected_finalized"]
        await add(a, payload(a, at=NOW+timedelta(seconds=2), request_id="second-closed"))
        assert (await prepared(a, at=NOW+timedelta(seconds=2)))["coverage"]["1h"]["latest_expected_finalized"]
    run(scenario())


def test_late_ingestion_has_no_historical_availability_and_out_of_order_is_rejected():
    async def scenario():
        a = archive()
        await add(a, payload(a), at=NOW+timedelta(hours=1))
        assert not await a.batches(cutoff=NOW)
        p = payload(a, at=NOW-timedelta(seconds=10), request_id="late-old-capture")
        p["timeframes"]["1h"][-1]["c"] = 2499
        await add(a, p, at=NOW+timedelta(hours=1, seconds=10))
        r = await prepared(a, at=NOW+timedelta(hours=1, seconds=10))
        assert any(x["reason"] == "OUT_OF_ORDER_CAPTURE" for x in r["rejections"])
        assert not any(e["revision"] for e in r["events"])
    run(scenario())


@pytest.mark.parametrize("kind", ["RETROSPECTIVE_HISTORICAL_DOWNLOAD", "POINT_IN_TIME_OBSERVATION"])
def test_real_evidence_is_never_promoted_to_synthetic_or_phase4_ready(kind):
    async def scenario():
        a = archive()
        await add(a, payload(a, at=NOW-timedelta(seconds=10)), kind=kind)
        await add(a, payload(a, request_id="second"), kind=kind)
        r = await prepared(a, kind=kind)
        assert not r["f0_input_ready"]
        assert not (await prepared(a))["batch_ids"]
        with pytest.raises(ValueError, match="blocked"):
            f0_input(a, r)
        if kind.startswith("RETROSPECTIVE"):
            assert all(not e["point_in_time_eligible"] for e in r["events"])
    run(scenario())


@pytest.mark.parametrize("tf", TIMEFRAMES)
def test_missing_candle_or_timeframe_is_reported_without_synthesis(tf):
    async def scenario():
        a = archive()
        p = payload(a)
        p["timeframes"][tf].pop()
        await add(a, p)
        r = await prepared(a)
        assert r["coverage"][tf]["missing"]
        assert not r["f0_input_ready"]
    run(scenario())


@pytest.mark.parametrize("change", ["account", "server", "symbol", "future", "duplicate", "unordered", "epoch_bool", "epoch_float", "boundary", "nan", "negative_volume", "zero_low", "units", "offset", "naive", "clock_order", "capture_future", "timeframe", "volume_kind", "no_proof"])
def test_bad_evidence_fail_closed_before_writes(change):
    a = archive()
    p = payload(a)
    kw = dict(evidence_kind="ENGINEERING_SYNTHETIC", source_reference="fixture")
    row = p["timeframes"]["1m"][-1]
    if change == "account": p["account_id"] = "other"
    elif change == "server": p["server"] = "other"
    elif change == "symbol": p["symbol"] = "GCZ6"
    elif change == "future": row["t_broker"] = int((NOW+timedelta(minutes=1)).timestamp())
    elif change == "duplicate": p["timeframes"]["1m"].append(dict(row))
    elif change == "unordered": p["timeframes"]["1m"].reverse()
    elif change == "epoch_bool": row["t_broker"] = True
    elif change == "epoch_float": row["t_broker"] = float(row["t_broker"])
    elif change == "boundary": row["t_broker"] += 1
    elif change == "nan": row["c"] = float("nan")
    elif change == "negative_volume": row["v"] = -1
    elif change == "zero_low": row["l"] = 0
    elif change == "units": p["point"] = 0
    elif change == "offset": p["broker_time_offset"] = 3600
    elif change == "naive": p["captured_at"] = "2026-10-05T12:00:20"
    elif change == "clock_order": p["received_at"] = (NOW-timedelta(seconds=1)).isoformat()
    elif change == "capture_future": p["captured_at"] = (NOW+timedelta(seconds=1)).isoformat()
    elif change == "timeframe": p["timeframes"]["2h"] = []
    elif change == "volume_kind": p["volume_kind"] = "gc_exchange_volume"
    else: kw["evidence_kind"] = "POINT_IN_TIME_OBSERVATION"
    with pytest.raises(ValueError):
        run(a.append(p, **kw))
    assert not a.store.memory.documents


def test_original_wall_clock_and_provider_assertion_are_retained():
    a = archive(calendar=manifest(7200), symbol="XAUUSDm")
    p = payload(a)
    body = a.prepare(p, evidence_kind="ENGINEERING_SYNTHETIC", source_reference="fixture")
    assert body["raw_payload"] == p
    r = body["rows"][-1]
    assert r["original"]["t_broker"] == int(datetime.fromisoformat(r["opened_at"]).timestamp()) + 7200
    assert r["original"]["t"] == "provider assertion preserved verbatim"
    assert body["namespace"].startswith("BROKER:XAUUSD:")


def test_request_id_conflict_and_integrity_tampering_are_detected():
    async def scenario():
        a = archive()
        p = payload(a)
        await add(a, p)
        p["timeframes"]["1h"][0]["c"] = 2499
        with pytest.raises(ValueError, match="conflict"):
            await add(a, p)
        records = list(a.store.memory.documents.values())
        records[0].value["rows"][0]["candle"]["close"] = 2499
        with pytest.raises(ValueError, match="integrity"):
            await a.batches(cutoff=NOW)
    run(scenario())


def test_orphan_batch_is_excluded_until_explicit_idempotent_admission_retry():
    async def scenario():
        a = archive()
        p = payload(a)
        body = a.prepare(p, evidence_kind="ENGINEERING_SYNTHETIC", source_reference="synthetic fixture/source-v1")
        await a._create("batch:"+body["batch_id"], body)
        assert not await a.batches(cutoff=NOW)
        await add(a, p, at=NOW+timedelta(seconds=1))
        assert not await a.batches(cutoff=NOW)
        assert len(await a.batches(cutoff=NOW+timedelta(seconds=1))) == 1
    run(scenario())


def test_plans_are_bounded_pure_and_keep_all_five_timeframes():
    a = archive()
    plan = historical_plan(a.identity, a.calendar, start=START, end=END, page_bars=50)
    assert {p["timeframe"] for p in plan["pages"]} == set(TIMEFRAMES)
    assert all(p["expected_bars"] <= 50 for p in plan["pages"])
    assert plan["requires_separate_connection_authorization"] and not plan["execution_enabled"]
    with pytest.raises(ValueError):
        historical_plan(a.identity, a.calendar, start="2026-10-01T00:00:00Z", end="2026-10-10T00:00:00Z")


def test_sessions_holidays_and_historical_offsets_are_not_generic_24h_grids():
    from monatise.application.gold_sessions import GoldSessionCalendar
    from tests.test_gold_sessions import manifest as reviewed_fixture
    calendar = GoldSessionCalendar.from_manifest(reviewed_fixture())
    rows = expected_opens(calendar, "15m", "2026-10-23T00:00:00Z", "2026-10-29T00:00:00Z")
    assert all(r.weekday() < 5 and r.day != 27 for r in rows)
    assert not any(r.day == 26 and r.hour == 21 for r in rows)
    h4 = expected_opens(calendar, "4h", "2026-10-26T00:00:00Z", "2026-10-27T00:00:00Z")
    assert any(r.hour == 10 for r in h4) and not any(r.hour == 20 for r in h4)


def test_genuine_store_requires_isolated_table_and_gc_cannot_map_to_spot():
    with pytest.raises(ValueError, match="isolated"):
        archive(PostgresDocumentStore(object()))
    with pytest.raises(ValueError, match="GC"):
        BrokerIdentity("fixture", "fixture", "fixture", "GCZ6")
    with pytest.raises(ValueError, match="GC"):
        BrokerIdentity("fixture", "fixture", "fixture", "XAUUSD", symbol="GC")


def test_research_import_graph_has_no_transport_execution_or_selector_dependencies():
    root = Path(__file__).parents[2]/"monatise/research/broker_xauusd"
    forbidden = ("monatise.application.ftmo", "monatise.application.telegram", "monatise.research.gold_fib",
                 "monatise.research.databento", "MetaTrader5", "requests", "urllib", "httpx", "socket")
    for file in root.glob("*.py"):
        tree = ast.parse(file.read_text())
        for node in ast.walk(tree):
            modules = [node.module or ""] if isinstance(node, ast.ImportFrom) else [n.name for n in node.names] if isinstance(node, ast.Import) else []
            assert not any(m.startswith(forbidden) for m in modules)
    # No live server, worker, scheduler or approval route imports this package.
    for folder in ("application", "live"):
        for file in (root.parents[1]/folder).rglob("*.py"):
            assert "research.broker_xauusd" not in file.read_text()


def test_exact_value_revision_hidden_by_canonical_12_digit_hash_blocks_export():
    async def scenario():
        a = archive()
        await add(a, payload(a, at=NOW-timedelta(seconds=10)))
        await add(a, payload(a, request_id="two"))
        p = payload(a, at=NOW+timedelta(seconds=10), request_id="tiny-revision")
        p["timeframes"]["1h"][-1]["c"] += 1e-9
        await add(a, p)
        result = await prepared(a, at=NOW+timedelta(seconds=10))
        assert "NORMALIZER_HASH_COLLISION" in result["blockers"]
        assert not result["coverage"]["1h"]["latest_expected_finalized"]
    run(scenario())


def test_ambiguous_availability_and_receipt_tampering_fail_closed():
    async def scenario():
        a = archive()
        await add(a, payload(a, at=NOW-timedelta(seconds=10)), at=NOW)
        await add(a, payload(a, request_id="two"), at=NOW)
        r = await prepared(a)
        assert "AMBIGUOUS_OBSERVATION_AVAILABILITY" in r["blockers"]
        receipt = next(d for d in a.store.memory.documents.values() if d.key.startswith("admission:"))
        receipt.value["ingested_and_available_at"] = (NOW-timedelta(days=1)).isoformat()
        with pytest.raises(ValueError, match="integrity"):
            await a.batches(cutoff=NOW)
    run(scenario())


def test_historical_offset_era_is_used_and_ambiguous_wall_hour_rejected():
    from monatise.application.gold_sessions import GoldSessionCalendar
    from tests.test_gold_sessions import manifest as reviewed_fixture
    m = reviewed_fixture()
    m.update(account_id="ENGINEERING_ONLY", server="SYNTHETIC_NOT_BROKER")
    a = archive(calendar=m)
    a.fixture_clock[0] = datetime(2026, 10, 26, 12, tzinfo=UTC)
    captured = a.fixture_clock[0]
    opened = datetime(2026, 10, 23, 12, tzinfo=UTC)
    p = {"request_id": "historical-era", "account_id": a.identity.account_id, "server": a.identity.server,
         "symbol": "XAUUSD", "captured_at": captured.isoformat(), "received_at": captured.isoformat(),
         "point": .01, "tick_size": .01, "spread_price": .2, "broker_time_offset": 7200,
         "timestamp_policy": "current_offset_uncertified_history", "timeframes": {"1h": [
             {"t_broker": int(opened.timestamp())+10800, "t": "wrong current offset assertion",
              "o": 2500, "h": 2502, "l": 2498, "c": 2501, "v": 1}]}}
    b = a.prepare(p, evidence_kind="RETROSPECTIVE_HISTORICAL_DOWNLOAD", source_reference="synthetic historical export")
    assert b["rows"][0]["opened_at"] == opened.isoformat()
    p["timeframes"]["1h"][0]["t_broker"] = int(datetime(2026,10,25,3,30,tzinfo=UTC).timestamp())
    with pytest.raises(ValueError, match="ambiguous"):
        a.prepare(p, evidence_kind="RETROSPECTIVE_HISTORICAL_DOWNLOAD", source_reference="synthetic export")


def test_window_bounds_and_empty_evidence_and_boolean_offset():
    a = archive()
    p = payload(a)
    with pytest.raises(ValueError, match="outside declared"):
        a.prepare(p, evidence_kind="ENGINEERING_SYNTHETIC", source_reference="fixture",
                  window={"start": END.isoformat(), "end": (END+timedelta(hours=1)).isoformat()})
    p["broker_time_offset"] = False
    with pytest.raises(ValueError, match="offset"):
        a.prepare(p, evidence_kind="ENGINEERING_SYNTHETIC", source_reference="fixture")
    with pytest.raises(ValueError, match="real evidence"):
        b = BrokerObservationArchive(MemoryStore(), identity=a.identity, calendar_manifest=manifest(), engineering_store=True)
        b.prepare(payload(a), evidence_kind="RETROSPECTIVE_HISTORICAL_DOWNLOAD", source_reference="fixture")


def test_calendar_and_source_metadata_cannot_mutate_archived_provenance_by_alias():
    a = archive()
    original = a.calendar_manifest
    original["version"] = "tampered"
    assert a.calendar_manifest["version"] == "fixture-v1"
    window = {"start": START.isoformat(), "end": END.isoformat()}
    body = a.prepare(payload(a), evidence_kind="ENGINEERING_SYNTHETIC", source_reference="fixture", window=window)
    window["start"] = END.isoformat()
    assert body["window"]["start"] == START.isoformat()


def test_old_history_acquired_today_requires_separate_reviewed_capture_calendar():
    a = archive()
    p = payload(a)
    acquired = datetime(2027, 1, 2, 12, tzinfo=UTC)
    a.fixture_clock[0] = acquired
    p.update(captured_at=acquired.isoformat(), received_at=acquired.isoformat(), broker_time_offset=7200)
    with pytest.raises(ValueError, match="coverage"):
        a.prepare(p, evidence_kind="RETROSPECTIVE_HISTORICAL_DOWNLOAD", source_reference="synthetic old export")
    current = manifest(7200)
    start = acquired.replace(hour=0)
    end = start+timedelta(days=1)
    current.update(valid_from=start.isoformat(), valid_until=end.isoformat(),
        offsets=[{"from":start.isoformat(),"until":end.isoformat(),"seconds":7200}],
        sessions=[{"open":start.isoformat(),"close":end.isoformat()}])
    body = a.prepare(p, evidence_kind="RETROSPECTIVE_HISTORICAL_DOWNLOAD", source_reference="synthetic old export",
                     capture_calendar_manifest=current)
    assert body["rows"][0]["opened_at"].startswith("2026-10-05")
    assert body["raw_payload"]["captured_at"].startswith("2027-01-02")
    assert body["capture_calendar_fingerprint"] != body["calendar_fingerprint"]
    current["account_id"] = "other"
    with pytest.raises(ValueError, match="identity"):
        a.prepare(p, evidence_kind="RETROSPECTIVE_HISTORICAL_DOWNLOAD", source_reference="synthetic old export",
                  capture_calendar_manifest=current)
