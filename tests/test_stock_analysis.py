from monatise.application.stock_analysis import build_directional_levels, build_stock_analysis


def test_supportive_quiver_context_creates_analysis_only_buy_watch() -> None:
    result = build_stock_analysis({"symbol": "NVDA", "source": "Quiver Quantitative", "available": True, "summary": {"score": 4, "drivers": ["insider buying"]}})
    assert result["decision"] == "BUY_WATCH"
    assert result["execution"] == {"enabled": False, "orders_placed": 0}


def test_weak_context_stays_no_trade() -> None:
    result = build_stock_analysis({"symbol": "AAPL", "available": True, "summary": {"score": 1}})
    assert result["decision"] == "NO_TRADE"


def test_confirmed_breakout_builds_structural_entry_stop_and_two_r_target() -> None:
    bars = [{"h": 101 + index, "l": 98 + index, "c": 100 + index} for index in range(21)]
    bars.append({"h": 124, "l": 119, "c": 123})
    levels = build_directional_levels("BUY_WATCH", bars, {"latestQuote": {"bp": 122.9, "ap": 123.1}})
    assert levels["setup_status"] == "confirmed"
    assert levels["stop_loss"] < levels["entry"] < levels["target"]
    assert levels["reward_risk"] == 2.0


def test_unconfirmed_direction_never_invents_trade_levels() -> None:
    bars = [{"h": 110, "l": 100, "c": 105} for _ in range(22)]
    levels = build_directional_levels("BUY_WATCH", bars, {})
    assert levels["setup_status"] == "awaiting_price_confirmation"
    assert levels["entry"] is None and levels["stop_loss"] is None
