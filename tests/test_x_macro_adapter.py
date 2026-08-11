from datetime import datetime, timezone

from monatise.adapters.x_macro import XMacroAdapter, XMacroPost
from monatise.application.deployment import OrchestrationRuntime


def test_x_adapter_classifies_bitcoin_sale_as_context_only():
    post = XMacroAdapter._parse({
        "id": "123", "author_id": "42", "created_at": "2026-08-11T00:00:00Z",
        "text": "A large holder deposited BTC to an exchange and is selling bitcoin",
        "public_metrics": {"retweet_count": 20, "like_count": 100},
    })
    assert post is not None
    assert post.category == "btc_whale_sale"
    assert post.severity == "critical"
    assert post.url.endswith("/123")


def test_x_adapter_ignores_unrelated_post():
    assert XMacroAdapter._parse({"id": "1", "text": "ordinary unrelated post"}) is None


def test_x_telegram_message_requires_market_confirmation():
    post = XMacroPost("1", "Large holder sells bitcoin", "42", datetime(2026, 8, 11, tzinfo=timezone.utc), "https://x.com/i/web/status/1", "btc_whale_sale", "critical")
    message = OrchestrationRuntime._format_x_macro_post(post)
    assert "CoinGlass/price confirmation required" in message
    assert "BTC WHALE-SALE WATCH" in message
