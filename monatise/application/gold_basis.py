"""Contract-specific midpoint mapping, never an executable price provider."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median


@dataclass(frozen=True)
class BasisSample:
    contract: str
    broker_mid: Decimal
    futures_mid: Decimal
    broker_at: datetime
    futures_at: datetime


class GoldBasisService:
    def __init__(
        self,
        *,
        minimum_samples=5,
        maximum_age=timedelta(seconds=30),
        max_skew=timedelta(seconds=1),
        max_dispersion=Decimal(".5"),
        max_residual=Decimal(1),
    ):
        if (
            minimum_samples < 3
            or maximum_age.total_seconds() <= 0
            or max_skew.total_seconds() < 0
            or max_dispersion <= 0
            or max_residual <= 0
        ):
            raise ValueError("invalid basis policy")
        self.minimum_samples, self.maximum_age, self.max_skew = (
            minimum_samples,
            maximum_age,
            max_skew,
        )
        self.max_dispersion, self.max_residual = max_dispersion, max_residual
        self.samples = deque(maxlen=128)
        self.contract = None

    def add(self, **kwargs):
        try:
            return self._add(**kwargs)
        except (ValueError, ArithmeticError, TypeError):
            # A rejected current observation quarantines prior translated
            # levels until a fresh, sufficient window is rebuilt.
            self.samples.clear()
            raise

    def _add(
        self,
        *,
        contract,
        broker_bid,
        broker_ask,
        futures_bid,
        futures_ask,
        broker_at,
        futures_at,
        now,
    ):
        prices = [
            Decimal(str(v)) for v in (broker_bid, broker_ask, futures_bid, futures_ask)
        ]
        if (
            any(not p.is_finite() or p <= 0 for p in prices)
            or prices[0] > prices[1]
            or prices[2] > prices[3]
        ):
            raise ValueError("invalid midpoint quote geometry")
        if prices[1] - prices[0] > 5 or prices[3] - prices[2] > 5:
            raise ValueError("basis quote too wide")
        if (
            not contract
            or any(t.tzinfo is None for t in (broker_at, futures_at, now))
            or abs(broker_at - futures_at) > self.max_skew
            or any(
                not timedelta(0) <= now - t <= self.maximum_age
                for t in (broker_at, futures_at)
            )
        ):
            raise ValueError("asynchronous, future or stale basis quotes")
        if self.contract != contract:
            self.samples.clear()
            self.contract = contract
        if self.samples and (
            broker_at <= self.samples[-1].broker_at
            or futures_at <= self.samples[-1].futures_at
        ):
            raise ValueError("duplicate or unordered basis observation")
        self.samples.append(
            BasisSample(
                contract,
                sum(prices[:2]) / 2,
                sum(prices[2:]) / 2,
                broker_at,
                futures_at,
            )
        )

    def estimate(self, *, contract, now):
        if contract != self.contract:
            raise ValueError("basis contract mismatch or roll")
        samples = [
            s
            for s in self.samples
            if all(
                timedelta(0) <= now - t <= self.maximum_age
                for t in (s.broker_at, s.futures_at)
            )
        ]
        if len(samples) < self.minimum_samples:
            raise ValueError("insufficient fresh basis samples")
        values = [s.futures_mid - s.broker_mid for s in samples]
        centre = median(values)
        dispersion = max(values) - min(values)
        residual = abs(values[-1] - centre)
        if dispersion > self.max_dispersion or residual > self.max_residual:
            raise ValueError("basis dispersion or residual excessive")
        uncertainty = max(abs(v - centre) for v in values)
        return {
            "contract": contract,
            "basis": centre,
            "uncertainty": uncertainty,
            "sample_count": len(samples),
            "window_start": min(min(s.broker_at, s.futures_at) for s in samples),
            "as_of": max(max(s.broker_at, s.futures_at) for s in samples),
            "expires_at": min(min(s.broker_at, s.futures_at) for s in samples)
            + self.maximum_age,
        }

    def map_level(self, level, *, contract, now):
        original = Decimal(str(level))
        if not original.is_finite() or original <= 0:
            raise ValueError("invalid GC level")
        estimate = self.estimate(contract=contract, now=now)
        mapped = original - estimate["basis"]
        if mapped - estimate["uncertainty"] <= 0:
            raise ValueError("mapped level invalid")
        return {
            **estimate,
            "original_gc_level": original,
            "mapped_low": mapped - estimate["uncertainty"],
            "mapped_high": mapped + estimate["uncertainty"],
            "context_only": True,
            "execution_price_authority": False,
        }
