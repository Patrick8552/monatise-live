from monatise.live.server import normalize_tradingview_alert


def test_tradingview_alert_normalizes_json_payload() -> None:
    alert = normalize_tradingview_alert(
        {
            "symbol": "FX:EURUSD",
            "action": "bullish",
            "confidence": "82.5",
            "indicator": "Monatise Forex Bias",
            "timeframe": "15m",
            "price": "1.0842",
        }
    )

    assert alert["symbol"] == "EURUSD"
    assert alert["action"] == "BUY"
    assert alert["confidence"] == 82.5
    assert alert["indicator"] == "Monatise Forex Bias"


def test_tradingview_alert_accepts_plain_text_key_values() -> None:
    alert = normalize_tradingview_alert("symbol=GBPUSD, action=sell, confidence=91, timeframe=1h")

    assert alert["symbol"] == "GBPUSD"
    assert alert["action"] == "SELL"
    assert alert["confidence"] == 91
    assert alert["timeframe"] == "1h"


def test_tradingview_alert_clamps_confidence() -> None:
    alert = normalize_tradingview_alert({"ticker": "USDJPY", "bias": "neutral", "confidence": "120"})

    assert alert["symbol"] == "USDJPY"
    assert alert["action"] == "WAIT"
    assert alert["confidence"] == 100
