from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest

from monatise.application.registry import PRODUCTION_ENGINE_ORDER

from monatise.application.deployment import OrchestrationRuntime
from monatise.application.persistence import PostgresDocumentStore, RedisDocumentStore, connect_postgres_store, connect_redis_store


@pytest.mark.skipif(not os.getenv("MONATISE_TEST_DATABASE_URL"), reason="MONATISE_TEST_DATABASE_URL is not configured")
def test_postgres_document_contract_against_real_service():
    async def scenario():
        store, connection = await connect_postgres_store(os.environ["MONATISE_TEST_DATABASE_URL"])
        try:
            migration = Path("deploy/migrations/001_application_orchestration.sql").read_text()
            await connection.execute(migration)
            namespace, key = f"contract-{uuid4()}", "state"
            first = await store.put(namespace, key, {"value": 1})
            second = await store.put(namespace, key, {"value": 2}, expected_version=first.version)
            assert second.version == 2
            assert (await store.get(namespace, key)).value == {"value": 2}
            await store.delete(namespace, key)
            assert await store.get(namespace, key) is None
        finally:
            await connection.close()
    asyncio.run(scenario())


@pytest.mark.skipif(not os.getenv("MONATISE_TEST_REDIS_URL"), reason="MONATISE_TEST_REDIS_URL is not configured")
def test_redis_document_contract_against_real_service():
    async def scenario():
        prefix = f"monatise-test-{uuid4()}"
        store, client = connect_redis_store(os.environ["MONATISE_TEST_REDIS_URL"], prefix=prefix)
        try:
            first = await store.put("state", "one", {"value": 1}, ttl_seconds=30)
            second = await store.put("state", "one", {"value": 2}, ttl_seconds=30)
            assert (first.version, second.version) == (1, 2)
            assert (await store.get("state", "one")).value == {"value": 2}
            await store.append("events", {"sequence": 1})
            assert await store.read_stream("events") == ({"sequence": 1},)
            await store.delete("state", "one")
        finally:
            await client.aclose()
    asyncio.run(scenario())


@pytest.mark.skipif(
    not os.getenv("MONATISE_TEST_DATABASE_URL") or not os.getenv("MONATISE_TEST_REDIS_URL"),
    reason="PostgreSQL and Redis test URLs are not configured",
)
def test_orchestration_runtime_service_backed_startup_and_shutdown():
    async def scenario():
        runtime = OrchestrationRuntime(environment={
            "MONATISE_ENVIRONMENT": "test",
            "MONATISE_MODE": "paper",
            "MONATISE_NETWORK": "paper",
            "MONATISE_DATABASE_URL": os.environ["MONATISE_TEST_DATABASE_URL"],
            "MONATISE_REDIS_URL": os.environ["MONATISE_TEST_REDIS_URL"],
            "MONATISE_REDIS_NAMESPACE": f"monatise:test:runtime:{uuid4()}",
            "MONATISE_COIN_DISCOVERY_ENABLED": "false",
        })
        await runtime.start()
        try:
            ready, payload = runtime.readiness()
            assert ready is True
            assert payload["execution_enabled"] is False
            assert payload["dependencies"]["engine_registry"]["count"] == len(PRODUCTION_ENGINE_ORDER)
            assert payload["dependencies"]["engine_registry"]["order"] == list(PRODUCTION_ENGINE_ORDER)
            assert "risk_validation" not in payload["dependencies"]["engine_registry"]["order"]
            assert payload["dependencies"]["scheduler"]["leader"] is True
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
