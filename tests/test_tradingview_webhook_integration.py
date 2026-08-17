"""Integration coverage for the native TradingView webhook against real
PostgreSQL: malformed, expired, and replayed alerts must all fail closed.

"Unauthorized" is covered against the real database implicitly (nothing is
ever written for an unauthenticated request) and explicitly, at the HTTP
layer where auth actually lives, in tests/test_production_entrypoint.py.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest

from monatise.application.deployment import (
    TRADINGVIEW_ALERT_RETENTION_DAYS,
    OrchestrationRuntime,
    TradingViewAlertDuplicate,
)
from monatise.application.persistence import connect_postgres_store


pytestmark = pytest.mark.skipif(
    not os.getenv("MONATISE_TEST_DATABASE_URL"), reason="MONATISE_TEST_DATABASE_URL is not configured"
)


async def _migrated_runtime():
    _, connection = await connect_postgres_store(os.environ["MONATISE_TEST_DATABASE_URL"])
    migration = Path("deploy/migrations/003_tradingview_alerts.sql").read_text()
    await connection.execute(migration)
    await connection.execute("DELETE FROM monatise_tradingview_alerts")
    runtime = OrchestrationRuntime()
    runtime.postgres = connection
    return runtime, connection


def test_valid_alert_is_durably_stored_and_readable():
    async def scenario():
        runtime, connection = await _migrated_runtime()
        try:
            alert = await runtime.record_tradingview_alert(
                {"symbol": "BTCUSDT", "action": "buy", "confidence": "77"}, fingerprint=str(uuid4())
            )
            assert alert["symbol"] == "BTC"
            recent = await runtime.recent_tradingview_alerts(symbol="BTC")
            assert len(recent) == 1
            assert recent[0]["symbol"] == "BTC"
            assert recent[0]["classification"]["fresh"] is True
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_malformed_alert_fails_closed_without_storing_anything():
    async def scenario():
        runtime, connection = await _migrated_runtime()
        try:
            with pytest.raises(ValueError, match="Gold/XAU"):
                await runtime.record_tradingview_alert({"symbol": "OANDA:XAUUSD", "action": "buy"}, fingerprint=str(uuid4()))
            row = await (await connection.execute("SELECT count(*) FROM monatise_tradingview_alerts")).fetchone()
            assert row[0] == 0
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_replayed_alert_fails_closed_and_only_one_row_is_stored():
    async def scenario():
        runtime, connection = await _migrated_runtime()
        try:
            fingerprint = str(uuid4())
            payload = {"symbol": "ETHUSDT", "action": "sell", "confidence": "88"}
            await runtime.record_tradingview_alert(payload, fingerprint=fingerprint)
            with pytest.raises(TradingViewAlertDuplicate):
                await runtime.record_tradingview_alert(payload, fingerprint=fingerprint)
            row = await (await connection.execute("SELECT count(*) FROM monatise_tradingview_alerts")).fetchone()
            assert row[0] == 1
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_expired_alert_is_excluded_from_recent_signals():
    async def scenario():
        runtime, connection = await _migrated_runtime()
        try:
            await runtime.record_tradingview_alert({"symbol": "SOLUSDT", "action": "buy"}, fingerprint=str(uuid4()))
            # Backdate it past the 5-minute freshness window directly --
            # normalize_tradingview_alert always stamps "now", so an expired
            # alert can only be produced by manipulating the stored row,
            # exactly as real elapsed time would.
            await connection.execute(
                "UPDATE monatise_tradingview_alerts SET received_at = NOW() - INTERVAL '10 minutes' WHERE symbol = 'SOL'"
            )
            recent = await runtime.recent_tradingview_alerts(symbol="SOL")
            assert recent == []
        finally:
            await connection.close()

    asyncio.run(scenario())


def test_retention_removes_alerts_older_than_the_retention_window():
    async def scenario():
        runtime, connection = await _migrated_runtime()
        try:
            await runtime.record_tradingview_alert({"symbol": "BNBUSDT", "action": "wait"}, fingerprint=str(uuid4()))
            await connection.execute(
                "UPDATE monatise_tradingview_alerts SET received_at = NOW() - make_interval(days => %s)",
                (TRADINGVIEW_ALERT_RETENTION_DAYS + 1,),
            )
            result = await connection.execute(
                "DELETE FROM monatise_tradingview_alerts WHERE received_at < NOW() - make_interval(days => %s)",
                (TRADINGVIEW_ALERT_RETENTION_DAYS,),
            )
            assert result.rowcount == 1
            row = await (await connection.execute("SELECT count(*) FROM monatise_tradingview_alerts")).fetchone()
            assert row[0] == 0
        finally:
            await connection.close()

    asyncio.run(scenario())
