"""Offline engineering fixtures, never market-performance evidence."""
import asyncio
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from monatise.application.persistence import PostgresDocumentStore
from monatise.research.databento.acquisition import (
    ApprovedDownload, DownloadPreflight, HistoricalAcquisition, HistoricalMetadata,
    HistoricalRequest, SDKHistoricalSource, inspect_request_archive,
)
from monatise.research.databento.archive import NativeDBNArchive, dbn_records, sha256_file
from monatise.research.databento.replay import (
    CoverageAttestation, HistoricalGCReference, HistoricalGCReplay, ReplayConfig,
    normalize_record, replay_archive,
)
from tests.research.test_databento_foundations import NOW_NS, DAY, future, policy

dbn = pytest.importorskip("databento_dbn")
START = NOW_NS - DAY + 300
END = START + 10**9


def request(**kwargs):
    params = dict(dataset="GLBX.MDP3", schema="trades", contracts=((1, 41271, "GCZ6"),),
                  start_ns=START, end_ns=END, record_limit=100)
    params.update(kwargs)
    return HistoricalRequest(**params)


def preflight(req=None, **kwargs):
    req = req or request()
    params = dict(request_sha256=req.sha256, observed_at_ns=NOW_NS-1000,
        available_from_ns=START-1, available_to_ns=END+1, estimated_usd="1.97",
        schema_available=True, identities_verified=True, metadata_sha256="a"*64,
        entitlement="VERIFIED_OPERATOR")
    params.update(kwargs)
    return DownloadPreflight(**params)


def approval(req=None, pre=None, **kwargs):
    req = req or request()
    pre = pre or preflight(req)
    params = dict(approval_id="review-1", review_reference="human-test-fixture-approval",
        request_sha256=req.sha256, preflight_sha256=pre.sha256, approved_at_ns=NOW_NS-500,
        expires_at_ns=NOW_NS+1000, max_estimated_usd="2.00", entitlement_reference="fixture-license",
        estimate_is_not_charge_cap_acknowledged=True, verified_credit_usd="125.00",
        credit_checked_at_ns=NOW_NS-1000, credit_expires_at_ns=NOW_NS+DAY,
        credit_balance_reference="fixture-not-real-balance")
    params.update(kwargs)
    return ApprovedDownload(**params)


def trade(*, offset=100, **kwargs):
    args = dict(publisher_id=1, instrument_id=41271, ts_event=START+offset,
        ts_recv=START+offset+1, price=2500_000_000_000, size=2, action=dbn.Action.TRADE,
        side=dbn.Side.BID, depth=0, sequence=offset, flags=0)
    args.update(kwargs)
    return dbn.TradeMsg(**args)


def write_dbn(path, req, records, *, compressed=False):
    header = dbn.Metadata(dataset=req.dataset, start=req.start_ns, end=req.end_ns,
        stype_in=dbn.SType.RAW_SYMBOL, stype_out=dbn.SType.INSTRUMENT_ID,
        schema=dbn.Schema(req.schema), symbols=[c[2] for c in req.contracts],
        limit=req.record_limit, version=3)
    payload = header.encode() + b"".join(bytes(record) for record in records)
    if compressed:
        import zstandard
        payload = zstandard.ZstdCompressor().compress(payload)
    Path(path).write_bytes(payload)


class SQLFixtureConnection:
    """CAS document-store SQL fixture; live DB tested separately, not claimed here."""
    def __init__(self):
        self.rows = {}
    async def fetchrow(self, query, *args):
        if query.startswith("INSERT"):
            namespace, key, payload, expected = args
            old = self.rows.get((namespace, key))
            if old and expected is not None and expected != old["version"]:
                return None
            value = dict(value=json.loads(payload), version=old["version"]+1 if old else 1)
            self.rows[namespace, key] = value
            return dict(version=value["version"])
        assert query.startswith("SELECT")
        return self.rows.get(tuple(args))


