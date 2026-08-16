import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).parents[1] / "openclaw-skills/crypto-asset-router/scripts/analyze_crypto_dynamic.py"
SPEC = importlib.util.spec_from_file_location("openclaw_crypto_analyze_dynamic", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def payload(*, classification="trend", direction="long", actionable=True, quality_passed=True):
    provenance = {
        "base_asset": "WOOD", "instrument": "WOODUSDT", "exchange": "Bybit", "quote_asset": "USDT",
        "source": "CoinGlass futures supported-coins + supported-exchange-pairs + pairs-markets",
        "supported_coins_observed_at": "2026-08-13T00:00:00+00:00", "market_observed_at": "2026-08-13T00:00:01+00:00",
    }
    result = {
        "symbol": "WOOD", "interval": "1h", "classification": classification, "direction": direction,
        "provenance": provenance,
        "evidence": {"current_price": 0.42, "candle_count": 200},
        "data_quality": {"passed": quality_passed, "failures": [] if quality_passed else ["insufficient candle history: 20/120"], "warnings": []},
        "score": 8, "grid_score": 3, "score_threshold": 7, "volatility_assessment": "continuation requires confirmation",
        "run_id": "run-wood-1", "execution_enabled": False,
    }
    if actionable and quality_passed:
        result.update({
            "entry_zone": {"low": 0.40, "high": 0.41}, "entry_trigger": "confirmed retracement/reclaim",
            "invalidation": 0.38, "targets": [0.46], "reward_risk": 2.0,
            "expires_at": "2026-08-13T04:00:00+00:00",
        })
        if classification == "grid":
            result["grid_plan"] = {
                "center": 0.42, "buy_levels": [0.41, 0.40, 0.39], "sell_levels": [0.43, 0.44, 0.45],
                "lower_boundary": 0.39, "upper_boundary": 0.45,
                "lower_invalidation": 0.38, "upper_invalidation": 0.46,
                "spacing": 0.01, "levels_per_side": 3,
            }
    else:
        result.update({"entry_zone": None, "entry_trigger": None, "invalidation": None, "targets": [], "reward_risk": None, "expires_at": None, "grid_plan": None})
    return result


def test_normalize_accepts_non_core_crypto_ticker():
    assert MODULE.normalize("wood/usdt") == "WOOD"
    assert MODULE.normalize("/analyze PEPE") == "PEPE"


def test_normalize_rejects_forex_and_malformed():
    for bad in ("EURUSD", "../../BTC", "USD", "", "BTC$USDT"):
        with pytest.raises(ValueError):
            MODULE.normalize(bad)


def test_normalize_rejects_core_symbols():
    for core in ("BTC", "ETH", "SOL"):
        with pytest.raises(ValueError, match="core asset"):
            MODULE.normalize(core)


def test_confirmed_trend_is_actionable_with_full_plan():
    result = MODULE.analyze("WOOD", payload=payload())
    assert result["actionable"] is True
    assert result["classification"] == "trend"
    assert result["direction"] == "long"
    assert result["entry_zone"] == {"low": 0.40, "high": 0.41}
    assert result["targets"] == [0.46]
    message = MODULE.telegram(result)
    assert "Decision: TREND (LONG)" in message
    assert "Entry zone: 0.4 — 0.41 (trigger required, not an automatic entry)" in message
    assert "Analysis only. No trade was executed." in message
    assert '"entry"' not in message and "Entry:" not in message.replace("Entry zone", "").replace("Entry trigger", "")


def test_grid_decision_displays_grid_score_not_the_unrelated_trend_score():
    result = MODULE.analyze("WOOD", payload=payload(classification="grid", direction="two_sided"))
    assert result["actionable"] is True
    assert result["classification"] == "grid"
    message = MODULE.telegram(result)
    assert "Score: 3/10" in message
    assert "Score: 8/10" not in message


def test_grid_decision_shows_the_full_multi_level_grid_plan():
    result = MODULE.analyze("WOOD", payload=payload(classification="grid", direction="two_sided"))
    assert result["actionable"] is True
    assert result["grid_plan"]["buy_levels"] == [0.41, 0.40, 0.39]
    assert result["grid_plan"]["sell_levels"] == [0.43, 0.44, 0.45]
    message = MODULE.telegram(result)
    assert "Decision: GRID (TWO_SIDED)" in message
    assert "Center: 0.42" in message
    assert "Buy levels: 0.41 | 0.4 | 0.39" in message
    assert "Sell levels: 0.43 | 0.44 | 0.45" in message
    assert "Boundaries: 0.39 — 0.45" in message
    assert "Invalidation: below 0.38 or above 0.46" in message
    assert "Spacing: 0.01 | 3 levels per side" in message
    # a grid has no single directional entry/target -- only the multi-level plan
    assert "Entry zone:" not in message and "Targets:" not in message


def test_grid_without_a_valid_grid_plan_fails_closed_to_no_trade():
    data = payload(classification="grid", direction="two_sided")
    data["grid_plan"] = None
    result = MODULE.analyze("WOOD", payload=data)
    assert result["actionable"] is False
    assert result["classification"] == "no_trade"
    assert any("grid_plan" in reason for reason in result["data_quality"]["failures"])


def test_grid_plan_missing_boundary_fields_fails_closed_instead_of_crashing():
    # telegram() reads grid['lower_boundary']/['upper_boundary'] (and
    # spacing/levels_per_side) unconditionally -- the validator must reject
    # a grid_plan missing them rather than let a KeyError reach telegram().
    data = payload(classification="grid", direction="two_sided")
    del data["grid_plan"]["lower_boundary"]

    result = MODULE.analyze("WOOD", payload=data)

    assert result["actionable"] is False
    assert result["classification"] == "no_trade"
    assert any("grid_plan" in reason for reason in result["data_quality"]["failures"])
    MODULE.telegram(result)  # must not raise


def test_failed_quality_gate_is_no_trade_and_never_shows_a_zone():
    result = MODULE.analyze("WOOD", payload=payload(quality_passed=False))
    assert result["actionable"] is False
    assert result["classification"] == "no_trade"
    assert result["entry_zone"] is None
    message = MODULE.telegram(result)
    assert "Decision: NO_TRADE" in message
    assert "insufficient candle history" in message


def test_missing_actionable_fields_fail_closed_even_when_classification_is_trend():
    data = payload()
    data["reward_risk"] = None  # classification says trend, quality passed, but the plan is incomplete
    result = MODULE.analyze("WOOD", payload=data)
    assert result["actionable"] is False
    assert result["classification"] == "no_trade"
    assert any("reward_risk" in reason for reason in result["data_quality"]["failures"])


def test_execution_enabled_must_be_explicitly_false():
    data = payload()
    data["execution_enabled"] = True
    result = MODULE.analyze("WOOD", payload=data)
    assert result["actionable"] is False
    assert any("execution_enabled" in reason for reason in result["data_quality"]["failures"])


def test_missing_provenance_fails_closed():
    data = payload()
    data["provenance"] = {}
    result = MODULE.analyze("WOOD", payload=data)
    assert result["actionable"] is False
    assert any("provenance" in reason for reason in result["data_quality"]["failures"])


def test_unknown_classification_fails_closed():
    data = payload()
    data["classification"] = "buy_now"
    result = MODULE.analyze("WOOD", payload=data)
    assert result["classification"] == "no_trade"
    assert result["actionable"] is False


def _run(returncode, stdout):
    return type("Run", (), {"returncode": returncode, "stdout": stdout, "stderr": ""})()


def test_fetch_never_retries_400_or_401():
    with patch.object(MODULE.subprocess, "run", return_value=_run(1, json.dumps({"http_status": 400, "reason": "unsupported"}))) as mocked:
        with pytest.raises(ValueError, match="unsupported"):
            MODULE.fetch("WOOD", "1h")
    assert mocked.call_count == 1

    with patch.object(MODULE.subprocess, "run", return_value=_run(1, json.dumps({"http_status": 401, "reason": "unauthorized"}))) as mocked:
        with pytest.raises(PermissionError):
            MODULE.fetch("WOOD", "1h")
    assert mocked.call_count == 1


def test_fetch_retries_429_and_503_with_bounded_attempts():
    with patch.object(MODULE, "time") as mock_time:
        with patch.object(MODULE.subprocess, "run", return_value=_run(1, json.dumps({"http_status": 503, "reason": "unavailable"}))) as mocked:
            with pytest.raises(RuntimeError, match="503"):
                MODULE.fetch("WOOD", "1h", attempts=3)
        assert mocked.call_count == 3
        assert mock_time.sleep.call_count == 2


def test_fetch_succeeds_without_retry_on_valid_response():
    good = json.dumps({"symbol": "WOOD", "classification": "no_trade"})
    with patch.object(MODULE.subprocess, "run", return_value=_run(0, good)) as mocked:
        result = MODULE.fetch("WOOD", "1h")
    assert result == {"symbol": "WOOD", "classification": "no_trade"}
    assert mocked.call_count == 1
