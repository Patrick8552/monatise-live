"""The existing crypto hierarchy, shared by every candle-based asset route.

These are strategy roles, not scanner polling intervals. Keep the defaults and
lifetimes identical to the original crypto evaluator. Market calendars belong
to the data/session boundary, never to an alternative timeframe configuration.
"""

from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType


@dataclass(frozen=True)
class TimeframePolicy:
    context: str = "4h"
    analysis: str = "1h"
    setup: str = "15m"
    confirmation: str = "5m"
    entry: str = "1m"
    context_lifetime: timedelta = timedelta(hours=5)
    analysis_lifetime: timedelta = timedelta(hours=2)
    setup_lifetime: timedelta = timedelta(minutes=45)
    confirmation_lifetime: timedelta = timedelta(minutes=15)
    signal_lifetime: timedelta = timedelta(minutes=15)

    @property
    def timeframes(self) -> tuple[str, ...]:
        return (self.context, self.analysis, self.setup, self.confirmation, self.entry)

    @property
    def trigger(self) -> str:
        return self.confirmation

    @property
    def parent_timeframes(self) -> tuple[str, ...]:
        return self.timeframes[:3]

    @property
    def entry_timeframes(self) -> tuple[str, ...]:
        return self.timeframes[3:]

    def metadata(self) -> dict:
        return {
            "timeframe_policy": "crypto-hierarchy-v1",
            "context_timeframe": self.context,
            "analysis_timeframe": self.analysis,
            "setup_timeframe": self.setup,
            "confirmation_timeframe": self.confirmation,
            "trigger_timeframe": self.trigger,
            "entry_timeframe": self.entry,
            "stop_timeframe": self.setup,
            "timeframe": self.analysis,
            "interval": self.analysis,
        }


CRYPTO_TIMEFRAME_POLICY = TimeframePolicy()
SHARED_TIMEFRAME_POLICY = CRYPTO_TIMEFRAME_POLICY
INTERVAL_SECONDS = MappingProxyType(
    {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
)


def timeframe_policy(asset_class: str) -> TimeframePolicy:
    if str(asset_class).casefold() not in {
        "crypto",
        "stock",
        "stocks",
        "index",
        "indices",
    }:
        raise ValueError("asset class does not use the shared candle hierarchy")
    return SHARED_TIMEFRAME_POLICY
