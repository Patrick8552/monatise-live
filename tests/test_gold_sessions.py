"""Synthetic reviewed schedules; no claim these are an FTMO calendar."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from monatise.application.gold_sessions import GoldSessionCalendar


def manifest():
    return {
        "schema": "gold-broker-sessions-v1",
        "account_id": "synthetic",
        "server": "synthetic",
        "symbol": "XAU/USD",
        "source": "synthetic reference schedule",
        "version": "test-v1",
        "valid_from": "2026-10-20T00:00:00Z",
        "valid_until": "2026-11-03T00:00:00Z",
        "offsets": [
            {
                "from": "2026-10-20T00:00:00Z",
                "until": "2026-10-25T01:00:00Z",
                "seconds": 10800,
            },
            {
                "from": "2026-10-25T01:00:00Z",
                "until": "2026-11-03T00:00:00Z",
                "seconds": 7200,
            },
        ],
        # Holiday on Oct 27; maintenance break at 21:00-22:00 Oct 26.
        "sessions": [
            {"open": "2026-10-23T00:00:00Z", "close": "2026-10-23T21:00:00Z"},
            {"open": "2026-10-26T00:00:00Z", "close": "2026-10-26T21:00:00Z"},
            {"open": "2026-10-26T22:00:00Z", "close": "2026-10-27T00:00:00Z"},
            {"open": "2026-10-28T00:00:00Z", "close": "2026-10-28T21:00:00Z"},
        ],
    }


def t(value):
    return datetime.fromisoformat(value)


def test_historical_offsets_use_the_era_not_the_current_offset():
    c = GoldSessionCalendar.from_manifest(manifest())
    before = t("2026-10-23T12:00:00Z")
    after = t("2026-10-26T12:00:00Z")
    assert c.normalize_broker_epoch(int(before.timestamp()) + 10800) == before
    assert c.normalize_broker_epoch(int(after.timestamp()) + 7200) == after
    assert c.fingerprint == GoldSessionCalendar.from_manifest(manifest()).fingerprint


def test_dst_repeated_broker_hour_is_rejected_instead_of_guessed():
    c = GoldSessionCalendar.from_manifest(manifest())
    wall = int(t("2026-10-25T03:30:00Z").timestamp())
    with pytest.raises(ValueError, match="ambiguous"):
        c.normalize_broker_epoch(wall)


def test_spring_forward_nonexistent_hour_rejected():
    m = manifest()
    m["offsets"][0]["seconds"] = 7200
    m["offsets"][1]["seconds"] = 10800
    c = GoldSessionCalendar.from_manifest(m)
    with pytest.raises(ValueError, match="ambiguous or outside"):
        c.normalize_broker_epoch(int(t("2026-10-25T03:30:00Z").timestamp()))


def test_expected_closed_candle_respects_weekend_holiday_break_and_grace():
    c = GoldSessionCalendar.from_manifest(manifest())
    assert c.expected_closed_open("15m", t("2026-10-24T12:00:00Z")) == t(
        "2026-10-23T20:45:00Z"
    )
    assert c.expected_closed_open("15m", t("2026-10-27T12:00:00Z")) == t(
        "2026-10-26T23:45:00Z"
    )
    assert c.expected_closed_open("15m", t("2026-10-26T21:30:00Z")) == t(
        "2026-10-26T20:45:00Z"
    )
    assert c.expected_closed_open("15m", t("2026-10-26T12:00:05Z")) == t(
        "2026-10-26T11:30:00Z"
    )
    assert c.expected_closed_open("15m", t("2026-10-26T12:00:20Z")) == t(
        "2026-10-26T11:45:00Z"
    )
    assert not c.regular_bar(t("2026-10-26T20:00:00Z"), "4h")
    assert c.regular_bar(t("2026-10-26T10:00:00Z"), "4h")  # broker noon
    with pytest.raises(ValueError, match="closed_or_break"):
        c.require_regular_session(t("2026-10-27T12:00:00Z"))


@pytest.mark.parametrize(
    "change", ["identity", "hole", "overlap", "session", "source", "boolean", "naive"]
)
def test_invalid_manifests_never_certify(change):
    m = deepcopy(manifest())
    if change == "identity":
        m["symbol"] = "XAU/EUR"
    elif change == "hole":
        m["offsets"][1]["from"] = "2026-10-25T02:00:00Z"
    elif change == "overlap":
        m["offsets"][1]["from"] = "2026-10-25T00:00:00Z"
    elif change == "session":
        m["sessions"][1]["close"] = "2026-10-29T21:00:00Z"
    elif change == "source":
        m["source"] = ""
    elif change == "boolean":
        m["offsets"][1]["seconds"] = True
    else:
        m["valid_from"] = "2026-10-20T00:00:00"
    with pytest.raises(ValueError):
        GoldSessionCalendar.from_manifest(m)


def test_identity_and_expired_schedule_fail_closed():
    c = GoldSessionCalendar.from_manifest(manifest())
    with pytest.raises(ValueError, match="identity"):
        c.require_identity("other", "synthetic", "XAU/USD")
    with pytest.raises(ValueError, match="coverage"):
        c.offset(c.end)
    with pytest.raises(ValueError, match="raw broker"):
        c.normalize_broker_epoch(True)


def test_authenticated_transport_normalizes_raw_times_and_binds_calendar():
    import asyncio
    from types import SimpleNamespace

    from monatise.application.hierarchy.broker_candles import (
        DEMANDS,
        BrokerCandleService,
    )
    from tests.test_application_hierarchy import MemoryStore
    from tests.test_gold_technical_first import NOW, SECONDS, synthetic_candles

    async def scenario():
        store = MemoryStore()
        start = NOW.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=20
        )
        end = start + timedelta(days=30)
        m = manifest()
        m.update(
            account_id="synthetic-account",
            server="synthetic-server",
            valid_from=start.isoformat(),
            valid_until=end.isoformat(),
            offsets=[
                {"from": start.isoformat(), "until": end.isoformat(), "seconds": 0}
            ],
            sessions=[
                {
                    "open": (start + timedelta(days=i)).isoformat(),
                    "close": (start + timedelta(days=i + 1)).isoformat(),
                }
                for i in range(30)
            ],
        )
        calendar = GoldSessionCalendar.from_manifest(m)

        class Master:
            repository = SimpleNamespace(store=store)
            configuration = SimpleNamespace(
                account_id="synthetic-account", server="synthetic-server"
            )
            gold_history_calendar = calendar
            _symbol_key = staticmethod(lambda x: x.replace("/", "").upper())

            async def _healthy_bridge(self, now):
                return {"history_version": 3}

        service = BrokerCandleService(Master())
        await store.put(
            DEMANDS,
            "nonce",
            {
                "state": "pending",
                "symbol": "XAU/USD",
                "limit": 200,
                "gold": True,
                "account_id": "synthetic-account",
                "server": "synthetic-server",
                "expires_at": (NOW + timedelta(seconds=30)).isoformat(),
            },
            expected_version=0,
        )
        payload = {
            "request_id": "nonce",
            "account_id": "synthetic-account",
            "server": "synthetic-server",
            "symbol": "XAUUSD",
            "captured_at": NOW.isoformat(),
            "broker_time_offset": 0,
            "session_open": True,
            "session_close": calendar.session_close(NOW).isoformat(),
            "point": 0.01,
            "tick_size": 0.01,
            "spread_price": 0.2,
            "timestamp_policy": "current_offset_uncertified_history",
            "timeframes": {
                tf: [
                    {
                        "t": (
                            datetime.fromisoformat(c.timestamp) + timedelta(hours=2)
                        ).isoformat(),
                        "t_broker": int(
                            datetime.fromisoformat(c.timestamp).timestamp()
                        ),
                        "o": c.open,
                        "h": c.high,
                        "l": c.low,
                        "c": c.close,
                        "v": c.volume,
                    }
                    for c in synthetic_candles(tf)
                ]
                for tf in SECONDS
            },
        }
        for change in [
            {"broker_time_offset": 3600},
            {"session_close": (NOW + timedelta(hours=1)).isoformat()},
            {"session_open": False},
        ]:
            with pytest.raises(ValueError):
                await service.accept({**payload, **change}, now=NOW)
        missing = deepcopy(payload)
        missing["timeframes"]["1m"][0].pop("t_broker")
        with pytest.raises(ValueError, match="raw broker"):
            await service.accept(missing, now=NOW)
        await service.accept(payload, now=NOW)
        response = (await store.get(DEMANDS, "nonce")).value["response"]
        assert (
            response["timeframes"]["4h"][0]["t"] == synthetic_candles("4h")[0].timestamp
        )
        assert response["calendar_fingerprint"] == calendar.fingerprint
        assert response["timestamp_policy"] == "reviewed_broker_schedule_v1"

    asyncio.run(scenario())