class FixtureSource:
    evidence_kind = "ENGINEERING_SYNTHETIC"
    def __init__(self, records, *, fail=False, compressed=True):
        self.records, self.fail, self.compressed = records, fail, compressed
        self.calls = 0
    def download(self, req, path, *, preflight=None, approval=None):
        self.calls += 1
        write_dbn(path, req, self.records, compressed=self.compressed)
        if self.fail:
            raise RuntimeError("private provider error must not leak")


def service(tmp_path, source=None):
    metadata = HistoricalMetadata(PostgresDocumentStore(SQLFixtureConnection()))
    archive = NativeDBNArchive(tmp_path)
    source = source or FixtureSource([trade(), trade(offset=101, side=dbn.Side.ASK)])
    return HistoricalAcquisition(metadata=metadata, archive=archive, source=source,
                                 clock_ns=lambda: NOW_NS)


def acquired(svc, req=None):
    req = req or request()
    p = preflight(req)
    return asyncio.run(svc.acquire(req, p, approval(req, p)))


def reference():
    return HistoricalGCReference.reconstruct(future(), identity_policy=policy(), retrieval_ns=NOW_NS)


def config(req=None, **kwargs):
    req = req or request()
    params = dict(start_ns=req.start_ns, end_ns=req.end_ns, session_open_ns=START-1000,
        session_close_ns=END+1000, session_calendar_reference="synthetic-reviewed-session")
    params.update(kwargs)
    return ReplayConfig(**params)


def observation(record=None, req=None, ordinal=0):
    return normalize_record(record or trade(), request=req or request(), reference=reference(),
                            ordinal=ordinal, ingestion_ns=NOW_NS, retrieval_ns=NOW_NS)


@pytest.mark.parametrize("changes", [
    {"contracts": ((1, 1, "ALL_SYMBOLS"),)}, {"contracts": ((1, 1, "GC.v.0"),)},
    {"contracts": []}, {"contracts": ((True, 1, "GCZ6"),)},
    {"contracts": ((1, 1, "GCZ6"), (1, 2, "GCZ6"))},
    {"end_ns": START}, {"end_ns": START+8*DAY}, {"start_ns": 1.2},
    {"record_limit": True}, {"record_limit": 1_000_001}, {"wire_byte_limit": 1},
    {"dataset": "OTHER"}, {"schema": "mbo"},
])
def test_unbounded_unknown_or_ambiguous_requests_rejected(changes):
    with pytest.raises(ValueError):
        request(**changes)


@pytest.mark.parametrize("changes", [
    {"request_sha256": "b"*64}, {"preflight_sha256": "b"*64},
    {"expires_at_ns": NOW_NS}, {"approved_at_ns": NOW_NS+1},
    {"max_estimated_usd": "1.96"}, {"max_estimated_usd": "NaN"},
    {"estimate_is_not_charge_cap_acknowledged": False},
    {"verified_credit_usd": None}, {"verified_credit_usd": "1.99"},
    {"credit_checked_at_ns": NOW_NS-301*10**9}, {"credit_expires_at_ns": NOW_NS},
    {"credit_balance_reference": "unsafe reference with spaces"},
])
def test_explicit_credit_and_exact_cost_approval_gates(changes):
    with pytest.raises(ValueError):
        approval(**changes).validate(request(), preflight(), NOW_NS)


@pytest.mark.parametrize("changes", [{"entitlement": "UNKNOWN"}, {"entitlement": "DENIED"},
    {"identities_verified": False}, {"schema_available": False},
    {"available_to_ns": END-1}, {"observed_at_ns": NOW_NS-301*10**9}])
def test_metadata_success_never_implies_entitlement_or_coverage(changes):
    p = preflight(**changes)
    with pytest.raises(ValueError):
        approval(pre=p).validate(request(), p, NOW_NS)


