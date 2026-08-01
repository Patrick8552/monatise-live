from __future__ import annotations

from math import isfinite
from numbers import Real


def require_finite(**values: Real | None) -> None:
    """Reject booleans, non-numeric values, NaN, and infinities."""
    for name, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{name} must be a finite number")
        if not isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
