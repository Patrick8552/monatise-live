from datetime import datetime, timezone
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "openclaw-skills/crypto-asset-router/scripts/analyze_crypto.py"
SPEC = importlib.util.spec_from_file_location("openclaw_crypto_analyze", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
WEEKDAY = datetime(2026, 7, 24, tzinfo=timezone.utc)


def payload(*, classification="trend", direction="long", score=7, grid_score=2):
    result = {
        "classification": classification,
        "direction": direction,
        "score": score,
        "grid_score": grid_score,
        "score_threshold": 7,
        "conviction": 0.78,
        "entry": 100.0,
        "invalidation": 95.0 if direction != "short" else 105.0,
        "target": 110.0 if direction != "short" else 90.0,
        "reward_risk": 2.0,
        "reasons": ["production evidence aligned"],
        "blockers": [],
        "data_source": "CoinGlass futures price history",
    }
    if classification == "grid":
        result["grid_plan"] = {
            "center": 100.0,
            "buy_levels": [99.0, 98.0, 97.0],
            "sell_levels": [101.0, 102.0, 103.0],
            "lower_boundary": 97.0,
            "upper_boundary": 103.0,
            "lower_invalidation": 96.0,
            "upper_invalidation": 104.0,
            "spacing": 1.0,
            "levels_per_side": 3,
        }
    return result


def test_plus_seven_production_score_is_long():
    result = MODULE.analyze("BTC", payload=payload(score=7), current_time=WEEKDAY)
    assert result["decision"] == "LONG"
    assert result["reason_code"] == "SIGNED_SCORE_THRESHOLD_MET"
    assert result["execution"] == {"enabled": False, "orders_placed": 0}


def test_minus_seven_production_score_is_short():
    result = MODULE.analyze("ETH", payload=payload(direction="short", score=-7), current_time=WEEKDAY)
    assert result["decision"] == "SHORT"


def test_scores_inside_threshold_are_no_trade():
    assert MODULE.analyze("BTC", payload=payload(score=6), current_time=WEEKDAY)["decision"] == "NO_TRADE"
    assert MODULE.analyze("BTC", payload=payload(direction="short", score=-6), current_time=WEEKDAY)["decision"] == "NO_TRADE"


def test_grid_score_seven_is_grid_trade_analysis():
    result = MODULE.analyze(
        "BTC",
        payload=payload(classification="grid", direction="two_sided", score=0, grid_score=7),
        current_time=WEEKDAY,
    )
    assert result["decision"] == "GRID"
    assert result["reason_code"] == "GRID_SCORE_THRESHOLD_MET"
    assert len(result["grid_plan"]["buy_levels"]) == 3
    assert len(result["grid_plan"]["sell_levels"]) == 3
    message = MODULE.telegram(result)
    assert "Buy levels: $99.00 | $98.00 | $97.00" in message
    assert "Sell levels: $101.00 | $102.00 | $103.00" in message
    assert "Entry:" not in message


def test_grid_without_multiple_levels_fails_closed():
    data = payload(classification="grid", direction="two_sided", score=0, grid_score=8)
    data["grid_plan"] = None
    result = MODULE.analyze("BTC", payload=data, current_time=WEEKDAY)
    assert result["decision"] == "NO_TRADE"
    assert result["reason_code"] == "INVALID_GRID_LEVELS"


def test_weekend_is_always_no_trade():
    result = MODULE.analyze("BTC", payload=payload(score=9), current_time=datetime(2026, 7, 25, tzinfo=timezone.utc))
    assert result["decision"] == "NO_TRADE"
    assert result["reason_code"] == "WEEKEND_NO_TRADE"


def test_invalid_risk_levels_fail_closed():
    data = payload(score=8)
    data["target"] = None
    result = MODULE.analyze("SOL", payload=data, current_time=WEEKDAY)
    assert result["decision"] == "NO_TRADE"
    assert result["reason_code"] == "INVALID_RISK_LEVELS"


def test_production_blocker_is_reported_instead_of_score_failure():
    data = payload(classification="no_trade", score=3, grid_score=8)
    data["blockers"] = ["market structure is unstable"]
    result = MODULE.analyze("BTC", payload=data, current_time=WEEKDAY)
    assert result["decision"] == "NO_TRADE"
    assert result["reason_code"] == "PRODUCTION_BLOCKED"
    assert result["blockers"] == ["market structure is unstable"]
