from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import replace
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from monatise.analysis.context import context_assets, grid_instruction, indicator_snapshot
from monatise.analysis.fibonacci import analyze_fibonacci
from monatise.analysis.fvg import analyze_fvg
from monatise.adapters.coinglass import CoinGlassAdapter, CoinGlassPlanError
from monatise.adapters.hyperliquid import HyperliquidAdapter
from monatise.adapters.memecoins import discover_pumpfun, inspect_memecoin
from monatise.adapters.quiver import QuiverAdapter, normalize_quiver_symbol
from monatise.live.config import LIVE_CONFIRMATION, RuntimeConfig
from monatise.live.emailer import EmailDeliveryError, expose_dev_reset_code, send_login_code, send_password_reset_code, send_trading_alert_email
from monatise.live.secrets import secret_value
from monatise.live.service import JsonEncoder, TradingService
from monatise.live.users import REMEMBERED_SESSION_SECONDS, SESSION_SECONDS, User, UserCredentials, UserStore, encryption_key_configured

STOCK_WATCHLIST = ("SPX", "NDX", "NASDAQ", "QQQ", "SPY", "AAPL", "TSLA", "NVDA")
METALS_WATCHLIST = {"GOLD", "XAU", "XAUUSD", "XAG", "XAGUSD", "SILVER"}
FOREX_QUOTES = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}
GOLD_ANALYSIS_INDICATORS = (
    {"name": "LuxAlgo", "role": "historical colored market-structure context"},
    {"name": "Liquidity Swings", "settings": "14; Wick Extremity", "role": "swing liquidity and wick-extremity mapping"},
    {"name": "Equal Highs and Lows", "settings": "1; 200; Solid", "role": "resting-liquidity targets"},
    {"name": "Liquidity Grabs | Flux Charts", "role": "liquidity sweep and grab confirmation"},
    {"name": "Dynamic Trend", "settings": "21; 0.3; 0.85; 8; 1.7; 1.4; 2.2; EMA", "role": "dynamic trend and regime context"},
    {"name": "Auto Fib Retracement", "settings": "3; 10", "role": "retracement, extension, target, and invalidation geometry"},
    {"name": "Daily VWAP", "settings": "8; 30", "role": "daily fair-value and mean-reversion context"},
    {"name": "Volume Profile / Fixed Range", "settings": "150; 24; 70; 2", "role": "high-volume nodes, low-volume gaps, and value area"},
    {"name": "HTF Levels PRO", "settings": "50; 1; Dashed", "role": "higher-timeframe support, resistance, and liquidity levels"},
)
TRADINGVIEW_ACTIONS = {
    "BUY": "BUY",
    "BULL": "BUY",
    "BULLISH": "BUY",
    "LONG": "BUY",
    "SELL": "SELL",
    "BEAR": "SELL",
    "BEARISH": "SELL",
    "SHORT": "SELL",
    "WAIT": "WAIT",
    "NEUTRAL": "WAIT",
    "HOLD": "WAIT",
}
TRADINGVIEW_FRESH_SECONDS = 5 * 60
TRADINGVIEW_SNAPSHOT_LOCK_SECONDS = 15 * 60
TRADINGVIEW_ALERT_LIMIT = 50
COINGLASS_PROXY_BASE = "https://open-api-v4.coinglass.com"
COINGLASS_PROXY_PATHS = {
    "/api/article/list",
    "/api/futures/funding-rate/exchange-list",
    "/api/futures/liquidation/aggregated-map",
    "/api/futures/liquidation/aggregated-history",
    "/api/futures/liquidation/max-pain",
    "/api/futures/open-interest/exchange-list",
    "/api/futures/price/history",
    "/api/index/fear-greed-history",
}
PUBLIC_ANALYSIS_GET_PATHS = {
    "/api/markets",
    "/api/assets",
    "/api/candles",
    "/api/analysis/fibonacci",
    "/api/context/radar",
    "/api/memecoins/discover",
    "/api/memecoins/token",
}
PROTECTED_GET_PATHS = {
    "/api/status",
    "/api/tradingview/signals",
    "/api/coinglass/context",
    "/api/quiver/context",
}
PLATFORM_GET_PREFIXES = (
    "/api/coinglass/proxy/",
)
PLATFORM_STATIC_PATHS = {
    "/coinglass-dashboard.html",
    "/dashboard/",
    "/dashboard/index.html",
}
PLATFORM_POST_PATHS = {
    "/api/credentials",
    "/api/spotify-playlist",
    "/api/settings",
    "/api/trading-rules",
    "/api/start",
    "/api/stop",
}


def tradingview_alert_store_path() -> Path:
    configured = os.getenv("MONATISE_TRADINGVIEW_ALERT_STORE", "").strip()
    if configured:
        return Path(configured)
    data_dir = Path(os.getenv("MONATISE_DATA_DIR", "/data" if Path("/data").exists() else "work"))
    return data_dir / "tradingview-alerts.json"


def load_tradingview_alerts(path: Path | None = None) -> list[dict]:
    alert_path = path or tradingview_alert_store_path()
    try:
        payload = json.loads(alert_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    alerts = payload.get("alerts") if isinstance(payload, dict) else payload
    if not isinstance(alerts, list):
        return []
    return [alert for alert in alerts if isinstance(alert, dict)][:TRADINGVIEW_ALERT_LIMIT]


def save_tradingview_alerts(alerts: list[dict], path: Path | None = None) -> None:
    alert_path = path or tradingview_alert_store_path()
    try:
        alert_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"alerts": alerts[:TRADINGVIEW_ALERT_LIMIT], "updatedAt": time.time()}
        alert_path.write_text(json.dumps(payload, cls=JsonEncoder), encoding="utf-8")
    except OSError:
        return


def requires_site_auth(path: str) -> bool:
    return path in PROTECTED_GET_PATHS or path.startswith(PLATFORM_GET_PREFIXES)


def requires_platform_access(path: str) -> bool:
    return requires_site_auth(path)


def _is_email(value: str) -> bool:
    value = value.strip()
    return "@" in value and "." in value.rsplit("@", 1)[-1] and " " not in value


