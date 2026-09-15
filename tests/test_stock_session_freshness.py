from datetime import date, datetime, timedelta, timezone

import pytest

from monatise.application.hierarchy.assets import _candles
from monatise.application.hierarchy.policy import SHARED_TIMEFRAME_POLICY
from monatise.application.hierarchy.stock_sessions import StockSessionCalendar
from tests.stock_session_fixtures import calendar_rows, stock_rows


def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def calendar():
    return StockSessionCalendar.from_provider(
        calendar_rows("2026-07-01", "2026-09-16", holidays=["2026-09-07"]),
        start=date(2026, 7, 1),
        end=date(2026, 9, 16),
    )


@pytest.mark.parametrize(
    "observed,expected",
    [
        ("2026-09-15T08:00:00Z", "2026-09-14T16:00:00Z"),  # overnight
        ("2026-09-14T13:45:00Z", "2026-09-11T16:00:00Z"),  # weekend
        ("2026-09-08T13:45:00Z", "2026-09-04T16:00:00Z"),  # Labor Day
        ("2026-09-15T13:30:00Z", "2026-09-14T16:00:00Z"),  # opening instant
        ("2026-09-15T15:33:35Z", "2026-09-14T16:00:00Z"),  # SNOW regression
        ("2026-09-15T16:00:09Z", "2026-09-14T16:00:00Z"),  # close grace
        ("2026-09-15T16:00:10Z", "2026-09-15T12:00:00Z"),
    ],
)
def test_four_hour_freshness_uses_expected_session_bar(observed, expected):
    now = utc(observed)
    data = stock_rows("4h", now)
    # The fixture deliberately has a Labor Day row; out-of-session data cannot
    # replace the latest regular-session bar or be passed to the evaluator.
    details = {}
    result = _candles(data, "4h", now, stock_calendar=calendar(), diagnostics=details)
    assert details["expected_closed_open"] == utc(expected).isoformat()
    assert utc(details["latest_closed_open"]) == utc(expected)
    assert [c.timestamp for c in result] == [
        r["t"] for r in data if not r["t"].startswith("2026-09-07")
    ]
    original = {r["t"]: r for r in data}
    assert all(c.close == original[c.timestamp]["c"] for c in result)


@pytest.mark.parametrize("tf", SHARED_TIMEFRAME_POLICY.timeframes)
def test_missing_expected_bar_fails_even_with_a_newer_forming_bar(tf):
    now = utc("2026-09-15T16:01:20Z")
    cal = calendar()
    expected = cal.expected_closed_open(tf, now, grace_seconds=10)
    data = stock_rows(tf, now)
    data = [r for r in data if utc(r["t"]) != expected]
    seconds = {"4h": 14400, "1h": 3600, "15m": 900, "5m": 300, "1m": 60}[tf]
    forming = datetime.fromtimestamp(
        int(now.timestamp()) // seconds * seconds, timezone.utc
    )
    data.append({**data[-1], "t": forming.isoformat()})
    details = {}
    with pytest.raises(ValueError, match=f"{tf}_expected_closed_candle_missing"):
        _candles(data, tf, now, stock_calendar=cal, diagnostics=details)
    assert utc(details["expected_closed_open"]) == expected
    assert utc(details["latest_closed_open"]) < expected


def test_missing_previous_session_close_is_not_hidden_by_extended_hours():
    now = utc("2026-09-15T13:45:00Z")
    data = stock_rows("4h", now)
    data.pop()  # Remove yesterday's 16:00 UTC regular-session bar.
    data.append({**data[-1], "t": "2026-09-14T20:00:00Z"})
    with pytest.raises(ValueError, match="4h_expected_closed_candle_missing"):
        _candles(data, "4h", now, stock_calendar=calendar())


@pytest.mark.parametrize(
    "observed,expected",
    [
        ("2026-03-09T13:45:00Z", "2026-03-06T20:00:00Z"),
        ("2026-11-02T14:45:00Z", "2026-10-30T16:00:00Z"),
        ("2026-11-30T14:45:00Z", "2026-11-27T16:00:00Z"),
        ("2026-11-27T18:00:10Z", "2026-11-27T12:00:00Z"),
        ("2026-11-27T20:00:10Z", "2026-11-27T16:00:00Z"),
    ],
)
def test_dst_and_early_close_preserve_provider_bucket_end(observed, expected):
    rows = [
        {"date": d, "open": "09:30", "close": "13:00" if d == "2026-11-27" else "16:00"}
        for d in [
            "2026-03-06",
            "2026-03-09",
            "2026-10-30",
            "2026-11-02",
            "2026-11-27",
            "2026-11-30",
        ]
    ]
    cal = StockSessionCalendar.from_provider(
        rows, start=date(2026, 3, 1), end=date(2026, 11, 30)
    )
    assert cal.expected_closed_open("4h", utc(observed), grace_seconds=10) == utc(
        expected
    )


