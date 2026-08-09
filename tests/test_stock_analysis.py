from monatise.application.stock_analysis import build_stock_analysis


def test_supportive_quiver_context_creates_analysis_only_buy_watch() -> None:
    result = build_stock_analysis({"symbol": "NVDA", "source": "Quiver Quantitative", "available": True, "summary": {"score": 4, "drivers": ["insider buying"]}})
    assert result["decision"] == "BUY_WATCH"
    assert result["execution"] == {"enabled": False, "orders_placed": 0}


def test_weak_context_stays_no_trade() -> None:
    result = build_stock_analysis({"symbol": "AAPL", "available": True, "summary": {"score": 1}})
    assert result["decision"] == "NO_TRADE"
