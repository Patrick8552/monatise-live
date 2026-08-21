from datetime import datetime, timedelta, timezone

from monatise.application.stock_analysis import build_directional_levels, build_stock_analysis, refresh_setup_validity


NOW = datetime(2026, 8, 7, 19, tzinfo=timezone.utc)


def timestamped_bars() -> list[dict]:
    start = NOW - timedelta(hours=22)
    bars = [{"h": 101 + index, "l": 98 + index, "c": 100 + index, "t": (start + timedelta(hours=index)).isoformat()} for index in range(21)]
    bars.append({"h": 124, "l": 119, "c": 123, "t": (NOW - timedelta(hours=1)).isoformat()})
    return bars


def test_supportive_quiver_context_creates_analysis_only_buy_watch() -> None:
    result = build_stock_analysis({"symbol": "NVDA", "source": "Quiver Quantitative", "available": True, "summary": {"score": 4, "drivers": ["insider buying"]}})
    assert result["decision"] == "BUY_WATCH"
    assert result["execution"] == {"enabled": False, "orders_placed": 0}


def test_weak_context_stays_no_trade() -> None:
    result = build_stock_analysis({"symbol": "AAPL", "available": True, "summary": {"score": 1}})
    assert result["decision"] == "NO_TRADE"


def test_finnhub_enriches_but_cannot_change_quiver_direction() -> None:
    result = build_stock_analysis(
        {"symbol": "AAPL", "available": True, "summary": {"score": -2}},
        snapshot={"latestQuote": {"bp": 99, "ap": 101}},
        finnhub={"source": "Finnhub", "quote": {"c": 100}, "news": [{}, {}], "recommendations": [{"strongBuy": 99}]},
    )
    assert result["decision"] == "SELL_WATCH"
    assert result["additional_context"]["authoritative_for_direction"] is False
    assert result["additional_context"]["news_count"] == 2


def test_flashalpha_confirms_quiver_direction() -> None:
    result = build_stock_analysis(
        {"symbol": "SPY", "available": True, "summary": {"score": 3}},
        flashalpha={"source": "FlashAlpha", "net_gex": 2850000000, "net_gex_label": "positive", "underlying_price": 597.5, "gamma_flip": 595.25},
    )
    assert result["decision"] == "BUY_WATCH"
    assert result["additional_context"]["flashalpha"]["authoritative_for_direction"] == "confirmation_only"
    assert result["additional_context"]["flashalpha"]["net_gex_label"] == "positive"
    assert result["additional_context"]["flashalpha"]["available"] is True


def test_flashalpha_conflict_suppresses_quiver_watch() -> None:
    result = build_stock_analysis(
        {"symbol": "SPY", "available": True, "summary": {"score": 3}},
        flashalpha={"source": "FlashAlpha", "net_gex": 1, "underlying_price": 590, "gamma_flip": 595.25},
    )
    assert result["decision"] == "NO_TRADE"
    assert result["reason_code"] == "FLASHALPHA_POSITIONING_CONFLICT"


def test_flashalpha_unavailable_is_reported_but_not_fatal() -> None:
    result = build_stock_analysis(
        {"symbol": "SPY", "available": True, "summary": {"score": 3}},
        flashalpha={"source": "FlashAlpha", "unavailable": True},
    )
    assert result["additional_context"]["flashalpha"]["available"] is False


def test_confirmed_breakout_builds_structural_entry_stop_and_two_r_target() -> None:
    levels = build_directional_levels("BUY_WATCH", timestamped_bars(), {"latestQuote": {"bp": 122.9, "ap": 123.1}}, now=NOW)
    assert levels["setup_status"] == "confirmed"
    assert levels["stop_loss"] < levels["entry"] < levels["target"]
    assert levels["reward_risk"] == 2.0


def test_unconfirmed_direction_never_invents_trade_levels() -> None:
    bars = [{"h": 110, "l": 100, "c": 105, "t": (NOW - timedelta(hours=22-index)).isoformat()} for index in range(22)]
    levels = build_directional_levels("BUY_WATCH", bars, {}, now=NOW)
    assert levels["setup_status"] == "awaiting_price_confirmation"
    assert levels["entry"] is None and levels["stop_loss"] is None


