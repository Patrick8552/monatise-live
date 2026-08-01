from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MacroRule:
    factor: str
    weight: float
    bullish_when_positive: bool = True
    minimum_magnitude: float = 0.0

    def contribution(self, value: float | None) -> float | None:
        if value is None:
            return None
        if abs(value) < self.minimum_magnitude:
            return 0.0
        direction = 1.0 if self.bullish_when_positive else -1.0
        normalized = max(-1.0, min(1.0, value * direction))
        return normalized * self.weight


CRYPTO_MACRO_RULES: tuple[MacroRule, ...] = (
    MacroRule("dxy_change_pct", 0.90, bullish_when_positive=False),
    MacroRule("us10y_change_bps", 0.55, bullish_when_positive=False),
    MacroRule("real_yield_change_bps", 0.65, bullish_when_positive=False),
    MacroRule("vix_change_pct", 0.65, bullish_when_positive=False),
    MacroRule("nasdaq_change_pct", 0.70, bullish_when_positive=True),
    MacroRule("sp500_change_pct", 0.45, bullish_when_positive=True),
    MacroRule("usd_liquidity_score", 1.10, bullish_when_positive=True),
    MacroRule("risk_sentiment_score", 0.90, bullish_when_positive=True),
    MacroRule("stablecoin_market_cap_change_pct", 1.00, bullish_when_positive=True),
    MacroRule("stablecoin_exchange_inflow_score", 0.80, bullish_when_positive=True),
    MacroRule("btc_etf_flow_score", 1.10, bullish_when_positive=True),
    MacroRule("eth_etf_flow_score", 0.75, bullish_when_positive=True),
    MacroRule("crypto_funding_environment_score", 0.60, bullish_when_positive=True),
    MacroRule("crypto_open_interest_change_pct", 0.35, bullish_when_positive=True),
    MacroRule("total_crypto_market_cap_change_pct", 0.95, bullish_when_positive=True),
)
