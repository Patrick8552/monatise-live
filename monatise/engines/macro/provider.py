from __future__ import annotations

from typing import Protocol

from monatise.engines.macro.models import MacroEvent


class MacroDataPort(Protocol):
    """Read-only provider for crypto macro and cross-market context."""

    def economic_events(self) -> list[MacroEvent]:
        raise NotImplementedError

    def context_snapshot(self, symbol: str) -> dict[str, float | None]:
        """Return crypto-relevant macro factors.

        Suggested keys:
        - dxy_change_pct
        - us10y_change_bps
        - real_yield_change_bps
        - vix_change_pct
        - nasdaq_change_pct
        - sp500_change_pct
        - usd_liquidity_score
        - risk_sentiment_score
        - stablecoin_market_cap_change_pct
        - stablecoin_exchange_inflow_score
        - btc_dominance_change_pct
        - btc_etf_flow_score
        - eth_etf_flow_score
        - crypto_funding_environment_score
        - crypto_open_interest_change_pct
        - total_crypto_market_cap_change_pct

        Missing fields must remain None.
        """
        raise NotImplementedError
