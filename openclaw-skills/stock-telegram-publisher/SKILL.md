---
name: stock-telegram-publisher
description: Publish completed Monatise Quiver-backed stock and ETF analysis alerts to an authorized Telegram chat. Use for private Telegram stock commands and scheduled stock watch notifications.
---
# Stock Telegram Publisher

Authenticate the user and chat allowlist, rate-limit requests, and route `/stock SYMBOL` through `stock-asset-router`. Publish `BUY_WATCH`, `SELL_WATCH`, and `NO_TRADE` results exactly once. Label every message analysis-only. Never publish secrets, invent price levels, or place an order.
