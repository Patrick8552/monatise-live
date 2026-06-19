import os

from monatise.live.config import LIVE_CONFIRMATION, RuntimeConfig
from monatise.live.server import classify_tradingview_alert, enrich_tradingview_alert, normalize_tradingview_alert, operator_status_payload


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


def test_tradingview_alert_normalizes_gold_and_silver_symbols() -> None:
    gold = normalize_tradingview_alert({"symbol": "OANDA:XAUUSD", "action": "long"})
    silver = normalize_tradingview_alert({"symbol": "OANDA:XAGUSD", "action": "short"})

    assert gold["symbol"] == "GOLD"
    assert gold["action"] == "BUY"
    assert silver["symbol"] == "XAG"
    assert silver["action"] == "SELL"


def test_tradingview_alert_normalizes_stock_and_index_symbols() -> None:
    stock = normalize_tradingview_alert({"symbol": "NASDAQ:AAPL", "action": "bullish"})
    index = normalize_tradingview_alert({"symbol": "TVC:IXIC", "action": "bearish"})

    assert stock["symbol"] == "AAPL"
    assert stock["action"] == "BUY"
    assert index["symbol"] == "NASDAQ"
    assert index["action"] == "SELL"


def test_tradingview_alert_preserves_gold_indicator_stack() -> None:
    alert = normalize_tradingview_alert(
        {
            "symbol": "OANDA:XAUUSD",
            "action": "SELL",
            "indicators": {
                "luxalgo": "sell",
                "liquidity_grabs": "bearish",
                "auto_fib": "below 0.618",
                "daily_vwap": "below",
            },
            "volume_profile": "below value area",
            "rsi_sma_cross": "cross down",
        }
    )

    assert alert["symbol"] == "GOLD"
    assert alert["indicators"]["luxalgo"] == "sell"
    assert alert["indicators"]["liquidity_grabs"] == "bearish"
    assert alert["indicators"]["auto_fib"] == "below 0.618"
    assert alert["indicators"]["daily_vwap"] == "below"
    assert alert["indicators"]["volume_profile"] == "below value area"
    assert alert["indicators"]["rsi_sma_cross"] == "cross down"


def test_tradingview_alert_classification_is_confluence_only() -> None:
    alert = normalize_tradingview_alert(
        {
            "symbol": "OANDA:XAUUSD",
            "action": "BUY",
            "confidence": 81,
            "receivedAt": 1_000,
            "indicators": {
                "luxalgo": "buy",
                "daily_vwap": "above",
                "liquidity_grabs": "bullish grab",
            },
        }
    )
    alert["receivedAt"] = 1_000

    classification = classify_tradingview_alert(alert, now=1_060)

    assert classification["role"] == "confluence_only"
    assert classification["route"] == "metals and commodities confluence"
    assert classification["state"] == "confirming"
    assert classification["agreement"] == "confirming"
    assert classification["fresh"] is True
    assert classification["indicatorBias"] == "BUY"
    assert classification["indicatorScore"] == 3
    assert classification["snapshotWindow"]["reassessAt"] == 2_800
    assert classification["executionAllowed"] is False


def test_tradingview_alert_classification_flags_conflict_and_stale() -> None:
    alert = {
        "symbol": "EURUSD",
        "action": "SELL",
        "confidence": 66,
        "receivedAt": 1_000,
        "indicators": {"daily_vwap": "above", "rsi_sma_cross": "cross up"},
    }

    fresh = classify_tradingview_alert(alert, now=1_060)
    stale = classify_tradingview_alert(alert, now=10_000)

    assert fresh["route"] == "forex confluence"
    assert fresh["state"] == "conflict-watch"
    assert fresh["agreement"] == "conflicting"
    assert stale["state"] == "stale"
    assert stale["fresh"] is False


def test_enriched_tradingview_alert_keeps_raw_alert_fields() -> None:
    alert = normalize_tradingview_alert({"symbol": "NASDAQ:NVDA", "action": "long", "confidence": 72})

    enriched = enrich_tradingview_alert(alert, now=alert["receivedAt"] + 5)

    assert enriched["symbol"] == "NVDA"
    assert enriched["action"] == "BUY"
    assert enriched["classification"]["route"] == "stocks and indices confluence"
    assert enriched["classification"]["executionAllowed"] is False


def test_operator_status_reports_non_secret_integration_state() -> None:
    old_values = {
        key: os.environ.get(key)
        for key in [
            "COINGLASS_API_KEY",
            "MONATISE_SMTP_PROVIDER",
            "MONATISE_SMTP_FROM",
            "MONATISE_SMTP_PASSWORD",
            "MONATISE_ALERT_EMAILS",
            "RENDER_GIT_COMMIT",
        ]
    }
    os.environ["COINGLASS_API_KEY"] = "cg_secret"
    os.environ["MONATISE_SMTP_PROVIDER"] = "resend"
    os.environ["MONATISE_SMTP_FROM"] = "Monatise <no-reply@example.com>"
    os.environ["MONATISE_SMTP_PASSWORD"] = "smtp_secret"
    os.environ["MONATISE_ALERT_EMAILS"] = "ops@example.com"
    os.environ["RENDER_GIT_COMMIT"] = "abcdef123456"
    try:
        payload = operator_status_payload(
            RuntimeConfig(
                mode="live",
                network="mainnet",
                execution_mode="live",
                allow_live_orders=True,
                live_confirmation=LIVE_CONFIRMATION,
                tradingview_webhook_token="tv_secret",
            )
        )
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    assert payload["deploy"]["commit"] == "abcdef123456"
    assert payload["integrations"]["coinglass"]["configured"] is True
    assert payload["integrations"]["tradingView"]["configured"] is True
    assert payload["integrations"]["smtp"]["configured"] is True
    assert payload["integrations"]["smtp"]["alertsConfigured"] is True
    assert payload["riskCaps"]["allowLiveOrders"] is True
    assert "cg_secret" not in str(payload)
    assert "smtp_secret" not in str(payload)
    assert "tv_secret" not in str(payload)
