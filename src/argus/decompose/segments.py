"""Segment search: Adtributor-style explanatory power with a descent rule.

For every value v of a dimension: EP_v = deviation_v / total deviation, where the deviation of an
additive node is `current - baseline` and of a ratio node the rate effect `n_current * (r_current - r_base)`.
Pick the smallest set of values (at most 3, each EP >= 0.10) whose EP sums to >= 0.67; prefer the
dimension with the fewest values and the most concentrated deviation.

Descent rule (fixes the naive rule that stops at `country = DE` when only Android is affected):
descend into a single chosen cell only while its deviation is concentrated, i.e. the chosen cells
explain clearly more than their volume share (`excess = EP - volume_share >= 0.25`) and the
deviation is statistically clear (|z| >= 3). Uniform children mean the parent is the answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EP_TARGET = 0.67
EP_MIN = 0.10
MAX_CELLS = 3
EXCESS_MIN = 0.25
Z_DESCEND = 3.0
OVERDISPERSION = 0.03  # relative noise floor for additive cells (traffic is noisier than Poisson)


@dataclass(frozen=True)
class Cell:
    value: str
    cur: float  # additive: current total; ratio: current numerator
    base: float  # additive: baseline total; ratio: baseline numerator
    cur_den: float | None = None
    base_den: float | None = None
    weeks: int = 4

    @property
    def is_ratio(self) -> bool:
        return self.cur_den is not None

    @property
    def deviation(self) -> float:
        if not self.is_ratio:
            return self.cur - self.base
        if not self.cur_den or not self.base_den:
            return 0.0
        return self.cur_den * (self.cur / self.cur_den - self.base / self.base_den)

    @property
    def volume(self) -> float:
        return float(self.cur_den if self.is_ratio else self.base) or 0.0

    @property
    def rel_change(self) -> float:
        if not self.is_ratio:
            return self.cur / self.base - 1 if self.base else 0.0
        if not self.cur_den or not self.base_den or not self.base:
            return 0.0
        return (self.cur / self.cur_den) / (self.base / self.base_den) - 1

    @property
    def z(self) -> float:
        if not self.is_ratio:
            sd = math.sqrt(max(self.base, 1.0) + (OVERDISPERSION * self.base) ** 2)
            return self.deviation / sd
        if not self.cur_den or not self.base_den:
            return 0.0
        p0 = self.base / self.base_den
        p1 = self.cur / self.cur_den
        if 0 < p0 < 1:
            var = p0 * (1 - p0) * (1 / self.cur_den + 1 / (self.weeks * self.base_den))
        else:
            var = (p0**2) * (1 / max(self.cur, 1) + 1 / max(self.cur_den, 1))
        return (p1 - p0) / math.sqrt(var) if var > 0 else 0.0


@dataclass(frozen=True)
class Choice:
    dim: str
    cells: list[Cell]
    ep: float
    volume_share: float

    @property
    def excess(self) -> float:
        return self.ep - self.volume_share


def explanatory_power(cells: list[Cell]) -> dict[str, tuple[float, float]]:
    """value -> (EP, volume share)."""
    total_dev = sum(c.deviation for c in cells)
    total_vol = sum(c.volume for c in cells)
    return {
        c.value: (c.deviation / total_dev if total_dev else 0.0, c.volume / total_vol if total_vol else 0.0)
        for c in cells
    }


def minimal_set(dim: str, cells: list[Cell]) -> Choice | None:
    ep = explanatory_power(cells)
    ranked = sorted(cells, key=lambda c: -ep[c.value][0])
    chosen: list[Cell] = []
    total = 0.0
    for cell in ranked:
        if ep[cell.value][0] < EP_MIN or len(chosen) == MAX_CELLS:
            break
        chosen.append(cell)
        total += ep[cell.value][0]
        if total >= EP_TARGET:
            return Choice(dim, chosen, total, sum(ep[c.value][1] for c in chosen))
    return None


def best_choice(candidates: dict[str, list[Cell]]) -> Choice | None:
    """Among dimensions, prefer fewer cells, then the most concentrated deviation (largest excess)."""
    choices = [c for dim, cells in candidates.items() if (c := minimal_set(dim, cells)) is not None]
    if not choices:
        return None
    return min(choices, key=lambda c: (len(c.cells), -c.excess))


def should_descend(choice: Choice) -> bool:
    return len(choice.cells) == 1 and choice.excess >= EXCESS_MIN and abs(choice.cells[0].z) >= Z_DESCEND
