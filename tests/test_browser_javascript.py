from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "app.js"
INDEX_HTML = ROOT / "app" / "index.html"
COINGLASS_DASHBOARD_JS = ROOT / "app" / "coinglass-dashboard.js"
MEMECOINS_JS = ROOT / "app" / "memecoins.js"


def test_dashboard_javascript_has_valid_syntax() -> None:
    node = shutil.which("node")
    if node is None:
        return
    for script in (APP_JS, COINGLASS_DASHBOARD_JS, MEMECOINS_JS):
        result = subprocess.run([node, "--check", str(script)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


def test_coinglass_dashboard_price_history_respects_the_interval_dropdown() -> None:
    source = COINGLASS_DASHBOARD_JS.read_text(encoding="utf-8")
    # Previously hardcoded to ANALYSIS_INTERVAL ("30m") for every asset
    # except BTC/ETH/SOL, silently ignoring the INTERVAL dropdown.
    assert 'const interval = els.intervalSelect.value || ANALYSIS_INTERVAL;' in source
    assert 'const interval = ANALYSIS_INTERVAL;\n  requireCoinGlass' not in source


def test_memecoins_creator_panel_is_read_only_and_fetches_from_production_endpoint() -> None:
    source = MEMECOINS_JS.read_text(encoding="utf-8")
    assert '"/api/memecoins/creators?limit=15"' in source
    # No wallet connect, signing, or transaction submission -- research only.
    for forbidden in ("signTransaction", "sendTransaction", "connectWallet", "Keypair"):
        assert forbidden not in source


def test_coinglass_dashboard_price_history_falls_back_across_exchanges() -> None:
    source = COINGLASS_DASHBOARD_JS.read_text(encoding="utf-8")
    assert 'const CRYPTO_FALLBACK_EXCHANGES = ["Binance", "OKX", "Bybit"];' in source
    assert "rows.resolvedExchange = exchange;" in source
    # The fallback must stay visible to the user, never silently swap the
    # exchange label without saying so.
    assert "does not list this pair" in source


def test_coinglass_dashboard_handles_current_sentiment_shape_and_liquidity_fallback() -> None:
    source = (ROOT / "app" / "coinglass-dashboard.js").read_text(encoding="utf-8")
    assert "Array.isArray(payload.data) ? payload.data[0] : payload.data" in source
    assert "return await getHyperliquidBookLiquidity()" in source
    assert 'const HYPER_BASE = "https://api.hyperliquid.xyz/info"' in source
    assert "rawTime < 1_000_000_000_000 ? rawTime * 1000 : rawTime" in source
    assert "Number(analysis.stage_total) || 14" in source
    assert "Production 13-stage pipeline" not in source


def test_dashboard_signal_core_is_authoritative_and_production_is_advisory() -> None:
    source = COINGLASS_DASHBOARD_JS.read_text(encoding="utf-8")
    html = (ROOT / "app" / "coinglass-dashboard.html").read_text(encoding="utf-8")
    assert "const SIGNAL_CORE_MIN_EVIDENCE = 3;" in source
    assert "evidenceScore >= SIGNAL_CORE_MIN_EVIDENCE" in source
    assert "function signalMarketDataFresh()" in source
    assert "&& freshMarketData" in source
    assert "Signal Core remains authoritative for dashboard analysis" in source
    assert "Advisory conflict noted; Signal Core decision and risk controls remain unchanged" in source
    assert "renderAuthoritativeFramework(setup);" not in source
    assert "productionAdvisoryUnavailable: true" in source
    assert "WAIT · NO TRADE" not in source + html
    assert "say NO TRADE instead of fabricating a trade" in source


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