def test_download_archival_immutable_hashes_provenance_and_dedup(tmp_path):
    svc = service(tmp_path)
    result = acquired(svc)
    assert svc.source.calls == 1 and result["status"] == "ARCHIVED"
    assert result["actual_billed_usd"] is None and result["coverage"]["coverage_state"] == "UNCERTIFIED"
    assert result["retrieval_ns"] == result["availability_ns"] == NOW_NS
    path = svc.archive.verify(result["archive_sha256"])
    assert path.stat().st_mode & 0o222 == 0
    assert sha256_file(path) == result["archive_sha256"]
    assert acquired(svc) == result and svc.source.calls == 1
    records = list(dbn_records(path))
    assert bytes(records[1]) == bytes(trade())
    assert records[1].ts_event == START+100 and records[1].ts_recv == START+101
    assert not result["trading_eligible"]
    assert result["evidence_kind"] == "ENGINEERING_SYNTHETIC"


def test_failed_partial_is_quarantined_and_never_automatically_retried(tmp_path):
    svc = service(tmp_path, FixtureSource([trade()], fail=True))
    with pytest.raises(RuntimeError, match="no automatic") as failure:
        acquired(svc)
    assert "private provider" not in str(failure.value)
    row = asyncio.run(svc.metadata.get("request:"+request().sha256))
    assert row.value["status"] == "QUARANTINED" and row.value["quarantine_sha256"]
    assert row.value["actual_cost_status"] == "RECONCILIATION_REQUIRED"
    with pytest.raises(RuntimeError, match="reconciliation"):
        acquired(svc)
    assert svc.source.calls == 1 and len(list((tmp_path/"quarantine").iterdir())) == 1


def test_retrieval_and_bulk_admission_are_separate_observations(tmp_path):
    svc = service(tmp_path)
    clocks = iter([NOW_NS, NOW_NS+100, NOW_NS+200])
    svc.clock_ns = lambda: next(clocks)
    result = acquired(svc)
    assert result["retrieval_ns"] == NOW_NS+100
    assert result["ingestion_ns"] == result["availability_ns"] == NOW_NS+200
    assert result["ingestion_basis"] == "BULK_ARCHIVE_ADMISSION"


def test_post_seal_metadata_failure_reconciles_without_downloading_again(tmp_path):
    svc = service(tmp_path)
    original = svc.metadata.replace
    async def fail(previous, value):
        if value["status"] == "ARCHIVED":
            raise RuntimeError("simulated metadata outage")
        return await original(previous, value)
    svc.metadata.replace = fail
    with pytest.raises(RuntimeError, match="metadata outage"):
        acquired(svc)
    digest = next((tmp_path/"objects").iterdir()).stem
    assert not list((tmp_path/"staging").iterdir()) and svc.source.calls == 1
    svc.metadata.replace = original
    result = asyncio.run(svc.reconcile(request(), archive_sha256=digest, confirmed_transport_complete=True))
    assert result["status"] == "ARCHIVED" and result["retrieval_ns"] is None and svc.source.calls == 1


def test_limit_reached_quarantines_instead_of_claiming_complete(tmp_path):
    req = request(record_limit=1)
    svc = service(tmp_path, FixtureSource([trade()]))
    with pytest.raises(RuntimeError, match="quarantined"):
        acquired(svc, req)
    assert svc.source.calls == 1


@pytest.mark.parametrize("compressed", [False, True])
def test_truncated_dbn_and_compressed_frames_fail_closed(tmp_path, compressed):
    path = tmp_path/"native.dbn"
    write_dbn(path, request(), [trade()], compressed=compressed)
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises((ValueError, RuntimeError)):
        list(dbn_records(path))


def test_native_decoder_limits_and_hash_corruption(tmp_path):
    svc = service(tmp_path)
    result = acquired(svc)
    path = svc.archive.verify(result["archive_sha256"])
    with pytest.raises(ValueError, match="record capacity"):
        list(dbn_records(path, max_records=1))
    with pytest.raises(ValueError, match="byte capacity"):
        list(dbn_records(path, max_decoded_bytes=1))
    path.chmod(0o600)
    path.write_bytes(path.read_bytes()+b"bad")
    with pytest.raises(ValueError, match="integrity"):
        svc.archive.verify(result["archive_sha256"])


