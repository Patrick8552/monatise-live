"""Canonical live FTMO risk policy shared by analysis and execution."""

from __future__ import annotations

from decimal import Decimal


MAX_RISK_FRACTION_PER_TRADE = Decimal("0.03")
MAX_RISK_PERCENT_PER_TRADE = Decimal("3.0")


def risk_ceiling(equity: Decimal) -> Decimal:
    """Return the percentage-only per-trade ceiling for current equity."""
    return equity * MAX_RISK_FRACTION_PER_TRADE