@pytest.mark.parametrize(
    "now,reason",
    [
        ("2026-09-15T13:29:59Z", "stock_regular_session_closed"),
        ("2026-09-15T20:00:00Z", "stock_regular_session_closed"),
        ("2026-09-12T14:00:00Z", "stock_exchange_closed"),
        ("2026-09-07T14:00:00Z", "stock_exchange_closed"),
        ("2026-09-17T14:00:00Z", "stock_calendar_coverage_incomplete"),
    ],
)
def test_fresh_context_does_not_enable_execution_outside_regular_session(now, reason):
    with pytest.raises(ValueError, match=reason):
        calendar().require_regular_session(utc(now))


@pytest.mark.parametrize(
    "bad",
    [
        [],
        None,
        [None],
        [{"date": "2026-09-15", "open": "09:30", "close": "09:00"}],
        [{"date": "2026-09-15", "open": "09:30+00:00", "close": "16:00"}],
        [{"date": "2026-09-15", "open": "09:30:01", "close": "16:00"}],
        [{"date": "2026-09-17", "open": "09:30", "close": "16:00"}],
        [{"date": "2026-09-12", "open": "09:30", "close": "16:00"}],
        [{"date": "2026-09-15", "open": "09:30", "close": "16:00"}] * 2,
    ],
)
def test_inconsistent_or_unavailable_calendar_fails_closed(bad):
    with pytest.raises(ValueError, match="stock_calendar"):
        StockSessionCalendar.from_provider(
            bad, start=date(2026, 9, 1), end=date(2026, 9, 16)
        )


@pytest.mark.parametrize("mutation", ["future", "unaligned", "naive", "duplicate"])
def test_session_awareness_never_relabels_invalid_timestamps(mutation):
    now = utc("2026-09-15T15:33:35Z")
    data = stock_rows("4h", now)
    if mutation == "future":
        data[-1]["t"] = (now + timedelta(days=1)).isoformat()
    elif mutation == "unaligned":
        data[-1]["t"] = (utc(data[-1]["t"]) + timedelta(minutes=30)).isoformat()
    elif mutation == "naive":
        data[-1]["t"] = utc(data[-1]["t"]).replace(tzinfo=None).isoformat()
    else:
        data[-1]["t"] = data[-2]["t"]
    with pytest.raises(ValueError):
        _candles(data, "4h", now, stock_calendar=calendar())


def test_non_stock_freshness_is_unchanged():
    now = utc("2026-09-15T15:33:35Z")
    data = stock_rows("4h", now)
    with pytest.raises(ValueError, match="4h_candles_stale"):
        _candles(data, "4h", now)
    assert _candles(data, "4h", now, stock_calendar=calendar())


def test_scanner_trace_preserves_expected_and_received_bar_evidence():
    from monatise.application.scan_audit import analysis_trace

    now = utc("2026-09-15T16:01:20Z")
    data = stock_rows("4h", now)[:-1]
    diagnostics = {}
    with pytest.raises(ValueError, match="4h_expected_closed_candle_missing"):
        _candles(data, "4h", now, stock_calendar=calendar(), diagnostics=diagnostics)
    traced = analysis_trace(
        {"asset": "SNOW", "candle_diagnostics": {"4h": diagnostics}}
    )
    assert (
        traced["candle_diagnostics"]["4h"]["expected_closed_open"]
        == "2026-09-15T12:00:00+00:00"
    )
    assert utc(traced["candle_diagnostics"]["4h"]["latest_closed_open"]) == utc(
        "2026-09-14T16:00:00Z"
    )


def test_stock_pipeline_progresses_on_overnight_context_without_changing_policy():
    import asyncio
    from monatise.application.ftmo_registry import FTMO_REGISTRY
    from monatise.application.hierarchy.assets import AssetHierarchyAnalysis

    now = utc("2026-09-15T15:33:35Z")

    class Provider:
        feed = "iex"

        def market_calendar(self, start, end):
            return calendar_rows(start, end, holidays=["2026-09-07"])

        def stock_bars(self, symbol, timeframe, limit):
            tf = {
                "4Hour": "4h",
                "1Hour": "1h",
                "15Min": "15m",
                "5Min": "5m",
                "1Min": "1m",
            }[timeframe]
            return stock_rows(tf, now)

    async def run():
        engine = AssetHierarchyAnalysis(alpaca=Provider())
        outcomes = []
        for seconds in (0, 6, 12, 18):
            result = await engine.analyse(
                FTMO_REGISTRY.resolve("SNOW"), now=now + timedelta(seconds=seconds)
            )
            outcomes.append(result)
        assert result["freshness"] == "fresh"
        assert any(
            r.get("market_structure", {}).get("structure_bias") for r in outcomes
        )
        assert (
            result["candle_diagnostics"]["4h"]["expected_closed_open"]
            == "2026-09-14T16:00:00+00:00"
        )
        for key, value in SHARED_TIMEFRAME_POLICY.metadata().items():
            assert result[key] == value
        assert result["execution"] == {"enabled": False, "orders_placed": 0}
        regime = engine._engines["SNOW"][2]._state["SNOW"].regime_context
        assert regime.source_close_time == utc("2026-09-14T20:00:00Z")
        assert (
            regime.expires_at - regime.evaluated_at
            == SHARED_TIMEFRAME_POLICY.context_lifetime
        )

    asyncio.run(run())
