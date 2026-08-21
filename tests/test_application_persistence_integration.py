from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest

from monatise.application.registry import PRODUCTION_ENGINE_ORDER

from monatise.application.deployment import OrchestrationRuntime, RedisCoordinationStore
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


@pytest.mark.skipif(not os.getenv("MONATISE_TEST_REDIS_URL"), reason="MONATISE_TEST_REDIS_URL is not configured")
def test_telegram_queue_leases_retries_and_dead_letters_against_real_service():
    async def scenario():
        from redis.asyncio import Redis

        namespace = f"monatise:test:telegram:{uuid4()}"
        client = Redis.from_url(os.environ["MONATISE_TEST_REDIS_URL"], decode_responses=True)
        store = RedisCoordinationStore(client, namespace=namespace)
        try:
            assert await store.enqueue_telegram_command(1, {"update_id": 1, "text": "/help"}) is True
            leased = await store.dequeue_telegram_command(timeout_seconds=0)
            assert leased["update_id"] == 1
            assert await store.recover_telegram_commands(lease_seconds=120) == 0
            assert await store.recover_telegram_commands(lease_seconds=0) == 1

            leased = await store.dequeue_telegram_command(timeout_seconds=0)
            assert await store.retry_telegram_command(leased, max_attempts=2) is True
            metrics = await store.telegram_queue_metrics()
            assert metrics["redis"] == "connected"
            assert metrics["pending_depth"] == 1
            assert metrics["active_lease_count"] == 0
            assert metrics["retry_count"] == 1
            assert metrics["oldest_queued_age_seconds"] is not None
            leased = await store.dequeue_telegram_command(timeout_seconds=0)
            assert await store.retry_telegram_command(leased, max_attempts=2) is False
            assert await client.llen(store.key("telegram-command", "pending")) == 0
            assert await client.llen(store.key("telegram-command", "processing")) == 0
            assert await client.llen(store.key("telegram-command", "dead-letter")) == 1
            metrics = await store.telegram_queue_metrics()
            assert metrics["dead_letter_count"] == 1
            assert metrics["retry_count"] == 2
        finally:
            keys = await client.keys(f"{namespace}:*")
            if keys:
                await client.delete(*keys)
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
            "MONATISE_STOCK_SCAN_ENABLED": "false",
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
