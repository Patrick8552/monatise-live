from monatise.analysis.context import context_assets, grid_instruction, indicator_snapshot
from monatise.core.models import Candle


def test_indicator_snapshot_and_instruction_for_range() -> None:
    candles = [
        Candle(str(index), open=100 + (index % 3), high=103 + (index % 2), low=97 - (index % 2), close=100 + ((index + 1) % 3))
        for index in range(60)
    ]

    indicators = indicator_snapshot(candles)
    instruction = grid_instruction(indicators)

    assert indicators.atr > 0
    assert 0 <= indicators.rsi <= 100
    assert instruction["action"] in {"normal", "widen", "reduce", "pause"}
    assert instruction["spacingMultiplier"] >= 0


def test_context_assets_for_gold_and_oil() -> None:
    prices = {"GOLD": 4300.0, "CL": 90.0, "BRENTOIL": 94.0, "xyz:COPPER": 6.1}

    gold_assets = context_assets("GOLD", prices)
    oil_assets = context_assets("CL", prices)

    assert gold_assets[0]["symbol"] == "GOLD"
    assert any(asset["symbol"] == "US10Y_REAL" and not asset["available"] for asset in gold_assets)
    assert any(asset["symbol"] == "BRENTOIL" and asset["available"] for asset in oil_assets)
