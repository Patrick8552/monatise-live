from datetime import datetime, timezone
import importlib.util
from pathlib import Path

SCRIPT=Path(__file__).parents[1]/"openclaw-skills/crypto-asset-router/scripts/analyze_crypto.py"
SPEC=importlib.util.spec_from_file_location("openclaw_crypto_analyze",SCRIPT)
MODULE=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MODULE)

def payload(direction="up", source="CoinGlass futures price history"):
    bullish=direction=="up"
    return {"source":source,"mark":100.0,"indicator":{"trend":direction,"atr":2.0,"atr_pct":.02},"analysis":{"candle_count":120,"trend":direction,"nearest_level":{"price":100.0},"take_profit":{"price":105.0 if bullish else 95.0},"invalidation":90.0 if bullish else 110.0,"levels":[{"price":95.0},{"price":105.0},{"price":115.0 if bullish else 85.0}]},"fvg":{"bias":"bullish" if bullish else "bearish"}}

def test_coinglass_can_pass_long_gate_on_weekday():
    result=MODULE.analyze("BTC",payload=payload("up"),current_time=datetime(2026,7,24,tzinfo=timezone.utc))
    assert result["decision"]=="LONG"
    assert result["reason_code"]=="VALID_LONG_SETUP"
    assert result["stop_loss"]["price"]<result["entry"]["minimum"]<result["targets"][0]["price"]
    assert result["warnings"]==[]
    assert result["execution"]=={"enabled":False,"orders_placed":0}

def test_coinglass_can_pass_short_gate_on_weekday():
    result=MODULE.analyze("ETH",payload=payload("down"),current_time=datetime(2026,7,24,tzinfo=timezone.utc))
    assert result["decision"]=="SHORT"
    assert result["targets"][0]["price"]<result["entry"]["minimum"]<result["stop_loss"]["price"]

def test_weekend_is_always_no_trade():
    result=MODULE.analyze("BTC",payload=payload("up"),current_time=datetime(2026,7,25,tzinfo=timezone.utc))
    assert result["decision"]=="NO_TRADE"
    assert result["reason_code"]=="WEEKEND_NO_TRADE"
    assert result["entry"] is None and result["stop_loss"] is None and result["targets"]==[]

def test_non_coinglass_provider_is_rejected():
    result=MODULE.analyze("BTC",payload=payload("up", "Hyperliquid candleSnapshot"),current_time=datetime(2026,7,24,tzinfo=timezone.utc))
    assert result["decision"]=="NO_TRADE"
    assert result["reason_code"]=="PROVIDER_UNAVAILABLE"
    assert MODULE.COINGLASS_NOTICE in result["warnings"]

def test_conflicting_coinglass_context_is_no_trade():
    data=payload("up"); data["indicator"]["trend"]="down"
    assert MODULE.analyze("SOL",payload=data,current_time=datetime(2026,7,24,tzinfo=timezone.utc))["decision"]=="NO_TRADE"