def test_restart_reserved_partial_and_sealed_orphan_recovery_are_local(tmp_path):
    svc = service(tmp_path)
    req = request()
    value = dict(status="RESERVED", request_sha256=req.sha256)
    asyncio.run(svc.metadata.create("request:"+req.sha256, value))
    write_dbn(svc.archive.staging(req.sha256), req, [trade()])
    digest = svc.archive.seal(req.sha256)
    recovered = asyncio.run(svc.reconcile(req, archive_sha256=digest, confirmed_transport_complete=True))
    assert recovered["status"] == "ARCHIVED" and recovered["retrieval_ns"] is None
    assert recovered["availability_ns"] == NOW_NS and svc.source.calls == 0
    assert recovered["coverage"]["coverage_state"] == "UNCERTIFIED"
    other = request(end_ns=END+1)
    asyncio.run(svc.metadata.create("request:"+other.sha256, dict(status="RESERVED", request_sha256=other.sha256)))
    write_dbn(svc.archive.staging(other.sha256), other, [trade()])
    assert asyncio.run(svc.reconcile(other))["status"] == "QUARANTINED"
    assert svc.source.calls == 0


def test_concurrent_download_reservation_prevents_two_requests(tmp_path):
    svc = service(tmp_path)
    async def run():
        req, p = request(), preflight()
        return await asyncio.gather(svc.acquire(req, p, approval()), svc.acquire(req, p, approval()), return_exceptions=True)
    results = asyncio.run(run())
    assert len([r for r in results if isinstance(r, dict)]) == 1
    assert svc.source.calls == 1


def test_reconstruction_preserves_expired_contract_without_false_pit_certification():
    record = future(expiration=START+5000)
    ref = HistoricalGCReference.reconstruct(record, identity_policy=policy(), retrieval_ns=NOW_NS)
    assert ref.expiration_ns < NOW_NS and ref.availability_ns == NOW_NS
    assert ref.knowledge_basis == "RETROSPECTIVE_REFERENCE_RECONSTRUCTION"
    assert ref.contract.raw_symbol == "GCZ6"
    with pytest.raises(ValueError):
        HistoricalGCReference.reconstruct(future(exchange="XCME"), identity_policy=policy(), retrieval_ns=NOW_NS)


def test_normalization_keeps_nanos_missing_clocks_and_local_availability_separate():
    o = observation()
    assert o.event_ns == START+100 and o.provider_receive_ns == START+101
    assert o.availability_ns == NOW_NS and o.event_ns != o.availability_ns
    assert o.record_sha256 == hashlib.sha256(bytes(trade())).hexdigest()
    req = request(schema="ohlcv-1m")
    record = dbn.OHLCVMsg(rtype=dbn.RType.OHLCV_1M, publisher_id=1, instrument_id=41271,
        ts_event=START+100, open=2500_000_000_000, high=2501_000_000_000,
        low=2499_000_000_000, close=2500_000_000_000, volume=100)
    candle = observation(record, req)
    assert candle.provider_receive_ns is None and candle.sequence is None and candle.flags is None
    assert candle.availability_ns == NOW_NS
    with pytest.raises(ValueError, match="rtype"):
        observation(record, request(schema="ohlcv-1h"))


def test_required_trade_receive_time_cannot_fall_back_to_event_time(tmp_path):
    record = trade(ts_recv=(1<<64)-1)
    with pytest.raises(ValueError, match="receive timestamp unavailable"):
        observation(record)
    path = tmp_path/"missing-receive.dbn"
    write_dbn(path, request(), [record])
    with pytest.raises(ValueError, match="receive timestamp unavailable"):
        inspect_request_archive(path, request())


