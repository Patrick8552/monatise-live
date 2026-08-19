from datetime import datetime, timedelta, timezone

from monatise.application.stock_analysis import build_directional_levels, build_stock_analysis


NOW = datetime(2026, 8, 7, 20, tzinfo=timezone.utc)


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


def test_flashalpha_enriches_but_cannot_change_quiver_direction() -> None:
    result = build_stock_analysis(
        {"symbol": "SPY", "available": True, "summary": {"score": 3}},
        flashalpha={"source": "FlashAlpha", "net_gex": 2850000000, "net_gex_label": "positive", "gamma_flip": 595.25},
    )
    assert result["decision"] == "BUY_WATCH"
    assert result["additional_context"]["flashalpha"]["authoritative_for_direction"] is False
    assert result["additional_context"]["flashalpha"]["net_gex_label"] == "positive"
    assert result["additional_context"]["flashalpha"]["available"] is True


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
