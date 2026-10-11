"""Real isolated PostgreSQL integration, using an existing local installation.

No production DSN is read. Temporary cluster exposes only a private Unix socket
and is stopped/deleted after the tests. Skip when binaries/dependency are absent.
"""
import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from monatise.application.persistence import PostgresDocumentStore
from monatise.research.databento.acquisition import HistoricalAcquisition, HistoricalMetadata
from monatise.research.databento.archive import NativeDBNArchive
from tests.research.test_databento_history import (
    FixtureSource, NOW_NS, approval, preflight, request, trade,
)


@pytest.fixture(scope="module")
def private_postgres():
    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not initdb or not pg_ctl:
        pytest.skip("existing local PostgreSQL binaries unavailable")
    pytest.importorskip("psycopg")
    # Short path respects the OS Unix-socket path length limit.
    with tempfile.TemporaryDirectory(prefix="mon-history-pg-", dir="/tmp") as root:
        root = Path(root)
        data, socket = root/"cluster", root/"socket"
        socket.mkdir(mode=0o700)
        env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
        log = root/"server.log"
        initialized = subprocess.run([initdb, "-D", str(data), "-A", "trust", "--no-locale", "-U", "history_test"],
            env=env, capture_output=True, text=True)
        if initialized.returncode:
            pytest.fail("isolated PostgreSQL initialization failed")
        subprocess.run([pg_ctl, "-D", str(data), "-l", str(log), "-o",
            f"-F -k {socket} -c listen_addresses='' -p 55487", "-w", "start"],
            env=env, capture_output=True, check=True)
        try:
            yield dict(host=str(socket), port=55487, user="history_test", dbname="postgres")
        finally:
            subprocess.run([pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop"],
                           env=env, capture_output=True, check=True)


async def connection(parameters):
    import psycopg
    from psycopg.rows import dict_row
    c = await psycopg.AsyncConnection.connect(**parameters, autocommit=True, row_factory=dict_row)
    sql = Path(__file__).parents[2]/"deploy/migrations/001_application_orchestration.sql"
    await c.execute(sql.read_text())
    await c.execute("TRUNCATE monatise_application_documents")
    return c


def test_real_postgres_one_use_receipt_manifest_and_concurrent_download(private_postgres, tmp_path):
    async def run():
        async with await connection(private_postgres) as c:
            metadata = HistoricalMetadata(PostgresDocumentStore(c))
            source = FixtureSource([trade()])
            svc = HistoricalAcquisition(metadata=metadata, archive=NativeDBNArchive(tmp_path),
                                        source=source, clock_ns=lambda: NOW_NS)
            results = await asyncio.gather(svc.acquire(request(), preflight(), approval()),
                svc.acquire(request(), preflight(), approval()), return_exceptions=True)
            assert len([result for result in results if isinstance(result, dict)]) == 1
            assert source.calls == 1
            manifest = await metadata.get("request:"+request().sha256)
            receipt = await metadata.get("approval:review-1")
            assert manifest.value["status"] == "ARCHIVED" and manifest.version == 2
            assert receipt.version == 1 and manifest.value["availability_ns"] == NOW_NS
            assert await svc.acquire(request(), preflight(), approval()) == manifest.value
            assert source.calls == 1
    asyncio.run(run())


def test_real_postgres_checkpoint_roundtrip_and_cas_conflict(private_postgres):
    async def run():
        async with await connection(private_postgres) as c:
            metadata = HistoricalMetadata(PostgresDocumentStore(c))
            checkpoint = dict(config_sha256="a"*64, archive_sha256="b"*64, record_ordinal=7,
                              clocks=dict(event_ns=NOW_NS+111, receive_ns=None), profile=[[2500, 3]])
            first = await metadata.checkpoint("r1", checkpoint)
            assert (await metadata.get("checkpoint:r1")).value == checkpoint
            second = await metadata.checkpoint("r1", {**checkpoint, "record_ordinal": 8})
            assert second.version == 2
            with pytest.raises(RuntimeError, match="conflict"):
                await metadata.replace(first, checkpoint)
            with pytest.raises(ValueError, match="backwards"):
                await metadata.checkpoint("r1", checkpoint)
    asyncio.run(run())


def test_real_postgres_failure_preserves_quarantine_and_retry_is_blocked(private_postgres, tmp_path):
    async def run():
        async with await connection(private_postgres) as c:
            metadata = HistoricalMetadata(PostgresDocumentStore(c))
            source = FixtureSource([trade()], fail=True)
            svc = HistoricalAcquisition(metadata=metadata, archive=NativeDBNArchive(tmp_path),
                                        source=source, clock_ns=lambda: NOW_NS)
            with pytest.raises(RuntimeError, match="quarantined"):
                await svc.acquire(request(), preflight(), approval())
            value = (await metadata.get("request:"+request().sha256)).value
            assert value["status"] == "QUARANTINED" and value["quarantine_sha256"]
            with pytest.raises(ValueError, match="not settled"):
                await svc.retry(request(), preflight(), approval(approval_id="retry-1"),
                                previous_billed_usd="0", billing_review_reference="fixture-reconciliation")
            assert source.calls == 1
    asyncio.run(run())