def test_incremental_trade_quote_volume_and_side_semantics():
    replay = HistoricalGCReplay(reference=reference(), config=config(), publishers=policy().mapping)
    assert replay.consume(observation())
    assert not replay.consume(observation(ordinal=1))
    assert replay.consume(observation(trade(offset=101, side=dbn.Side.ASK), ordinal=2))
    assert replay.consume(observation(trade(offset=102, side=dbn.Side.NONE), ordinal=3))
    quote = dbn.MBP1Msg(publisher_id=1, instrument_id=41271, ts_event=START+103,
        ts_recv=START+104, price=2500_000_000_000, size=999, action=dbn.Action.TRADE,
        side=dbn.Side.BID, depth=0, sequence=103, flags=0,
        levels=dbn.BidAskPair(bid_px=2500_000_000_000, ask_px=2500_100_000_000, bid_sz=2, ask_sz=3))
    assert replay.consume(observation(quote, request(schema="mbp-1"), ordinal=4))
    result = replay.result()
    assert result["volume"] == 6 and result["duplicates"] == 1 and result["cvd_known_side"] == 0
    assert result["known_side_volume"] == 4 and not result["cvd_complete"]
    assert result["vwap"] == "2500" and result["poc_fixed"] == 2500_000_000_000
    assert result["quote_ns"] == START+104 and not result["execution_price_authority"]


@pytest.mark.parametrize("changes,reason", [
    ({"action": dbn.Action.CANCEL}, "unsupported_trade_correction"),
    ({"flags": 8}, "bad_receive_timestamp"),
    ({"price": 2500_000_000_001}, "record_quality_rejected"),
])
def test_corrections_and_invalid_flags_quarantine_derived_results(changes, reason):
    replay = HistoricalGCReplay(reference=reference(), config=config(), publishers=policy().mapping)
    assert not replay.consume(observation(trade(**changes)))
    assert reason in replay.gaps and replay.result()["volume"] == 0


def test_bounded_profile_dedup_and_filtered_sequence_do_not_invent_gaps():
    replay = HistoricalGCReplay(reference=reference(), config=config(dedup_capacity=1, profile_capacity=1), publishers=policy().mapping)
    assert replay.consume(observation(trade(sequence=1)))
    assert replay.consume(observation(trade(offset=101, sequence=99999)))
    assert not replay.gaps and len(replay.recent) == 1
    assert not replay.consume(observation(trade()))
    assert "out_of_order_or_old_duplicate" in replay.gaps and replay.total_volume == 4
    assert not replay.consume(observation(trade(offset=102, price=2500_100_000_000)))
    assert "volume_profile_capacity_exceeded" in replay.gaps and len(replay.profile) == 1


@pytest.mark.parametrize("arm,expected", [
    ("none", "UNCERTIFIED"), ("complete", "COMPLETE"), ("gap", "GAPPED"),
    ("stale", "STALE"), ("mismatch", "UNCERTIFIED"), ("partial", "PARTIAL"),
])
def test_coverage_is_independent_of_recent_records(tmp_path, arm, expected):
    svc = service(tmp_path)
    manifest = acquired(svc)
    attestation = CoverageAttestation(manifest["archive_sha256"], request().sha256,
        "synthetic-continuity-audit", START, END, 2)
    if arm == "none":
        attestation = None
    if arm == "gap":
        attestation = replace(attestation, gaps=("external_transport_gap",))
    if arm == "mismatch":
        attestation = replace(attestation, expected_records=3)
    replay = replay_archive(archive=svc.archive, manifest=manifest, request=request(), reference=reference(),
        config=config(), attestation=attestation, assessed_at_ns=END+(11*10**9 if arm == "stale" else 1))
    if arm == "partial":
        partial = {**manifest, "coverage": {**manifest["coverage"], "transport_complete": False}}
        replay.finish(manifest=partial, assessed_at_ns=END+1)
    assert replay.coverage_state == expected
    assert not replay.result()["trading_eligible"]


