---
name: stock-asset-router
description: Route Monatise stock and ETF analysis requests through the protected OpenClaw bridge, validate Quiver-backed results, and produce Telegram-ready analysis-only alerts. Use for AAPL, TSLA, NVDA, QQQ, or SPY stock analysis and alert requests.
---
# Stock Asset Router

Run `python3 {baseDir}/scripts/analyze_stock.py SYMBOL --format telegram`. Return its result verbatim. Reject unsupported symbols. Treat `BUY_WATCH` and `SELL_WATCH` as research alerts, not orders. Never invent prices, entries, stops, or targets; Quiver supplies alternative-data context, not execution geometry. Never place an order or expose credentials.
