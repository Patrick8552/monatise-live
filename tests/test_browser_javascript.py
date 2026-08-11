from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "app.js"
INDEX_HTML = ROOT / "app" / "index.html"


def test_dashboard_javascript_has_valid_syntax() -> None:
    node = shutil.which("node")
    if node is None:
        return
    result = subprocess.run([node, "--check", str(APP_JS)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_coinglass_dashboard_handles_current_sentiment_shape_and_liquidity_fallback() -> None:
    source = (ROOT / "app" / "coinglass-dashboard.js").read_text(encoding="utf-8")
    assert "Array.isArray(payload.data) ? payload.data[0] : payload.data" in source
    assert "return await getHyperliquidBookLiquidity()" in source
    assert 'const HYPER_BASE = "https://api.hyperliquid.xyz/info"' in source
    assert "rawTime < 1_000_000_000_000 ? rawTime * 1000 : rawTime" in source
    assert "Number(analysis.stage_total) || 14" in source
    assert "Production 13-stage pipeline" not in source


def test_dashboard_does_not_restore_removed_london_runtime_gate() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "app").glob("*.js"))
    assert "londonSession(" not in source
    assert "commodityLondonGuard(" not in source
    assert "londonCommodityInput" not in source
    assert "London/New York" not in source


def test_dashboard_does_not_restore_payment_or_execution_controls() -> None:
    source = (APP_JS.read_text(encoding="utf-8") + INDEX_HTML.read_text(encoding="utf-8")).lower()
    for removed_surface in ("stripe", "billingcheckout", "support with usdc", "usdc payment required"):
        assert removed_surface not in source


def test_stock_watch_fails_closed_without_premium_price_data() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert 'type: stockWatchOnly ? "unavailable" : "sample"' in source
    assert 'if (isQuiverAsset(symbol)) renderStockWatchOnly();' in source
    assert 'if (isQuiverAsset(selectedAsset) && candleSource.type !== "live")' in source
    assert "BTC sample candles are never reused for stocks" in source
    assert "Alpaca entries, stops, targets, and Finnhub enrichment require premium access" in source


def test_quiver_panel_requires_healthy_authoritative_datasets() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert 'const authorityHealthy = ["congress", "insider"].every' in source
    assert "!quiverContext.available || !authorityHealthy" in source
    assert 'const datasetMeta = quiverContext.datasetMeta || {}' in source
    assert 'metadata.status || "unknown"' in source


def test_stock_watch_clears_crypto_command_metrics() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    for expected in (
        'els.decisionExposure.textContent = "Unavailable"',
        'els.opportunityScore.textContent = "--"',
        'els.cioPosture.textContent = "Restricted"',
        'if (isQuiverAsset(selectedAsset) && candleSource.type !== "live")',
    ):
        assert expected in source