def test_deterministic_replay_prefix_restart_and_durable_checkpoint(tmp_path):
    svc = service(tmp_path)
    manifest = acquired(svc)
    partial = HistoricalGCReplay(reference=reference(), config=config(), publishers=policy().mapping)
    partial.consume(observation())
    checkpoint = partial.checkpoint(manifest["archive_sha256"])
    row = asyncio.run(svc.metadata.checkpoint("replay-test", checkpoint))
    assert row.value == checkpoint
    checkpoint = asyncio.run(svc.metadata.get("checkpoint:replay-test")).value
    kwargs = dict(archive=svc.archive, manifest=manifest, request=request(), reference=reference(),
                  config=config(), assessed_at_ns=END+1)
    resumed = replay_archive(**kwargs, checkpoint=checkpoint).result()
    assert resumed == replay_archive(**kwargs).result()
    assert resumed["input_records"] == 2 and resumed["volume"] == 4
    with pytest.raises(ValueError, match="corrupted"):
        replay_archive(**kwargs, checkpoint={**checkpoint, "rolling_sha256": "b"*64})
    with pytest.raises(ValueError, match="incompatible"):
        replay_archive(**kwargs, checkpoint={**checkpoint, "archive_sha256": "b"*64})
    with pytest.raises(ValueError, match="backwards"):
        asyncio.run(svc.metadata.checkpoint("replay-test", {**checkpoint, "record_ordinal": 0}))


def test_sdk_transport_is_bounded_no_retry_no_redirect_and_private_errors(monkeypatch, tmp_path):
    import requests
    source = SDKHistoricalSource(key="fixture-private-not-a-real-key", clock_ns=lambda: NOW_NS)
    calls = []
    class Response:
        status_code, headers = 200, {}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def iter_content(self, chunk_size):
            yield b"x"*2048
    def post(*args, **kwargs):
        calls.append(kwargs)
        return Response()
    monkeypatch.setattr(requests, "post", post)
    req = request(wire_byte_limit=1024)
    with pytest.raises(RuntimeError) as error:
        source.download(req, tmp_path/"bounded.part", preflight=preflight(req), approval=approval(req))
    assert len(calls) == 1 and calls[0]["allow_redirects"] is False
    assert "fixture-private" not in str(error.value)
    assert (tmp_path/"bounded.part").stat().st_size == 0


def test_sdk_billable_boundary_requires_approval_even_without_service(monkeypatch, tmp_path):
    import requests
    source = SDKHistoricalSource(key="fixture-private-not-a-real-key", clock_ns=lambda: NOW_NS)
    def forbidden(*args, **kwargs):
        raise AssertionError("unapproved network request")
    monkeypatch.setattr(requests, "post", forbidden)
    with pytest.raises(ValueError, match="approved request"):
        source.download(request(), tmp_path/"never-created")
    with pytest.raises(ValueError, match="expired"):
        source.download(request(), tmp_path/"never-created", preflight=preflight(),
                        approval=approval(expires_at_ns=NOW_NS))
    assert not (tmp_path/"never-created").exists()


def test_metadata_mapping_uses_exact_contract_and_leaves_entitlements_unknown():
    source = object.__new__(SDKHistoricalSource)
    metadata = SimpleNamespace(list_schemas=lambda dataset: ["trades"],
        get_dataset_range=lambda dataset: {"schema": {"trades": {"start": "2026-10-01", "end": "2026-10-12"}}},
        list_publishers=lambda: [dict(publisher_id=1, dataset="GLBX.MDP3", venue="GLBX")],
        get_cost=lambda **kwargs: 1.97)
    intervals = dict(result={"GCZ6": [dict(d0="2026-10-10", d1="2026-10-11", s="41271")]}, partial=[], not_found=[])
    source._client = SimpleNamespace(metadata=metadata,
        symbology=SimpleNamespace(resolve=lambda **kwargs: intervals))
    p = source.preflight(request(), now_ns=NOW_NS)
    assert p.identities_verified and p.entitlement == "UNKNOWN"
    intervals["result"]["GCZ6"][0]["s"] = "999"
    assert not source.preflight(request(), now_ns=NOW_NS).identities_verified


