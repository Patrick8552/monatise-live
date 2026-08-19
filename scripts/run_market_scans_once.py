"""Run one production stock-universe and CME scan using the normal safety gates."""

from __future__ import annotations

import asyncio
import json
import os

from redis.asyncio import Redis

from monatise.application.deployment import OrchestrationRuntime, TelegramNotificationTransport, _true
from monatise.application.flashalpha_analysis import FLASHALPHA_FUTURES_SYMBOLS
from monatise.application.stock_universe import StockUniverseConfiguration
from monatise.application.workflows import TelegramNotifier


def stock_configuration() -> StockUniverseConfiguration:
    return StockUniverseConfiguration(
        minimum_price=max(0.01, float(os.getenv("MONATISE_STOCK_MIN_PRICE", "5"))),
        maximum_spread_bps=max(1.0, float(os.getenv("MONATISE_STOCK_MAX_SPREAD_BPS", "80"))),
        minimum_daily_dollar_volume=max(0.0, float(os.getenv("MONATISE_STOCK_MIN_DOLLAR_VOLUME", "5000000"))),
        maximum_universe_size=max(0, int(os.getenv("MONATISE_STOCK_UNIVERSE_MAX", "0"))),
        include_leveraged=_true(os.getenv("MONATISE_STOCK_INCLUDE_LEVERAGED", "false")),
        shortlist_per_side=max(1, int(os.getenv("MONATISE_STOCK_SHORTLIST_PER_SIDE", "5"))),
        minimum_score=max(1, int(os.getenv("MONATISE_STOCK_MINIMUM_SCORE", "7"))),
        minimum_reward_risk=max(1.0, float(os.getenv("MONATISE_STOCK_MINIMUM_REWARD_RISK", "1.5"))),
    )


async def main() -> None:
    redis_url = os.getenv("MONATISE_REDIS_URL") or os.getenv("REDIS_URL")
    token, chat_id = os.getenv("MONATISE_TELEGRAM_BOT_TOKEN"), os.getenv("MONATISE_TELEGRAM_CHAT_ID")
    if not redis_url or not token or not chat_id:
        raise RuntimeError("Redis and Telegram production configuration are required")
    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.environment = dict(os.environ)
    runtime.redis = Redis.from_url(redis_url, decode_responses=True)
    runtime.telegram = TelegramNotifier(TelegramNotificationTransport(lambda: token), chat_id)
    namespace = os.getenv("MONATISE_REDIS_NAMESPACE", "monatise:production-analysis")
    try:
        stock = await runtime._run_stock_universe_scan(
            stock_configuration(), max(300, int(os.getenv("MONATISE_STOCK_SCAN_COOLDOWN_SECONDS", "21600"))), namespace
        )
        futures = await runtime._analyze_flashalpha_futures(
            tuple(part.strip().upper().removesuffix("=F") for part in os.getenv("MONATISE_FLASHALPHA_FUTURES_SYMBOLS", ",".join(FLASHALPHA_FUTURES_SYMBOLS)).split(",") if part.strip()),
            max(300, int(os.getenv("MONATISE_FLASHALPHA_FUTURES_SCAN_COOLDOWN_SECONDS", "3600"))), namespace,
        )
        print(json.dumps({"stock_scan": stock, "cme_scan": futures}, sort_keys=True))
    finally:
        await runtime.redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
