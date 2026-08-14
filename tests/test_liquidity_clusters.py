from __future__ import annotations

from monatise.analysis.liquidity_clusters import estimate_liquidation_clusters


def test_returns_none_without_price_or_open_interest() -> None:
    assert estimate_liquidation_clusters(price=None, open_interest_usd=1_000_000) is None
    assert estimate_liquidation_clusters(price=100.0, open_interest_usd=None) is None
    assert estimate_liquidation_clusters(price=0.0, open_interest_usd=1_000_000) is None
    assert estimate_liquidation_clusters(price=100.0, open_interest_usd=0.0) is None


def test_long_clusters_sit_below_price_and_short_clusters_above() -> None:
    result = estimate_liquidation_clusters(price=100.0, open_interest_usd=10_000_000)
    assert result is not None
    for cluster in result.clusters:
        if cluster.side == "long":
            assert cluster.price < 100.0
        else:
            assert cluster.price > 100.0


def test_higher_leverage_clusters_sit_closer_to_price() -> None:
    result = estimate_liquidation_clusters(price=100.0, open_interest_usd=10_000_000)
    assert result is not None
    longs_by_leverage = {c.leverage: c.price for c in result.clusters if c.side == "long"}
    assert longs_by_leverage[100.0] > longs_by_leverage[50.0] > longs_by_leverage[25.0] > longs_by_leverage[10.0] > longs_by_leverage[5.0]


def test_nearest_clusters_are_closest_to_current_price() -> None:
    result = estimate_liquidation_clusters(price=100.0, open_interest_usd=10_000_000)
    assert result is not None
    assert result.nearest_long_cluster is not None
    assert result.nearest_short_cluster is not None
    assert result.nearest_long_cluster.leverage == 100.0
    assert result.nearest_short_cluster.leverage == 100.0


def test_balanced_open_interest_without_funding_produces_neutral_magnet() -> None:
    result = estimate_liquidation_clusters(price=100.0, open_interest_usd=10_000_000, funding_rate=0.0)
    assert result is not None
    assert result.magnet_bias is not None
    assert abs(result.magnet_bias) < 0.05


def test_positive_funding_skews_open_interest_toward_longs_and_pulls_bias_down() -> None:
    result = estimate_liquidation_clusters(price=100.0, open_interest_usd=10_000_000, funding_rate=0.005)
    assert result is not None
    assert result.magnet_bias is not None
    assert result.magnet_bias < 0.0


def test_negative_funding_skews_open_interest_toward_shorts_and_pulls_bias_up() -> None:
    result = estimate_liquidation_clusters(price=100.0, open_interest_usd=10_000_000, funding_rate=-0.005)
    assert result is not None
    assert result.magnet_bias is not None
    assert result.magnet_bias > 0.0


def test_magnitude_scales_with_open_interest() -> None:
    small = estimate_liquidation_clusters(price=100.0, open_interest_usd=1_000_000)
    large = estimate_liquidation_clusters(price=100.0, open_interest_usd=10_000_000)
    assert small is not None and large is not None
    assert large.nearest_long_cluster.magnitude_usd > small.nearest_long_cluster.magnitude_usd
