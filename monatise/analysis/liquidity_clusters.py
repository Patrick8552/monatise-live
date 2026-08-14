from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

# CoinGlass's measured per-trader liquidation heatmap (aggregated-map /
# heatmap-model2/3) requires a Professional-tier API plan. Standard only
# exposes aggregated open interest and realized liquidation history, not the
# leverage distribution behind it. This module estimates where liquidation
# clusters likely sit by spreading open interest across the leverage tiers
# real exchanges commonly offer, weighted toward the 10x-50x band where
# retail OI tends to concentrate. It is a heuristic model, not measured data,
# and every caller-facing surface must say so.
LEVERAGE_TIERS: tuple[tuple[float, float], ...] = (
    (5.0, 0.12),
    (10.0, 0.24),
    (25.0, 0.30),
    (50.0, 0.22),
    (100.0, 0.12),
)

MAINTENANCE_MARGIN_RATE = 0.005
# Funding rate -> long/short open-interest skew. Positive funding means longs
# pay shorts, the standard proxy for longs dominating open interest.
FUNDING_SKEW_SCALE = 40.0
MAX_SKEW = 0.20


@dataclass(frozen=True)
class LiquidationCluster:
    price: float
    side: str
    leverage: float
    magnitude_usd: float


@dataclass(frozen=True)
class LiquidationClusterMap:
    clusters: tuple[LiquidationCluster, ...]
    nearest_long_cluster: LiquidationCluster | None
    nearest_short_cluster: LiquidationCluster | None
    # -1.0 (pulled toward the long cluster below price) .. +1.0 (pulled
    # toward the short cluster above price). None when there isn't enough
    # data to estimate a direction.
    magnet_bias: float | None


def estimate_liquidation_clusters(
    *,
    price: float | None,
    open_interest_usd: float | None,
    funding_rate: float | None = None,
) -> LiquidationClusterMap | None:
    if price is None or not isfinite(price) or price <= 0:
        return None
    if open_interest_usd is None or not isfinite(open_interest_usd) or open_interest_usd <= 0:
        return None

    long_share = 0.5
    if funding_rate is not None and isfinite(funding_rate):
        skew = max(-MAX_SKEW, min(MAX_SKEW, funding_rate * FUNDING_SKEW_SCALE))
        long_share = 0.5 + skew
    long_oi = open_interest_usd * long_share
    short_oi = open_interest_usd * (1.0 - long_share)

    clusters: list[LiquidationCluster] = []
    for leverage, weight in LEVERAGE_TIERS:
        distance = max(0.001, (1.0 / leverage) - MAINTENANCE_MARGIN_RATE)
        clusters.append(
            LiquidationCluster(
                price=round(price * (1.0 - distance), 8),
                side="long",
                leverage=leverage,
                magnitude_usd=round(long_oi * weight, 2),
            )
        )
        clusters.append(
            LiquidationCluster(
                price=round(price * (1.0 + distance), 8),
                side="short",
                leverage=leverage,
                magnitude_usd=round(short_oi * weight, 2),
            )
        )

    longs = [cluster for cluster in clusters if cluster.side == "long"]
    shorts = [cluster for cluster in clusters if cluster.side == "short"]
    nearest_long = max(longs, key=lambda cluster: cluster.price) if longs else None
    nearest_short = min(shorts, key=lambda cluster: cluster.price) if shorts else None

    magnet_bias = None
    if nearest_long is not None and nearest_short is not None:
        long_pull = nearest_long.magnitude_usd / max(1.0, price - nearest_long.price)
        short_pull = nearest_short.magnitude_usd / max(1.0, nearest_short.price - price)
        total_pull = long_pull + short_pull
        if total_pull > 0:
            magnet_bias = max(-1.0, min(1.0, (short_pull - long_pull) / total_pull))

    return LiquidationClusterMap(
        clusters=tuple(sorted(clusters, key=lambda cluster: cluster.price)),
        nearest_long_cluster=nearest_long,
        nearest_short_cluster=nearest_short,
        magnet_bias=magnet_bias,
    )
