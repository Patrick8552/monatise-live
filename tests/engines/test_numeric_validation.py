from math import inf, nan

from monatise.engines._validation import require_finite
from monatise.engines.capital_allocation.models import PortfolioExposure


def test_shared_numeric_guard_rejects_non_finite_values() -> None:
    for value in (nan, inf, -inf):
        try:
            require_finite(value=value)
        except ValueError:
            pass
        else:
            raise AssertionError("expected non-finite value rejection")


def test_portfolio_exposure_rejects_nan() -> None:
    exposure = PortfolioExposure(
        total_equity=10_000,
        deployed_capital=nan,
        open_risk_amount=0,
        crypto_exposure_pct=0,
        symbol_exposure_pct=0,
        correlated_exposure_pct=0,
        open_positions=0,
        symbol_positions=0,
    )
    try:
        exposure.validate()
    except ValueError as exc:
        assert "finite" in str(exc)
    else:
        raise AssertionError("expected NaN rejection")
