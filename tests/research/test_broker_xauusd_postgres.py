"""Durability proof in a private temporary PostgreSQL cluster, no production DSN."""
import asyncio
from datetime import timedelta
from pathlib import Path

import pytest

from monatise.application.persistence import PostgresDocumentStore
from monatise.research.broker_xauusd.archive import BrokerObservationArchive, TABLE
from monatise.research.broker_xauusd.models import BrokerIdentity
from tests.research.test_broker_xauusd_archive import NOW, add, archive, manifest, payload, prepared
from tests.research.test_databento_history_postgres import private_postgres


async def connection(parameters):
    import psycopg
    from psycopg.rows import dict_row
    c = await psycopg.AsyncConnection.connect(**parameters, autocommit=True, row_factory=dict_row)
    sql = Path(__file__).parents[2]/"monatise/research/broker_xauusd/schema.sql"
    await c.execute(sql.read_text())
    return c


def isolated(c, label, clock):
    m = manifest()
    m["account_id"] = label
    a = BrokerObservationArchive(PostgresDocumentStore(c, table=TABLE),
        identity=BrokerIdentity("SYNTHETIC", label, "SYNTHETIC_NOT_BROKER", "XAUUSD"),
        calendar_manifest=m, clock=lambda: clock[0])
    a.fixture_clock = clock
    return a


def test_durable_restart_concurrent_import_and_database_append_guards(private_postgres):
    async def run():
        async with await connection(private_postgres) as c:
            clock = [NOW]
            a = isolated(c, "durable-fixture", clock)
            p = payload(a, at=NOW-timedelta(seconds=10))
            receipts = await asyncio.gather(add(a, p), add(a, p))
            assert receipts[0] == receipts[1]
            assert len(await a.batches(cutoff=NOW)) == 1
            await add(a, payload(a, request_id="second"))
            before = await prepared(a)
            for statement in (
                f"UPDATE {TABLE} SET value='{{}}'::jsonb WHERE namespace=%s",
                f"DELETE FROM {TABLE} WHERE namespace=%s",
            ):
                with pytest.raises(Exception, match="append-only"):
                    await c.execute(statement, (a.namespace,))
            with pytest.raises(Exception, match="append-only"):
                await c.execute(f"TRUNCATE {TABLE}")
            # Default mutable PG store cannot overwrite this research table either.
            doc = (await a.store.list_namespace(a.namespace))[0]
            with pytest.raises(Exception, match="append-only"):
                await a.store.put(a.namespace, doc.key.decode() if isinstance(doc.key, bytes) else doc.key, {"tampered": True})
        async with await connection(private_postgres) as reopened:
            restored = isolated(reopened, "durable-fixture", clock)
            assert await prepared(restored) == before
            assert all(x["latest_expected_finalized"] for x in before["coverage"].values())
    asyncio.run(run())


def test_historical_download_and_capture_proof_remain_separate_on_real_postgres(private_postgres):
    async def run():
        async with await connection(private_postgres) as c:
            a = isolated(c, "historical-fixture", [NOW])
            await add(a, payload(a, at=NOW-timedelta(seconds=10)), kind="RETROSPECTIVE_HISTORICAL_DOWNLOAD")
            await add(a, payload(a, request_id="historical-second"), kind="RETROSPECTIVE_HISTORICAL_DOWNLOAD")
            historical = await prepared(a, kind="RETROSPECTIVE_HISTORICAL_DOWNLOAD")
            assert "HISTORICAL_AVAILABILITY_NOT_OBSERVED" in historical["blockers"]
            assert not (await prepared(a))["batch_ids"]
            # Historical fixture data has never been relabelled as market evidence.
            assert {b["evidence_kind"] for b in await a.batches(cutoff=NOW)} == {"RETROSPECTIVE_HISTORICAL_DOWNLOAD"}
    asyncio.run(run())


def test_research_schema_never_changes_existing_application_tables(private_postgres):
    async def run():
        async with await connection(private_postgres) as c:
            migration = Path(__file__).parents[2]/"deploy/migrations/001_application_orchestration.sql"
            await c.execute(migration.read_text())
            ordinary = PostgresDocumentStore(c)
            first = await ordinary.put("phase3-isolation", "key", {"v": 1}, expected_version=0)
            second = await ordinary.put("phase3-isolation", "key", {"v": 2}, expected_version=first.version)
            assert second.version == 2
            await ordinary.delete("phase3-isolation", "key")
            assert await ordinary.get("phase3-isolation", "key") is None
    asyncio.run(run())
