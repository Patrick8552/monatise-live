from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


TESTS = {
    "tests.test_grid": [
        "test_grid_builds_buy_and_sell_levels_around_center",
        "test_grid_rejects_invalid_spacing",
    ],
    "tests.test_harvester": [
        "test_harvester_plans_affordable_orders",
        "test_harvester_respects_inventory_skew",
        "test_harvester_records_paired_harvest",
    ],
    "tests.test_simulation": [
        "test_backtest_engine_runs_grid_harvest_cycle",
    ],
    "tests.test_fibonacci": [
        "test_fibonacci_analysis_builds_retracements_and_extensions",
    ],
    "tests.test_context": [
        "test_indicator_snapshot_and_instruction_for_range",
        "test_context_assets_for_gold_and_oil",
    ],
    "tests.test_sessions": [
        "test_forex_session_break_guard_flags_one_hour_before_london_close",
        "test_forex_session_break_guard_flags_one_hour_after_london_close",
        "test_forex_session_break_guard_ignores_crypto_symbols",
        "test_commodity_london_guard_blocks_gold_outside_london",
        "test_commodity_london_guard_allows_oil_during_london",
    ],
    "tests.test_hyperliquid_candles": [
        "test_hyperliquid_candle_snapshot_uses_builder_coin_alias",
        "test_parse_candle_and_interval_validation",
    ],
    "tests.test_live_config": [
        "test_live_mode_requires_all_order_gates",
        "test_live_mode_enables_only_with_explicit_confirmation",
        "test_live_mode_dry_run_does_not_enable_order_placement",
        "test_order_size_cannot_exceed_max_order_notional",
        "test_total_notional_defaults_to_trading_capital",
        "test_total_notional_env_override_is_respected",
        "test_env_daily_loss_defaults_to_five_percent_of_quote",
        "test_global_hyperliquid_credentials_are_ignored_by_default",
    ],
    "tests.test_live_service": [
        "test_live_tick_initializes_risk_baseline_from_live_mark",
        "test_live_snapshot_exposes_readiness_checklist",
        "test_client_drawdown_percentage_sets_daily_loss_limit",
        "test_market_shock_guard_blocks_fast_mark_move",
        "test_live_start_blocks_forex_session_break_guard",
        "test_live_start_blocks_gold_outside_london_when_rule_enabled",
        "test_stale_live_grid_cancels_exchange_orders_before_replace",
        "test_live_tick_cancels_orders_during_forex_session_break_guard",
        "test_live_tick_reconciles_exchange_fills_once",
        "test_hyperliquid_order_values_are_rounded_for_wire_format",
        "test_hyperliquid_extracts_exchange_order_id",
    ],
    "tests.test_live_users": [
        "test_user_store_authenticates_and_loads_session_user",
        "test_user_store_encrypts_credentials_per_user",
        "test_user_store_saves_asset_and_subscription_settings",
        "test_user_store_saves_trading_rules_and_gates_one_minute_to_pro",
        "test_user_store_rejects_excessive_drawdown_limit",
    ],
    "tests.test_live_secrets": [
        "test_secret_value_reads_direct_secret_file",
        "test_secret_value_reads_key_value_secret_file",
    ],
    "tests.test_payments": [
        "test_crypto_payment_config_exposes_usdc_networks",
        "test_crypto_checkout_returns_all_usdc_networks",
        "test_crypto_checkout_creates_pending_invoice",
        "test_crypto_watcher_marks_evm_invoice_paid_and_activates_plan",
        "test_crypto_watcher_marks_solana_invoice_paid_and_activates_plan",
    ],
}


def main() -> int:
    count = 0
    for module_name, test_names in TESTS.items():
        module = importlib.import_module(module_name)
        for test_name in test_names:
            getattr(module, test_name)()
            count += 1
    print(f"{count} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