def test_explicit_retry_requires_new_approval_and_retains_history(tmp_path):
    svc = service(tmp_path, FixtureSource([trade()], fail=True))
    with pytest.raises(RuntimeError):
        acquired(svc)
    svc.source.fail = False
    now = NOW_NS+181*10**9
    svc.clock_ns = lambda: now
    p = preflight(observed_at_ns=now-1000)
    receipt = approval(pre=p, approval_id="review-2", approved_at_ns=now-500,
        expires_at_ns=now+1000, credit_checked_at_ns=now-1000)
    result = asyncio.run(svc.retry(request(), p, receipt, previous_billed_usd="0.5",
                                  billing_review_reference="fixture-final-usage-and-stopped-process"))
    assert result["status"] == "ARCHIVED" and result["download_attempts"] == 2
    assert svc.source.calls == 2 and result["previous_billed_usd"] == "0.5"
    history = asyncio.run(svc.metadata.get("history:"+request().sha256+":2"))
    assert history.value["status"] == "QUARANTINED" and history.value["quarantine_sha256"]


def test_status_statistics_definition_and_native_candle_preserve_distinct_semantics():
    replay = HistoricalGCReplay(reference=reference(), config=config(), publishers=policy().mapping)
    stat = dbn.StatMsg(publisher_id=1, instrument_id=41271, ts_event=START+100,
        ts_recv=START+101, ts_ref=START-100, price=(1<<63)-1, quantity=123,
        stat_type=dbn.StatType.OPEN_INTEREST, sequence=1, update_action=dbn.StatUpdateAction.NEW)
    o = observation(stat, request(schema="statistics"))
    assert o.payload[1] == START-100 and replay.consume(o)
    assert replay.total_volume == 0 and len(replay.statistics) == 1
    status = dbn.StatusMsg(publisher_id=1, instrument_id=41271, ts_event=START+102,
        ts_recv=START+103)
    assert replay.consume(observation(status, request(schema="status"), ordinal=1))
    assert replay.result()["market_status"] is not None and replay.coverage_state == "PARTIAL"
    changed = future(ts_event=START+105, ts_recv=START+106)
    assert not replay.consume(observation(changed, request(schema="definition"), ordinal=2))
    assert "contract_definition_revision_requires_new_reference" in replay.gaps


@pytest.mark.parametrize("change", ["header", "identity", "schema", "order"])
def test_archive_contract_schema_header_and_order_are_verified(tmp_path, change):
    req = request()
    records = [trade()]
    header_req = req
    if change == "header":
        header_req = replace(req, end_ns=END+1)
    elif change == "identity":
        records = [trade(instrument_id=999)]
    elif change == "schema":
        records = [dbn.StatusMsg(publisher_id=1, instrument_id=41271, ts_event=START+100, ts_recv=START+101)]
    else:
        records = [trade(offset=101), trade()]
    path = tmp_path/"bad.dbn"
    write_dbn(path, header_req, records)
    with pytest.raises(ValueError):
        inspect_request_archive(path, req)


def test_research_has_no_runtime_publication_execution_or_network_on_import(monkeypatch):
    import ast
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError("network not authorized")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    root = Path(__file__).parents[2]/"monatise"
    forbidden_prefixes = ("monatise.application.telegram", "monatise.application.execution", "monatise.adapters.ftmo")
    for file in (root/"research/databento").glob("*.py"):
        for node in ast.walk(ast.parse(file.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(forbidden_prefixes)
    for folder in ("application", "engines", "adapters"):
        for file in (root/folder).rglob("*.py"):
            assert "monatise.research.databento" not in file.read_text()
    replay = HistoricalGCReplay(reference=reference(), config=config(), publishers=policy().mapping)
    assert not replay.snapshot(now=reference().contract.available_at)["direction"]