def _normalize_alert_symbol(value: str) -> str:
    raw = str(value).upper().strip()
    if ":" in raw:
        raw = raw.rsplit(":", 1)[-1]
    symbol = "".join(character for character in raw if character.isalnum())
    aliases = {
        "IXIC": "NASDAQ",
        "XAU": "GOLD",
        "XAUUSD": "GOLD",
        "GOLDUSD": "GOLD",
        "XAGUSD": "XAG",
        "SILVER": "XAG",
        "SILVERUSD": "XAG",
    }
    if symbol in aliases:
        return aliases[symbol]
    crypto_bases = {"BTC", "ETH", "SOL", "HYPE", "BNB", "XRP", "DOGE"}
    for quote in ("USDT", "USDC", "USD"):
        if symbol.endswith(quote) and symbol[: -len(quote)] in crypto_bases:
            return symbol[: -len(quote)]
    return symbol[:16]


def _normalize_alert_action(value: str) -> str:
    return TRADINGVIEW_ACTIONS.get(str(value).strip().upper(), "WAIT")


def _tradingview_route(symbol: str) -> str:
    symbol = str(symbol or "").upper().strip()
    if symbol in METALS_WATCHLIST:
        return "metals and commodities primary signal feed"
    if _is_forex_symbol(symbol):
        return "forex primary signal feed"
    if symbol in STOCK_WATCHLIST:
        return "stocks and indices primary signal feed"
    return "crypto confluence feed"


def _is_forex_symbol(symbol: str) -> bool:
    if len(symbol) != 6 or not symbol.isalpha():
        return False
    base = symbol[:3]
    quote = symbol[3:]
    return base in FOREX_QUOTES and quote in FOREX_QUOTES and base != quote


def _float_payload(payload: dict, *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value in {None, ""}:
            continue
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def _normalize_tradingview_grid(payload: dict) -> list[dict]:
    raw = payload.get("grid") or payload.get("levels") or payload.get("orders")
    levels: list[dict] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw[:12]):
            if isinstance(item, dict):
                price = _float_payload(item, "price", "level", "entry")
                side = str(item.get("side") or item.get("action") or "").strip().lower()
                label = str(item.get("label") or item.get("level_id") or f"tv-{index + 1}").strip()[:32]
            else:
                price = None
                side = ""
                label = f"tv-{index + 1}"
                try:
                    price = float(str(item).replace(",", ""))
                except (TypeError, ValueError):
                    pass
            if price is None or price <= 0:
                continue
            levels.append({"label": label, "price": price, "side": "sell" if side.startswith("s") else "buy"})
    elif isinstance(raw, str):
        for index, part in enumerate(raw.replace("|", ",").split(",")[:12]):
            item = part.strip()
            if not item:
                continue
            side = "sell" if item.lower().startswith(("sell", "short", "resistance")) else "buy"
            number = "".join(character for character in item if character.isdigit() or character in ".-")
            try:
                price = float(number)
            except ValueError:
                continue
            if price > 0:
                levels.append({"label": f"tv-{index + 1}", "price": price, "side": side})
    return levels


def _indicator_bias_value(value: str) -> int:
    text = str(value or "").lower()
    if not text or text in {"0", "none", "neutral", "wait", "n/a", "na"}:
        return 0
    bearish_terms = ("sell", "short", "bear", "bearish", "down", "below", "resistance", "reject", "lower", "cross down", "supply")
    bullish_terms = ("buy", "long", "bull", "bullish", "up", "above", "support", "reclaim", "higher", "cross up", "demand")
    if any(term in text for term in bearish_terms):
        return -1
    if any(term in text for term in bullish_terms):
        return 1
    return 0


