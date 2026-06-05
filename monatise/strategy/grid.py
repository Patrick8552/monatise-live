from __future__ import annotations

from dataclasses import dataclass

from monatise.core.models import OrderSide


@dataclass(frozen=True)
class GridLevel:
    level_id: str
    price: float
    side: OrderSide


@dataclass(frozen=True)
class GridConfig:
    center_price: float
    spacing_pct: float
    levels_each_side: int

    def validate(self) -> None:
        if self.center_price <= 0:
            raise ValueError("center_price must be positive")
        if self.spacing_pct <= 0:
            raise ValueError("spacing_pct must be positive")
        if self.levels_each_side < 1:
            raise ValueError("levels_each_side must be at least 1")


class Grid:
    def __init__(self, config: GridConfig) -> None:
        config.validate()
        self.config = config

    def levels(self) -> list[GridLevel]:
        levels: list[GridLevel] = []
        for index in range(self.config.levels_each_side, 0, -1):
            price = self.config.center_price * (1 - (self.config.spacing_pct * index))
            levels.append(GridLevel(f"buy-{index}", round(price, 8), OrderSide.BUY))

        for index in range(1, self.config.levels_each_side + 1):
            price = self.config.center_price * (1 + (self.config.spacing_pct * index))
            levels.append(GridLevel(f"sell-{index}", round(price, 8), OrderSide.SELL))
        return levels
