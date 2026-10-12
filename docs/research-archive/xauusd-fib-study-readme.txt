Monatise XAU/USD Fibonacci extension study — prepared 7 October 2026

Status: protocol and empty observation ledger prepared. No historical or forward performance run has occurred. No orders, production settings, trade notifications or automations were created.

Question: measure 1.618, 2.0 and 2.618 on identical qualifying setups with identical frozen anchors. Report target-first outcomes, time, uncertainty, actual R expectancy and censoring. A nearer target's higher touch rate does not alone make it better.

Tools required:
1. Read-only MT5 historical XAU/USD candles and Bid/Ask tick export from the intended broker, with instrument specifications and coverage/error logs.
2. Reviewed historical broker calendar and UTC-offset/DST mapping.
3. Frozen canonical GitHub engine at 0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18.
4. Isolated Python 3.11+ research environment, pytest, causal Gold replay runner, numerical/statistical reporting and plots.
5. Immutable data manifest/hashes and the supplied observation ledger.
6. Optional TradingView replay for visual cross-checking; screenshots do not establish executable-price outcomes.

Monatise provides the Fib engine and BrokerCandleService. Its current history request returns at most 240 bars per interval, so it is not a replacement for a paginated multi-month archive. The existing backtest_grid_spacing.py is BTC-specific and is not a Gold Fib comparison runner.

Read-only source checks:
https://github.com/Patrick8552/monatise-live/blob/0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18/docs/xauusd-operator-release.md
https://github.com/Patrick8552/monatise-live/blob/0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18/monatise/application/hierarchy/broker_candles.py
https://www.mql5.com/en/docs/series/copyticksrange

Next implementation step: verify available broker history and calendar, then build and validate the separate causal replay runner. Missing canonical admission evidence restricts a run to an explicitly labelled anchor-only observation study. No evidence gate is relaxed.

Important distinction: setup expiry limits entry eligibility. It does not automatically close an already filled virtual position. Post-entry strategy management and any preregistered research deadline are separate.

No paid provider purchase is needed to prepare this technical-only study. GC/options data are required only if a separately selected canonical policy depends on them. No claim is made about current broker connectivity or data completeness.