def classify_tradingview_alert(alert: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    action = str(alert.get("action") or "WAIT").upper()
    try:
        confidence = max(0.0, min(100.0, float(alert.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    received_at = float(alert.get("receivedAt") or 0)
    age_seconds = max(0, int(now - received_at)) if received_at else None
    fresh = received_at > 0 and age_seconds is not None and age_seconds <= TRADINGVIEW_FRESH_SECONDS
    indicators = alert.get("indicators") if isinstance(alert.get("indicators"), dict) else {}
    indicator_score = sum(_indicator_bias_value(value) for value in indicators.values())
    indicator_bias = "BUY" if indicator_score > 0 else "SELL" if indicator_score < 0 else "WAIT"
    if action in {"BUY", "SELL"} and indicator_bias in {"BUY", "SELL"}:
        agreement = "confirming" if action == indicator_bias else "conflicting"
    elif action in {"BUY", "SELL"}:
        agreement = "candidate"
    elif indicator_bias in {"BUY", "SELL"}:
        agreement = "indicator-watch"
    else:
        agreement = "informational"
    if not fresh:
        state = "stale"
    elif agreement == "conflicting":
        state = "conflict-watch"
    elif action in {"BUY", "SELL"} and confidence >= 70:
        state = "confirming"
    elif action in {"BUY", "SELL"} and confidence >= 50:
        state = "candidate"
    else:
        state = "watch"
    lock_start = int(received_at) if received_at else int(now)
    return {
        "role": "tradingview_primary_signal",
        "route": _tradingview_route(str(alert.get("symbol") or "")),
        "state": state,
        "fresh": fresh,
        "ageSeconds": age_seconds,
        "agreement": agreement,
        "action": action,
        "confidence": confidence,
        "indicatorBias": indicator_bias,
        "indicatorScore": indicator_score,
        "indicatorCount": len(indicators),
        "snapshotWindow": {
            "lockSeconds": TRADINGVIEW_SNAPSHOT_LOCK_SECONDS,
            "fastCheckSeconds": TRADINGVIEW_FRESH_SECONDS,
            "startedAt": lock_start,
            "fastReassessAt": lock_start + TRADINGVIEW_FRESH_SECONDS,
            "reassessAt": lock_start + TRADINGVIEW_SNAPSHOT_LOCK_SECONDS,
        },
        "executionAllowed": False,
        "executionNote": "TradingView is the primary signal feed here; Monatise still keeps execution behind risk and snapshot gates.",
    }


def _normalize_indicator_payload(payload: dict) -> dict:
    indicator_keys = {
        "luxalgo",
        "historical_color",
        "liquidity_swings",
        "wick_extremity",
        "equal_highs_lows",
        "liquidity_grabs",
        "dynamic_trend_pivot",
        "auto_fib",
        "daily_vwap",
        "volume_profile",
        "htf_levels",
        "rsi_sma_cross",
    }
    raw = payload.get("indicators")
    indicators = raw if isinstance(raw, dict) else {}
    normalized = {
        str(key).strip().lower(): str(value).strip()[:80]
        for key, value in indicators.items()
        if str(key).strip()
    }
    for key in indicator_keys:
        if key in payload:
            normalized[key] = str(payload.get(key, "")).strip()[:80]
    return normalized


def normalize_tradingview_alert(payload: dict | str) -> dict:
    if isinstance(payload, str):
        raw = payload.strip()
        payload = {"message": raw}
        parts = [part.strip() for part in raw.replace("|", ",").split(",") if part.strip()]
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                payload[key.strip().lower()] = value.strip()
        if "symbol" not in payload and parts:
            payload["symbol"] = parts[0]
        if "action" not in payload and len(parts) > 1:
            payload["action"] = parts[1]
    symbol = _normalize_alert_symbol(str(payload.get("symbol") or payload.get("ticker") or payload.get("pair") or ""))
    action = _normalize_alert_action(str(payload.get("action") or payload.get("signal") or payload.get("bias") or "WAIT"))
    try:
        confidence = max(0.0, min(100.0, float(payload.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "symbol": symbol or "UNKNOWN",
        "action": action,
        "confidence": confidence,
        "timeframe": str(payload.get("timeframe") or payload.get("interval") or "").strip()[:24],
        "indicator": str(payload.get("indicator") or payload.get("strategy") or "TradingView").strip()[:64],
        "indicators": _normalize_indicator_payload(payload),
        "price": str(payload.get("price") or payload.get("close") or "").strip()[:32],
        "priceValue": _float_payload(payload, "price", "close", "mark"),
        "setup": {
            "entry": _float_payload(payload, "entry", "entryPrice", "plannedEntry"),
            "stop": _float_payload(payload, "stop", "stopLoss", "sl", "invalidation"),
            "targetOne": _float_payload(payload, "target1", "targetOne", "tp1", "target"),
            "targetTwo": _float_payload(payload, "target2", "targetTwo", "tp2"),
            "trigger": str(payload.get("trigger") or "").strip()[:120],
            "thesis": str(payload.get("thesis") or payload.get("setup") or "").strip()[:240],
        },
        "grid": _normalize_tradingview_grid(payload),
        "hedge": {
            "side": str(payload.get("hedgeSide") or payload.get("hedge_side") or "").strip().upper()[:12],
            "ratio": _float_payload(payload, "hedgeRatio", "hedge_ratio", "hedgePct", "hedgePercent"),
            "trigger": _float_payload(payload, "hedgeTrigger", "hedge_trigger"),
            "release": _float_payload(payload, "hedgeRelease", "hedge_release"),
            "hardExit": _float_payload(payload, "hedgeHardExit", "hedge_hard_exit", "hardExit"),
            "note": str(payload.get("hedgeNote") or payload.get("hedge_note") or "").strip()[:180],
        },
        "message": str(payload.get("message") or payload.get("note") or "").strip()[:240],
        "receivedAt": time.time(),
    }


def enrich_tradingview_alert(alert: dict, now: float | None = None) -> dict:
    enriched = dict(alert)
    enriched["classification"] = classify_tradingview_alert(enriched, now=now)
    return enriched


def operator_status_payload(config: RuntimeConfig) -> dict:
    smtp_provider = os.getenv("MONATISE_SMTP_PROVIDER", "").strip().lower()
    smtp_host_configured = bool(os.getenv("MONATISE_SMTP_HOST", "").strip())
    smtp_from_configured = bool(os.getenv("MONATISE_SMTP_FROM", "").strip())
    smtp_password_configured = bool(os.getenv("MONATISE_SMTP_PASSWORD", "").strip())
    smtp_configured = smtp_from_configured and (smtp_host_configured or smtp_provider in {"resend", "postmark"})
    if smtp_configured and smtp_provider in {"resend", "postmark"}:
        smtp_configured = smtp_password_configured
    return {
        "ok": True,
        "service": "monatise-live",
        "mode": config.mode,
        "network": config.network,
        "executionMode": config.execution_mode,
        "exchange": config.exchange,
        "publicUrl": os.getenv("MONATISE_PUBLIC_URL", ""),
        "deploy": {
            "commit": os.getenv("RENDER_GIT_COMMIT", os.getenv("MONATISE_GIT_COMMIT", "")),
            "serviceId": os.getenv("RENDER_SERVICE_ID", ""),
            "instanceId": os.getenv("RENDER_INSTANCE_ID", ""),
        },
        "integrations": {
            "coinglass": {
                "configured": bool(os.getenv("COINGLASS_API_KEY", "").strip()),
                "exchange": os.getenv("COINGLASS_EXCHANGE", "Binance"),
            },
            "tradingView": {
                "configured": bool(config.tradingview_webhook_token),
            },
            "quiver": {
                "configured": bool(os.getenv("QUIVER_API_KEY", "").strip()),
                "role": "stock and ETF alternative-data context",
            },
            "backpack": {
                "configured": bool(os.getenv("BACKPACK_API_KEY", "").strip() and os.getenv("BACKPACK_SECRET_KEY", "").strip()),
                "restBase": os.getenv("BACKPACK_REST_BASE", "https://api.backpack.exchange"),
                "executionEnabled": False,
            },
            "smtp": {
                "configured": smtp_configured,
                "provider": smtp_provider or "generic",
                "alertsConfigured": bool(os.getenv("MONATISE_ALERT_EMAILS", "").strip()),
            },
            "credentialStorage": {
                "encrypted": encryption_key_configured(),
            },
        },
        "riskCaps": {
            "orderQuoteSize": config.order_quote_size,
            "maxOrderNotional": config.max_order_notional,
            "maxTotalNotional": config.max_total_notional,
            "maxPositionValue": config.max_position_value,
            "maxDailyLoss": config.max_daily_loss,
            "maxDailyLossPct": config.max_daily_loss_pct,
            "allowLiveOrders": config.allow_live_orders,
            "liveConfirmation": config.live_confirmation == LIVE_CONFIRMATION,
        },
    }


def _market_data_adapter(config: RuntimeConfig, symbol: str):  # noqa: ANN202
    if config.data_feed == "hyperliquid":
        return HyperliquidAdapter(config), "Hyperliquid candleSnapshot"
    return CoinGlassAdapter(config), "CoinGlass futures price history"


def _market_candles(config: RuntimeConfig, symbol: str, limit: int, interval: str):  # noqa: ANN202
    adapter, source = _market_data_adapter(config, symbol)
    try:
        return adapter.candles(symbol, limit, interval=interval), source
    except (CoinGlassPlanError, RuntimeError) as error:
        if "CoinGlass" not in source:
            raise
        fallback = HyperliquidAdapter(config)
        return fallback.candles(symbol, limit, interval=interval), f"Hyperliquid candleSnapshot (CoinGlass unavailable: {error})"


class TenantServices:
    def __init__(self, base_config: RuntimeConfig, store: UserStore) -> None:
        self.base_config = base_config
        self.store = store
        self._services: dict[int, TradingService] = {}
        self._lock = threading.Lock()

    def service_for_user(self, user: User) -> TradingService:
        with self._lock:
            service = self._services.get(user.id)
            if service is not None:
                return service
            credentials = self.store.credentials_for_user(user.id)
            if credentials is None:
                raise ValueError("save private sync details before starting private sync")
            settings = self.store.settings_for_user(user.id)
            config = replace(
                self.base_config,
                symbol=settings.selected_symbol,
                account_address=credentials.account_address,
                chart_interval=settings.chart_interval,
                signal_session_window=settings.signal_session_window,
                leverage=settings.leverage,
                order_quote_size=settings.order_quote_size,
                max_order_notional=settings.max_order_notional,
                max_total_notional=settings.max_total_notional,
                max_position_value=settings.max_position_value,
                london_commodity_only=False,
                max_daily_loss_pct=settings.max_daily_loss_pct,
                secret_key=credentials.secret_key,
                session_guard_minutes=settings.session_guard_minutes,
                stale_grid_cancel=settings.stale_grid_cancel,
            )
            service = TradingService(config)
            self._services[user.id] = service
            return service

    def reset_user(self, user_id: int) -> None:
        with self._lock:
            service = self._services.pop(user_id, None)
        if service is not None:
            service.stop()


def settings_payload(settings) -> dict:  # noqa: ANN001
    return {
        "chartInterval": settings.chart_interval,
        "signalSessionWindow": settings.signal_session_window,
        "leverage": settings.leverage,
        "orderQuoteSize": settings.order_quote_size,
        "maxOrderNotional": settings.max_order_notional,
        "maxTotalNotional": settings.max_total_notional,
        "maxPositionValue": settings.max_position_value,
        "londonCommodityOnly": False,
        "maxDailyLossPct": settings.max_daily_loss_pct,
        "sessionGuardMinutes": settings.session_guard_minutes,
        "staleGridCancel": settings.stale_grid_cancel,
    }


def user_payload(user: User, settings, store: UserStore) -> dict:  # noqa: ANN001
    return {
        "authenticated": True,
        "username": user.username,
        "clientName": settings.client_name,
        "credentialsConfigured": store.has_credentials(user.id),
        "selectedSymbol": settings.selected_symbol,
        "spotifyPlaylistUrl": settings.spotify_playlist_url,
        "spotifyPlaylistEmbedUrl": settings.spotify_playlist_embed_url,
        "subscription": {
            "plan": settings.subscription_plan,
            "status": settings.subscription_status,
        },
        "tradingRules": settings_payload(settings),
    }


class MarketFeed:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self._adapter: HyperliquidAdapter | None = None
        self._prices: dict[str, float] = {}
        self._all_prices: dict[str, float] = {}
        self._updated_at = 0.0
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            if now - self._updated_at > 2:
                if self._adapter is None:
                    self._adapter = HyperliquidAdapter(self.config)
                self._all_prices = self._adapter.all_prices()
                self._prices = {
                    symbol: self._all_prices[symbol]
                    for symbol in self.config.assets
                    if symbol in self._all_prices
                }
                self._updated_at = now
            return {
                "assets": [
                    {"symbol": symbol, "price": self._prices.get(symbol)}
                    for symbol in self.config.assets
                ],
                "groups": {
                    "crypto": [
                        {"symbol": symbol, "price": self._prices.get(symbol), "tradable": symbol in self._prices}
                        for symbol in self.config.assets
                    ],
                    "builder": [],
                    "stocks": self._watchlist(STOCK_WATCHLIST),
                },
                "updatedAt": self._updated_at,
            }

    def _watchlist(self, symbols: tuple[str, ...]) -> list[dict]:
        return [
            {"symbol": symbol, "price": self._all_prices.get(symbol), "tradable": symbol in self._all_prices}
            for symbol in symbols
        ]


class MonatiseHandler(SimpleHTTPRequestHandler):
    tenants: TenantServices
    market_feed: MarketFeed
    store: UserStore
    config: RuntimeConfig
    app_dir: Path
    rate_limits: dict[str, list[float]] = {}
    rate_lock = threading.Lock()
    tradingview_alerts: list[dict] = []
    tradingview_alert_store: Path | None = None
    tradingview_lock = threading.Lock()

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, directory=str(self.app_dir), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._json({"ok": True})
            return
        if parsed.path == "/api/operator":
            self._json(operator_status_payload(self.config))
            return
        if parsed.path == "/api/openclaw/status":
            if not self._openclaw_authorized():
                return
            query = parse_qs(parsed.query)
            symbol = _normalize_alert_symbol(str(query.get("symbol", [self.config.symbol])[0]))
            interval = str(query.get("interval", ["1h"])[0]).strip() or "1h"
            try:
                limit = max(50, min(240, int(query.get("limit", ["120"])[0])))
                with self.tradingview_lock:
                    alerts = [
                        enrich_tradingview_alert(alert)
                        for alert in type(self).tradingview_alerts
                        if not symbol or alert.get("symbol") == symbol
                    ][:10]
                payload = {
                    "ok": True,
                    "service": "monatise-live",
                    "access": "openclaw_read_only",
                    "symbol": symbol,
                    "interval": interval,
                    "market": self.market_feed.snapshot(),
                    "tradingView": {"alerts": alerts, "count": len(alerts)},
                    "operator": operator_status_payload(self.config),
                    "capabilities": {
                        "readOnly": True,
                        "liveOrders": False,
                        "configurationWrites": False,
                        "deploymentWrites": False,
                    },
                }
                if symbol == "GOLD":
                    payload.update(
                        {
                            "source": "TradingView webhook alerts",
                            "mark": alerts[0].get("price") if alerts else None,
                            "goldAnalysisIndicators": list(GOLD_ANALYSIS_INDICATORS),
                            "indicator": None,
                            "instruction": "Use the latest locked TradingView Gold setup; no alert means wait.",
                            "analysis": None,
                            "fvg": None,
                        }
                    )
                else:
                    candles, source = _market_candles(self.config, symbol, limit, interval)
                    mark = candles[-1].close
                    indicators = indicator_snapshot(candles)
                    payload.update(
                        {
                            "source": source,
                            "mark": mark,
                            "indicator": indicators.__dict__,
                            "instruction": grid_instruction(indicators),
                            "analysis": analyze_fibonacci(symbol, interval, candles, mark=mark).to_dict(),
                            "fvg": analyze_fvg(symbol, interval, candles, mark=mark).to_dict(),
                        }
                    )
                self._json(payload)
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/":
            self._redirect("/index.html")
            return
        if parsed.path not in PLATFORM_STATIC_PATHS and requires_platform_access(parsed.path):
            if self._require_platform_user() is None:
                return
        elif requires_site_auth(parsed.path):
            if self._require_platform_user() is None:
                return
        if parsed.path == "/api/markets":
            try:
                self._json(self.market_feed.snapshot())
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/api/assets":
            try:
                if self.config.data_feed == "hyperliquid":
                    assets = [{"symbol": symbol, "exchange": "Hyperliquid", "instrument": symbol, "tradable": True} for symbol in self.config.assets]
                    source = "configured Hyperliquid assets"
                else:
                    try:
                        assets = CoinGlassAdapter(self.config).supported_assets()
                        source = "CoinGlass futures exchange pairs"
                    except Exception as error:  # noqa: BLE001
                        assets = [{"symbol": symbol, "exchange": "Hyperliquid", "instrument": symbol, "tradable": True} for symbol in self.config.assets]
                        source = f"configured Hyperliquid assets (CoinGlass unavailable: {error})"
                self._json({"assets": assets, "count": len(assets), "source": source})
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/api/memecoins/discover":
            if self._rate_limited("/api/memecoins"):
                self._error(429, "memecoin radar refresh limit reached; try again shortly")
                return
            query = parse_qs(parsed.query)
            try:
                limit = max(4, min(24, int(query.get("limit", ["12"])[0])))
                self._json(discover_pumpfun(limit))
            except (RuntimeError, ValueError) as error:
                self._error(502, str(error))
            return
        if parsed.path == "/api/memecoins/token":
            if self._rate_limited("/api/memecoins"):
                self._error(429, "memecoin lookup limit reached; try again shortly")
                return
            query = parse_qs(parsed.query)
            address = str(query.get("address", [""])[0]).strip()
            rpc_url = os.getenv("MONATISE_SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com").strip()
            try:
                self._json(inspect_memecoin(address, rpc_url))
            except ValueError as error:
                self._error(400, str(error))
            except RuntimeError as error:
                self._error(502, str(error))
            return
        if parsed.path == "/api/candles":
            query = parse_qs(parsed.query)
            symbol = str(query.get("symbol", [self.config.symbol])[0]).strip().upper()
            interval = str(query.get("interval", ["1h"])[0]).strip() or "1h"
            try:
                limit = max(5, min(240, int(query.get("limit", ["120"])[0])))
                candles, source = _market_candles(self.config, symbol, limit, interval)
                self._json(
                    {
                        "candles": [candle.__dict__ for candle in candles],
                        "interval": interval,
                        "source": source,
                        "symbol": symbol,
                    }
                )
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/api/analysis/fibonacci":
            query = parse_qs(parsed.query)
            symbol = str(query.get("symbol", [self.config.symbol])[0]).strip().upper()
            interval = str(query.get("interval", ["1h"])[0]).strip() or "1h"
            try:
                limit = max(20, min(240, int(query.get("limit", ["120"])[0])))
                candles, source = _market_candles(self.config, symbol, limit, interval)
                mark = candles[-1].close
                if source.startswith("Hyperliquid"):
                    mark = HyperliquidAdapter(self.config).latest_price(symbol)
                self._json(
                    {
                        "analysis": analyze_fibonacci(symbol, interval, candles, mark=mark).to_dict(),
                        "candles": [candle.__dict__ for candle in candles],
                        "fvg": analyze_fvg(symbol, interval, candles, mark=mark).to_dict(),
                        "source": source,
                    }
                )
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/api/context/radar":
            query = parse_qs(parsed.query)
            symbol = str(query.get("symbol", [self.config.symbol])[0]).strip().upper()
            interval = str(query.get("interval", ["1h"])[0]).strip() or "1h"
            try:
                limit = max(50, min(240, int(query.get("limit", ["120"])[0])))
                candles, source = _market_candles(self.config, symbol, limit, interval)
                indicators = indicator_snapshot(candles)
                prices = HyperliquidAdapter(self.config).all_prices()
                instruction = grid_instruction(indicators)
                self._json(
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "source": source,
                        "indicator": indicators.__dict__,
                        "instruction": instruction,
                        "contextAssets": context_assets(symbol, prices),
                        "sources": [
                            {
                                "label": "Hyperliquid candleSnapshot",
                                "url": "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint",
                            },
                            {
                                "label": "EIA Weekly Petroleum Status Report",
                                "url": "https://www.eia.gov/petroleum/supply/weekly/index.php",
                            },
                            {
                                "label": "ICE U.S. Dollar Index",
                                "url": "https://www.ice.com/market-data/indices/currency-indices",
                            },
                            {
                                "label": "CME FedWatch",
                                "url": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
                            },
                        ],
                    }
                )
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path.startswith("/api/coinglass/proxy/"):
            if self._require_platform_user() is None:
                return
            if self._rate_limited("/api/coinglass/proxy"):
                self._error(429, "too many requests")
                return
            proxy_path = "/" + parsed.path.removeprefix("/api/coinglass/proxy/")
            if proxy_path not in COINGLASS_PROXY_PATHS:
                self._error(404, "CoinGlass proxy route is not allowed")
                return
            api_key = (
                self.headers.get("X-CG-API-KEY")
                or self.headers.get("CG-API-KEY")
                or os.getenv("COINGLASS_API_KEY", "")
            ).strip()
            if not api_key:
                self._error(401, "CoinGlass API key is required")
                return
            url = f"{COINGLASS_PROXY_BASE}{proxy_path}"
            if parsed.query:
                url = f"{url}?{parsed.query}"
            request = Request(
                url,
                headers={"accept": "application/json", "CG-API-KEY": api_key},
                method="GET",
            )
            try:
                with urlopen(request, timeout=15) as response:  # noqa: S310
                    body = response.read()
            except HTTPError as error:
                body = error.read() or json.dumps({"message": str(error)}).encode("utf-8")
                self.send_response(error.code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            except (URLError, TimeoutError) as error:
                self._error(502, f"CoinGlass proxy request failed: {error}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/coinglass/context":
            query = parse_qs(parsed.query)
            symbol = str(query.get("symbol", [self.config.symbol])[0]).strip().upper()
            interval = str(query.get("interval", ["1h"])[0]).strip() or "1h"
            try:
                adapter = CoinGlassAdapter(self.config)
                subscription: dict = {}
                unavailable: list[dict] = []
                funding: list[dict] = []
                fear_greed: list[dict] = []
                open_interest: list[dict] = []
                liquidations: list[dict] = []
                try:
                    subscription = adapter.account_subscription()
                except (CoinGlassPlanError, RuntimeError) as error:
                    unavailable.append({"feature": "subscription", "reason": str(error)})
                try:
                    funding = adapter.funding_rate(symbol)
                except (CoinGlassPlanError, RuntimeError) as error:
                    unavailable.append({"feature": "fundingRate", "reason": str(error)})
                try:
                    open_interest = adapter.open_interest(symbol)
                except (CoinGlassPlanError, RuntimeError) as error:
                    unavailable.append({"feature": "openInterest", "reason": str(error)})
                try:
                    liquidations = adapter.liquidation_history(symbol, limit=24, interval=interval)
                except (CoinGlassPlanError, RuntimeError) as error:
                    unavailable.append({"feature": "liquidations", "reason": str(error)})
                try:
                    fear_greed = adapter.fear_greed()
                except (CoinGlassPlanError, RuntimeError) as error:
                    unavailable.append({"feature": "fearGreed", "reason": str(error)})
                self._json(
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "source": "CoinGlass",
                        "subscription": subscription,
                        "available": not unavailable,
                        "unavailable": unavailable,
                        "fundingRate": funding,
                        "fearGreed": fear_greed,
                        "openInterest": open_interest,
                        "liquidations": liquidations,
                    }
                )
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/api/quiver/context":
            query = parse_qs(parsed.query)
            symbol = normalize_quiver_symbol(str(query.get("symbol", [self.config.symbol])[0]))
            try:
                adapter = QuiverAdapter.from_env()
                self._json(adapter.context(symbol))
            except Exception as error:  # noqa: BLE001
                self._error(502, str(error))
            return
        if parsed.path == "/api/tradingview/signals":
            if self._require_platform_user() is None:
                return
            query = parse_qs(parsed.query)
            symbol = _normalize_alert_symbol(str(query.get("symbol", [""])[0]))
            with self.tradingview_lock:
                alerts = list(type(self).tradingview_alerts)
            if symbol:
                alerts = [alert for alert in alerts if alert.get("symbol") == symbol]
            enriched_alerts = [enrich_tradingview_alert(alert) for alert in alerts[:20]]
            self._json(
                {
                    "configured": bool(self.config.tradingview_webhook_token),
                    "alerts": enriched_alerts,
                    "count": len(alerts),
                    "source": "TradingView webhook alerts",
                    "role": "tradingview_primary_signal",
                    "snapshotPolicy": {
                        "lockSeconds": TRADINGVIEW_SNAPSHOT_LOCK_SECONDS,
                        "freshSeconds": TRADINGVIEW_FRESH_SECONDS,
                        "fastCheckSeconds": TRADINGVIEW_FRESH_SECONDS,
                    },
                }
            )
            return
        if parsed.path == "/api/me":
            user = self._current_user()
            if user is None:
                self._json({"authenticated": False, "credentialsConfigured": False})
                return
            self.store.touch_seen(user.id, user.username, self._client_ip())
            settings = self.store.settings_for_user(user.id)
            self._json(user_payload(user, settings, self.store))
            return
        if parsed.path == "/api/status":
            user = self._require_user()
            if user is None:
                return
            try:
                service = self.tenants.service_for_user(user)
                self._json(service.snapshot())
            except ValueError as error:
                self._json(
                    {
                        "running": False,
                        "mode": self.tenants.base_config.mode,
                        "network": self.tenants.base_config.network,
                        "symbol": self.store.settings_for_user(user.id).selected_symbol,
                        "riskStatus": str(error),
                        "requires": ["Private sync details"],
                        "events": [{"timestamp": 0, "level": "warn", "message": str(error)}],
                    }
                )
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        public_post_paths = {"/api/tradingview/webhook"}
        if parsed.path not in public_post_paths and not self._valid_request_origin():
            self._error(403, "invalid request origin")
            return
        if self._rate_limited(parsed.path):
            self._error(429, "too many requests")
            return
        if parsed.path == "/api/tradingview/webhook":
            query = parse_qs(parsed.query)
            token = str(query.get("token", [""])[0])
            if not self.config.tradingview_webhook_token:
                self._error(503, "TradingView webhook token is not configured")
                return
            if token != self.config.tradingview_webhook_token:
                self._error(401, "invalid TradingView webhook token")
                return
            body = self._read_body()
            try:
                payload: dict | str = json.loads(body.decode("utf-8")) if body else {}
            except json.JSONDecodeError:
                payload = body.decode("utf-8", errors="replace")
            alert = normalize_tradingview_alert(payload)
            enriched_alert = enrich_tradingview_alert(alert)
            with self.tradingview_lock:
                type(self).tradingview_alerts = [alert, *type(self).tradingview_alerts[: TRADINGVIEW_ALERT_LIMIT - 1]]
                save_tradingview_alerts(type(self).tradingview_alerts, type(self).tradingview_alert_store)
            email_recipients = 0
            email_error = ""
            try:
                email_recipients = send_trading_alert_email(alert)
            except EmailDeliveryError as error:
                email_error = str(error)
            response = {"accepted": True, "alert": enriched_alert, "emailRecipients": email_recipients}
            if email_error:
                response["emailError"] = email_error
            self._json(response)
            return
        if parsed.path == "/api/register":
            payload = self._read_json()
            try:
                user = self.store.create_user(str(payload.get("username", "")), str(payload.get("password", "")))
                client_name = str(payload.get("clientName", "")).strip()
                if client_name:
                    settings = self.store.save_client_name(user.id, client_name)
                else:
                    settings = self.store.settings_for_user(user.id)
                self.store.record_login(user.id, user.username, self._client_ip())
                self._create_login_session(user.id, remember_device=bool(payload.get("rememberDevice")))
                self._json(user_payload(user, settings, self.store))
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/login":
            payload = self._read_json()
            user = self.store.authenticate(str(payload.get("username", "")), str(payload.get("password", "")))
            if user is None:
                self._error(401, "invalid username or password")
                return
            self.store.record_login(user.id, user.username, self._client_ip())
            self._create_login_session(user.id, remember_device=bool(payload.get("rememberDevice")))
            settings = self.store.settings_for_user(user.id)
            self._json(user_payload(user, settings, self.store))
            return
        if parsed.path == "/api/login-code/request":
            payload = self._read_json()
            username = str(payload.get("username", "")).strip().lower()
            if not _is_email(username):
                self._error(400, "enter the email used for this profile")
                return
            code = self.store.create_login_code(username)
            response = {"message": "If that email exists, a login code has been sent."}
            if code is not None:
                try:
                    send_login_code(code.user.username, code.code)
                except EmailDeliveryError as error:
                    if not expose_dev_reset_code():
                        response["emailUnavailable"] = True
                        response["message"] = (
                            "Email delivery is not available for this address right now. "
                            "Use password login, or use the verified test email on the SMTP account."
                        )
                    else:
                        response["devLoginCode"] = code.code
                else:
                    response["emailUnavailable"] = False
                if expose_dev_reset_code():
                    response["devLoginCode"] = code.code
            self._json(response)
            return
        if parsed.path == "/api/login-code/complete":
            payload = self._read_json()
            user = self.store.authenticate_login_code(str(payload.get("username", "")), str(payload.get("loginCode", "")))
            if user is None:
                self._error(400, "login code is invalid or expired")
                return
            self.store.record_login(user.id, user.username, self._client_ip())
            self._create_login_session(user.id, remember_device=bool(payload.get("rememberDevice")))
            settings = self.store.settings_for_user(user.id)
            self._json(user_payload(user, settings, self.store))
            return
        if parsed.path == "/api/password-reset/request":
            payload = self._read_json()
            username = str(payload.get("username", "")).strip().lower()
            if not _is_email(username):
                self._error(400, "enter the email used for this profile")
                return
            reset = self.store.create_password_reset_code(username)
            response = {"message": "If that email exists, a reset code has been sent."}
            if reset is not None:
                try:
                    send_password_reset_code(reset.user.username, reset.code)
                except EmailDeliveryError as error:
                    if not expose_dev_reset_code():
                        response["emailUnavailable"] = True
                        response["message"] = (
                            "Password reset email delivery is not available for this address right now. "
                            "Use password login, or use the verified test email on the SMTP account."
                        )
                    else:
                        response["devResetCode"] = reset.code
                else:
                    response["emailUnavailable"] = False
                if expose_dev_reset_code():
                    response["devResetCode"] = reset.code
            self._json(response)
            return
        if parsed.path == "/api/password-reset/complete":
            payload = self._read_json()
            try:
                user = self.store.reset_password_with_code(
                    str(payload.get("username", "")),
                    str(payload.get("resetCode", "")),
                    str(payload.get("password", "")),
                )
            except ValueError as error:
                self._error(400, str(error))
                return
            if user is None:
                self._error(400, "reset code is invalid or expired")
                return
            self.tenants.reset_user(user.id)
            self._create_login_session(user.id, remember_device=True)
            settings = self.store.settings_for_user(user.id)
            self._json(user_payload(user, settings, self.store))
            return
        if parsed.path == "/api/password-recovery-code":
            self._error(410, "saved recovery codes have been replaced by email reset codes")
            return
        if parsed.path == "/api/logout":
            token = self._session_token()
            if token:
                self.store.delete_session(token)
            self._clear_session_cookie()
            self._json({"authenticated": False})
            return
        if parsed.path in PLATFORM_POST_PATHS:
            if self._require_user() is None:
                return
        if parsed.path == "/api/credentials":
            user = self._require_user()
            if user is None:
                return
            payload = self._read_json()
            try:
                self.store.save_credentials(
                    user.id,
                    UserCredentials(
                        account_address=str(payload.get("accountAddress", "")),
                        secret_key=str(payload.get("secretKey", "")),
                    ),
                )
                self.tenants.reset_user(user.id)
                self._json({"credentialsConfigured": True})
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/profile":
            user = self._require_user()
            if user is None:
                return
            payload = self._read_json()
            try:
                settings = self.store.save_client_name(user.id, str(payload.get("clientName", "")))
                self._json(user_payload(user, settings, self.store))
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/spotify-playlist":
            user = self._require_user()
            if user is None:
                return
            payload = self._read_json()
            try:
                settings = self.store.save_spotify_playlist(user.id, str(payload.get("spotifyPlaylistUrl", "")))
                self._json(user_payload(user, settings, self.store))
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/settings":
            user = self._require_user()
            if user is None:
                return
            payload = self._read_json()
            try:
                settings = self.store.save_selected_symbol(user.id, str(payload.get("selectedSymbol", "")))
                self.tenants.reset_user(user.id)
                self._json(
                    {
                        "selectedSymbol": settings.selected_symbol,
                        "subscription": {
                            "plan": settings.subscription_plan,
                            "status": settings.subscription_status,
                        },
                        "tradingRules": settings_payload(settings),
                    }
                )
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/trading-rules":
            user = self._require_user()
            if user is None:
                return
            payload = self._read_json()
            try:
                settings = self.store.save_trading_rules(
                    user.id,
                    chart_interval=str(payload.get("chartInterval", "")),
                    signal_session_window=str(payload.get("signalSessionWindow", "always")),
                    london_commodity_only=False,
                    max_daily_loss_pct=float(payload.get("maxDailyLossPct", 0.05)),
                    session_guard_minutes=int(payload.get("sessionGuardMinutes", 60)),
                    stale_grid_cancel=bool(payload.get("staleGridCancel", True)),
                    order_quote_size=float(payload.get("orderQuoteSize", 25)),
                    max_total_notional=float(payload.get("maxTotalNotional", 5000)),
                    max_position_value=float(payload.get("maxPositionValue", 5000)),
                )
                self.tenants.reset_user(user.id)
                self._json({"tradingRules": settings_payload(settings)})
            except (TypeError, ValueError) as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/start":
            user = self._require_user()
            if user is None:
                return
            try:
                self._json(self.tenants.service_for_user(user).start())
            except ValueError as error:
                self._error(400, str(error))
            return
        if parsed.path == "/api/stop":
            user = self._require_user()
            if user is None:
                return
            try:
                self._json(self.tenants.service_for_user(user).stop())
            except ValueError as error:
                self._error(400, str(error))
            return
        self.send_error(404, "not found")

    def _read_json(self) -> dict:
        data = self._read_body()
        if not data:
            return {}
        return json.loads(data.decode("utf-8"))

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _current_user(self) -> User | None:
        return self.store.user_for_session(self._session_token())

    def _require_user(self) -> User | None:
        user = self._current_user()
        if user is None:
            self._error(401, "authentication required")
        return user

    def _require_platform_user(self) -> User | None:
        return self._require_user()

    def _openclaw_authorized(self) -> bool:
        expected = secret_value("MONATISE_OPENCLAW_TOKEN", "").strip()
        if not expected:
            self._error(503, "OpenClaw read-only integration is not configured")
            return False
        scheme, _, supplied = self.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(supplied.strip(), expected):
            self._error(401, "invalid OpenClaw authorization")
            return False
        return True

    def _session_token(self) -> str:
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "monatise_session":
                return value
        return ""

    def _create_login_session(self, user_id: int, *, remember_device: bool = False) -> None:
        max_age = REMEMBERED_SESSION_SECONDS if remember_device else SESSION_SECONDS
        self._set_session_cookie(self.store.create_session(user_id, ttl_seconds=max_age), max_age=max_age)

    def _set_session_cookie(self, token: str, *, max_age: int = SESSION_SECONDS) -> None:
        self._pending_cookie = (
            f"monatise_session={token}; Path=/; Max-Age={int(max_age)}; SameSite=Lax; HttpOnly{self._secure_cookie_suffix()}"
        )

    def _clear_session_cookie(self) -> None:
        self._pending_cookie = f"monatise_session=; Path=/; Max-Age=0; SameSite=Lax; HttpOnly{self._secure_cookie_suffix()}"

    def _secure_cookie_suffix(self) -> str:
        public_url = os.getenv("MONATISE_PUBLIC_URL", "")
        if public_url.startswith("https://") or os.getenv("MONATISE_SECURE_COOKIES", "").lower() == "true":
            return "; Secure"
        return ""

    def end_headers(self) -> None:
        static_path = urlparse(self.path).path
        if static_path in {"/", "/index.html", "/coinglass-dashboard.html", "/sw.js"}:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://cdnjs.cloudflare.com https://cdn.ably.com; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self' https://open-api-v4.coinglass.com https://api.binance.com https://api.hyperliquid.xyz https://api.alternative.me https://postgresql.org https://www.postgresql.org https://rest.ably.io https://realtime.ably.io wss://realtime.ably.io wss://*.ably.io https://api.elevenlabs.io https://api.openai.com; "
            "media-src 'self' blob: data:; "
            "frame-src 'self' https://s.tradingview.com https://www.tradingview.com https://open.spotify.com; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        if os.getenv("MONATISE_PUBLIC_URL", "").startswith("https://"):
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        super().end_headers()

    def _json(self, payload: dict) -> None:
        self._json_status(200, payload)

    def _json_status(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, cls=JsonEncoder).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if hasattr(self, "_pending_cookie"):
            self.send_header("Set-Cookie", self._pending_cookie)
            delattr(self, "_pending_cookie")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if hasattr(self, "_pending_cookie"):
            self.send_header("Set-Cookie", self._pending_cookie)
            delattr(self, "_pending_cookie")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _valid_request_origin(self) -> bool:
        origin = self.headers.get("Origin") or self.headers.get("Referer")
        if not origin:
            return True
        origin_host = urlparse(origin).netloc
        if not origin_host:
            return False
        allowed_hosts = {
            self.headers.get("Host", ""),
            self.headers.get("X-Forwarded-Host", ""),
            urlparse(os.getenv("MONATISE_PUBLIC_URL", "")).netloc,
        }
        return origin_host in {host for host in allowed_hosts if host}

    def _rate_limited(self, path: str) -> bool:
        limits = {
            "/api/login": (10, 60),
            "/api/login-code/request": (4, 60),
            "/api/login-code/complete": (8, 60),
            "/api/register": (6, 60),
            "/api/password-reset/request": (4, 60),
            "/api/password-reset/complete": (8, 60),
            "/api/password-recovery-code": (3, 60),
            "/api/credentials": (6, 60),
            "/api/start": (6, 60),
            "/api/stop": (12, 60),
            "/api/tradingview/webhook": (120, 60),
            "/api/coinglass/proxy": (60, 60),
            "/api/memecoins": (30, 60),
        }
        limit, window = limits.get(path, (60, 60))
        client = self._client_ip()
        key = f"{client}:{path}"
        now = time.time()
        with self.rate_lock:
            attempts = [stamp for stamp in self.rate_limits.get(key, []) if now - stamp < window]
            if len(attempts) >= limit:
                self.rate_limits[key] = attempts
                return True
            attempts.append(now)
            self.rate_limits[key] = attempts
        return False

    def _client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        return forwarded.split(",", 1)[0].strip() or self.client_address[0]


def main() -> int:
    config = RuntimeConfig.from_env()
    if config.mode == "live" and config.network == "mainnet" and not encryption_key_configured():
        raise RuntimeError("MONATISE_ENCRYPTION_KEY is required for live mainnet credential storage")
    store = UserStore()
    tenants = TenantServices(config, store)
    market_feed = MarketFeed(replace(config, account_address="", secret_key=""))
    app_dir = Path(__file__).resolve().parents[2] / "app"

    class Handler(MonatiseHandler):
        pass

    Handler.store = store
    Handler.tenants = tenants
    Handler.market_feed = market_feed
    Handler.config = config
    Handler.app_dir = app_dir
    Handler.tradingview_alert_store = tradingview_alert_store_path()
    Handler.tradingview_alerts = load_tradingview_alerts(Handler.tradingview_alert_store)

    port = int(os.getenv("MONATISE_PORT", os.getenv("PORT", "4174")))
    host = os.getenv("MONATISE_HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Monatise backend running at http://{host}:{port}", flush=True)
    print(f"mode={config.mode} network={config.network} multi_user=true", flush=True)
    print(f"auth_db={store.path}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
