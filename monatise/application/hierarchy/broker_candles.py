"""Authenticated, read-only candle requests through the existing MT5 bridge.

This transport cannot create commands or orders. Responses are bound to a
short-lived request and the configured account, server, instrument and policy.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from monatise.application.hierarchy.policy import (
    SHARED_TIMEFRAME_POLICY,
    INTERVAL_SECONDS,
)
from monatise.core.models import Candle

DEMANDS = "hierarchy_candle_requests_v1"


def is_index(instrument: Any) -> bool:
    return (
        instrument is not None
        and instrument.asset_class.value == "futures_linked_cfd"
        and "Index" in instrument.display_name
    )


class BrokerCandleService:
    def __init__(self, master: Any) -> None:
        self.master = master
        self.store = master.repository.store

    async def fetch(self, instrument: Any, limit: int = 200) -> dict[str, Any]:
        if not is_index(instrument):
            raise ValueError("broker hierarchy candles require a verified index")
        bridge = await self.master._healthy_bridge(None)
        if bridge.get("history_version") != 1:
            raise ValueError(
                "index_candles_unavailable: MT5 EA 1.19 history capability required"
            )
        now = datetime.now(timezone.utc)
        request_id = secrets.token_hex(16)
        await self.store.put(
            DEMANDS,
            request_id,
            {
                "request_id": request_id,
                "symbol": instrument.ftmo_symbol,
                "limit": min(240, max(50, limit)),
                "state": "pending",
                "account_id": self.master.configuration.account_id,
                "server": self.master.configuration.server,
                "requested_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=45)).isoformat(),
            },
            expected_version=0,
        )
        try:
            async with asyncio.timeout(20):
                while True:
                    record = await self.store.get(DEMANDS, request_id)
                    if record and record.value.get("state") == "received":
                        return record.value["response"]
                    await asyncio.sleep(0.25)
        except TimeoutError as exc:
            raise ValueError(
                "index_candles_unavailable: MT5 history response timed out"
            ) from exc

    async def next_request(self, now: datetime | None = None) -> str:
        observed = now or datetime.now(timezone.utc)
        records = await self.store.list_namespace(DEMANDS)
        pending = []
        for record in records:
            value = record.value
            expiry = datetime.fromisoformat(value["expires_at"])
            if expiry < observed - timedelta(minutes=5):
                await self.store.delete(DEMANDS, record.key)
            elif expiry > observed and value["state"] == "pending":
                pending.append(value)
        if not pending:
            return ""
        value = min(pending, key=lambda row: row["requested_at"])
        return f"{value['request_id']}|{value['symbol']}|{value['limit']}|{','.join(SHARED_TIMEFRAME_POLICY.timeframes)}"

    async def accept(
        self, payload: Mapping[str, Any], now: datetime | None = None
    ) -> dict[str, Any]:
        observed = now or datetime.now(timezone.utc)
        await self.master._healthy_bridge(observed)
        request_id = str(payload.get("request_id") or "")
        record = await self.store.get(DEMANDS, request_id)
        if not record or record.value.get("state") != "pending":
            raise ValueError("unknown or consumed candle request")
        request = record.value
        if observed >= datetime.fromisoformat(request["expires_at"]):
            raise ValueError("candle request expired")
        if (
            str(payload.get("account_id")) != str(request["account_id"])
            or str(payload.get("server", "")).casefold()
            != str(request["server"]).casefold()
        ):
            raise ValueError("candle response account identity mismatch")
        if self.master._symbol_key(
            str(payload.get("symbol", ""))
        ) != self.master._symbol_key(request["symbol"]):
            raise ValueError("candle response instrument mismatch")
        captured = datetime.fromisoformat(
            str(payload.get("captured_at", "")).replace("Z", "+00:00")
        )
        if (
            captured.tzinfo is None
            or not 0 <= (observed - captured).total_seconds() <= 30
        ):
            raise ValueError("candle response timestamp is stale or in the future")
        series = payload.get("timeframes")
        if not isinstance(series, dict) or set(series) != set(
            SHARED_TIMEFRAME_POLICY.timeframes
        ):
            raise ValueError(
                "candle response must contain the complete shared hierarchy"
            )
        clean = {}
        for timeframe, rows in series.items():
            if not isinstance(rows, list) or not 50 <= len(rows) <= request["limit"]:
                raise ValueError("incomplete candle response")
            previous = None
            clean[timeframe] = []
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("malformed candle")
                if any(
                    isinstance(row.get(key), bool) or row.get(key) is None
                    for key in ("o", "h", "l", "c", "v")
                ):
                    raise ValueError("candle OHLCV is incomplete")
                candle = Candle(
                    str(row["t"]),
                    *(float(row[key]) for key in ("o", "h", "l", "c", "v")),
                )
                candle.validate()
                opened = datetime.fromisoformat(candle.timestamp.replace("Z", "+00:00"))
                if (
                    opened.tzinfo is None
                    or opened > captured
                    or (previous and opened <= previous)
                ):
                    raise ValueError("candle timestamps are invalid or unordered")
                previous = opened
                clean[timeframe].append(dict(row))
            # All requests contain the forming row too. Freshness of each last
            # closed row is checked again by the analysis service.
            if (captured - previous).total_seconds() > INTERVAL_SECONDS[timeframe] * 2:
                raise ValueError("broker candle series is stale")
        response = {
            "timeframes": clean,
            "captured_at": captured.isoformat(),
            "symbol": str(payload["symbol"]),
            "trade_mode": payload.get("trade_mode"),
            "session_open": payload.get("session_open") is True,
            "session_close": payload.get("session_close"),
            "provider": "ftmo_mt5",
            "request_id": request_id,
            "volume_kind": "tick_volume",
            "broker_time_offset": payload.get("broker_time_offset"),
        }
        await self.store.put(
            DEMANDS,
            request_id,
            {**request, "state": "received", "response": response},
            expected_version=record.version,
        )
        return {"status": "accepted", "execution_enabled": False}