def test_open_or_stale_bar_never_confirms_levels() -> None:
    open_bar = timestamped_bars()
    open_bar[-1]["t"] = (NOW - timedelta(minutes=30)).isoformat()
    assert build_directional_levels("BUY_WATCH", open_bar, {}, now=NOW)["setup_status"] == "market_data_unavailable"

    stale = timestamped_bars()
    stale[-1]["t"] = (NOW - timedelta(days=5)).isoformat()
    assert build_directional_levels("BUY_WATCH", stale, {}, now=NOW)["setup_status"] == "market_data_unavailable"


def test_breakout_far_beyond_entry_is_marked_missed() -> None:
    levels = build_directional_levels("BUY_WATCH", timestamped_bars(), {"latestQuote": {"bp": 149, "ap": 151}}, now=NOW)
    assert levels["setup_status"] == "entry_missed"
    assert levels["entry"] is None


def test_confirmed_setup_expiry_is_anchored_to_confirmation_candle() -> None:
    result = build_stock_analysis(
        {"symbol": "NVDA", "available": True, "summary": {"score": 3}},
        trigger_bars=timestamped_bars(), snapshot={"latestQuote": {"bp": 122.9, "ap": 123.1}},
        now=NOW, validity_minutes=90,
    )
    assert result["setup_state"] == "ACTIVE"
    assert result["analysis_timeframe"] == "1H" and result["trigger_timeframe"] == "15M"
    assert result["setup_created_at"] == (NOW - timedelta(minutes=45)).isoformat()
    assert result["setup_expires_at"] == (NOW + timedelta(minutes=45)).isoformat()
    assert result["validity_remaining_seconds"] == 2700


def test_expired_setup_becomes_no_trade_and_levels_are_removed() -> None:
    result = build_stock_analysis(
        {"symbol": "NVDA", "available": True, "summary": {"score": 3}},
        trigger_bars=timestamped_bars(), snapshot={"latestQuote": {"bp": 122.9, "ap": 123.1}},
        now=NOW, validity_minutes=30,
    )
    assert result["setup_state"] == "EXPIRED"
    assert result["decision"] == "NO_TRADE" and result["reason_code"] == "SETUP_EXPIRED"
    assert result["entry"] is None and result["stop_loss"] is None and result["target"] is None


def test_refresh_time_does_not_replace_confirmation_time() -> None:
    first = build_stock_analysis(
        {"symbol": "NVDA", "available": True, "summary": {"score": 3}}, trigger_bars=timestamped_bars(),
        snapshot={"latestQuote": {"bp": 122.9, "ap": 123.1}}, now=NOW, validity_minutes=120,
    )
    second = build_stock_analysis(
        {"symbol": "NVDA", "available": True, "summary": {"score": 3}}, trigger_bars=timestamped_bars(),
        snapshot={"latestQuote": {"bp": 122.9, "ap": 123.1}}, now=NOW + timedelta(minutes=10), validity_minutes=120,
    )
    assert first["setup_created_at"] == second["setup_created_at"]
    assert first["setup_expires_at"] == second["setup_expires_at"]
    assert second["validity_remaining_seconds"] == first["validity_remaining_seconds"] - 600


def test_setup_cannot_remain_active_beyond_regular_session_close() -> None:
    after_close = datetime(2026, 8, 7, 20, 5, tzinfo=timezone.utc)
    bars = timestamped_bars()
    bars[-1]["t"] = datetime(2026, 8, 7, 19, 45, tzinfo=timezone.utc).isoformat()
    result = build_stock_analysis(
        {"symbol": "NVDA", "available": True, "summary": {"score": 3}}, trigger_bars=bars,
        snapshot={"latestQuote": {"bp": 122.9, "ap": 123.1}}, now=after_close, validity_minutes=90,
    )
    assert result["setup_state"] == "EXPIRED"
    assert result["expiry_reason"] == "SESSION_EXPIRED"


def test_cached_setup_validity_is_recomputed_without_mutating_cached_payload() -> None:
    cached = {
        "setup_state": "ACTIVE", "decision": "BUY_WATCH", "reason_code": "CONFIRMED",
        "setup_expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        "validity_remaining_seconds": 3600, "entry": 100, "stop_loss": 98, "target": 104,
        "reward_risk": 2,
    }
    refreshed = refresh_setup_validity(cached, NOW)
    assert refreshed["validity_remaining_seconds"] == 300
    assert cached["validity_remaining_seconds"] == 3600

    expired = refresh_setup_validity(cached, NOW + timedelta(minutes=6))
    assert expired["setup_state"] == "EXPIRED" and expired["decision"] == "NO_TRADE"
    assert expired["entry"] is None and expired["stop_loss"] is None and expired["target"] is None
