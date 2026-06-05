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
    "tests.test_live_config": [
        "test_live_mode_requires_all_order_gates",
        "test_live_mode_enables_only_with_explicit_confirmation",
        "test_order_size_cannot_exceed_max_order_notional",
    ],
    "tests.test_live_service": [
        "test_live_tick_initializes_risk_baseline_from_live_mark",
        "test_hyperliquid_order_values_are_rounded_for_wire_format",
    ],
    "tests.test_live_server": [
        "test_live_server_requires_control_token_for_status",
    ],
    "tests.test_live_secrets": [
        "test_secret_value_reads_direct_secret_file",
        "test_secret_value_reads_key_value_secret_file",
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
