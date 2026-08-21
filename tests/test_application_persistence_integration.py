from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from monatise.application.registry import PRODUCTION_ENGINE_ORDER

from monatise.application.deployment import OrchestrationRuntime, RedisCoordinationStore, TelegramCommandTransition
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
            assert await store.recover_telegram_commands() == 0
            assert await store.renew_telegram_command(leased, lease_seconds=120) is True
            await client.zadd(store.key("telegram-command", "leases-v2"), {leased["__monatise_lease_token"]: 0})
            assert await store.recover_telegram_commands() == 1
            assert await store.finish_telegram_command(leased) is False
            assert await store.retry_telegram_command(leased, max_attempts=2) is TelegramCommandTransition.OWNERSHIP_LOST
            assert await client.llen(store.key("telegram-command", "pending")) == 1

            leased = await store.dequeue_telegram_command(timeout_seconds=0)
            assert await store.retry_telegram_command(leased, max_attempts=2) is TelegramCommandTransition.REQUEUED
            metrics = await store.telegram_queue_metrics()
            assert metrics["redis"] == "connected"
            assert metrics["pending_depth"] == 1
            assert metrics["active_lease_count"] == 0
            assert metrics["retry_count"] == 1
            assert metrics["oldest_queued_age_seconds"] is not None
            leased = await store.dequeue_telegram_command(timeout_seconds=0)
            assert await store.retry_telegram_command(leased, max_attempts=2) is TelegramCommandTransition.DEAD_LETTERED
            assert await client.llen(store.key("telegram-command", "pending")) == 0
            assert await client.hlen(store.key("telegram-command", "processing-v2")) == 0
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


@pytest.mark.skipif(not os.getenv("MONATISE_TEST_REDIS_URL"), reason="MONATISE_TEST_REDIS_URL is not configured")
def test_telegram_queue_uses_redis_clock_and_quarantines_malformed_leases(monkeypatch):
    async def scenario():
        from redis.asyncio import Redis
        import monatise.application.deployment as deployment_module

        namespace = f"monatise:test:telegram:fencing:{uuid4()}"
        client = Redis.from_url(os.environ["MONATISE_TEST_REDIS_URL"], decode_responses=True)
        store = RedisCoordinationStore(client, namespace=namespace)
        try:
            monkeypatch.setattr(deployment_module, "time", lambda: 9_999_999_999.0)
            await store.enqueue_telegram_command(10, {"update_id": 10, "text": "/help"})
            leased = await store.dequeue_telegram_command(timeout_seconds=0, lease_seconds=120)
            redis_seconds, redis_microseconds = await client.time()
            redis_now = redis_seconds + redis_microseconds / 1_000_000
            expiry = await client.zscore(store.key("telegram-command", "leases-v2"), leased["__monatise_lease_token"])
            assert 119 <= expiry - redis_now <= 120

            assert await store.release_telegram_command(leased) is TelegramCommandTransition.REQUEUED
            for _ in range(3):
                leased = await store.dequeue_telegram_command(timeout_seconds=0)
                assert await store.release_telegram_command(leased) is TelegramCommandTransition.REQUEUED
            raw = json.loads(await client.lindex(store.key("telegram-command", "pending"), -1))
            assert raw.get("attempts", 0) == 0

            valid = await store.dequeue_telegram_command(timeout_seconds=0)
            await store.enqueue_telegram_command(11, {"update_id": 11, "text": "/help"})
            malformed = await store.dequeue_telegram_command(timeout_seconds=0)
            malformed_token = malformed["__monatise_lease_token"]
            await client.hset(store.key("telegram-command", "processing-v2"), malformed_token, "not-json")
            await client.zadd(store.key("telegram-command", "leases-v2"), {
                valid["__monatise_lease_token"]: 0,
                malformed_token: 0,
            })

            assert await store.recover_telegram_commands() == 1
            quarantined = json.loads(await client.lindex(store.key("telegram-command", "dead-letter"), 0))
            assert quarantined["reason"] == "malformed_lease_envelope"
            assert await store.retry_telegram_command(valid) is TelegramCommandTransition.OWNERSHIP_LOST
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
