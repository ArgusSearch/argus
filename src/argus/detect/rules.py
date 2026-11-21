"""Open, onset and resolve rules on a series of z-scores (index -1 is the scored hour).

* open ``z_gt_open``: |z| > open_z (4) in the scored hour.
* open ``two_of_three``: |z| > run_z (3) in the scored hour and in at least one of the two hours before it,
  on the same side (a Western Electric run rule: catches a smaller shift that persists).
* onset: the first hour of the unbroken run with |z| > 2 on the anomaly's side that ends in the scored hour.
* resolve: the last `calm_hours` scored hours all have |z| < 2.

Both open rules need the scored hour itself to be extreme, so every (series, hour) pair is tested once and
an hour that was already passed over cannot open an anomaly later.

A breakdown look tests m slices at once. `family_params` raises both thresholds (Bonferroni) so that the
whole look has the false-alarm rate of a single series at open_z and run_z: for m = 6 the slice thresholds
are about 4.4 and 3.3.

The defaults (4 and 3) are calibrated for this module's noise model (two-component variance with a Poisson
floor, 14 days of residuals): z has a standard deviation of about 1.03 on quiet worlds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Literal

import numpy as np

from argus.contracts.findings import Direction

Rule = Literal["z_gt_open", "two_of_three"]


@dataclass(frozen=True)
class RuleParams:
    open_z: float = 4.0
    run_z: float = 3.0
    onset_z: float = 2.0
    calm_z: float = 2.0
    calm_hours: int = 3


@dataclass(frozen=True)
class Trigger:
    rule: Rule
    direction: Direction
    onset_index: int
    """Index into the z array of the first hour of the run (negative, counted from the end)."""


def normal_sf(z: float) -> float:
    """P(Z > z) for a standard normal."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def normal_isf(p: float) -> float:
    """Inverse of `normal_sf` by bisection (no scipy needed; p in (0, 0.5))."""
    lo, hi = 0.0, 40.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if normal_sf(mid) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


@lru_cache(maxsize=256)
def family_params(params: RuleParams, m: int) -> RuleParams:
    """Thresholds for one of m series tested together, with the family-wise rate of one series."""
    if m <= 1:
        return params
    open_z = normal_isf(normal_sf(params.open_z) / m)
    # the run rule needs two extreme hours, so each hour carries the square root of the correction
    run_z = normal_isf(normal_sf(params.run_z) / math.sqrt(m))
    return replace(params, open_z=open_z, run_z=run_z)


def direction_of(z: float) -> Direction:
    return "up" if z > 0 else "down"


def onset_index(z: np.ndarray, direction: Direction, params: RuleParams = RuleParams()) -> int:
    sign = 1.0 if direction == "up" else -1.0
    i = len(z) - 1
    while i - 1 >= 0 and np.isfinite(z[i - 1]) and sign * z[i - 1] > params.onset_z:
        i -= 1
    return i - len(z)


def open_trigger(z: np.ndarray, params: RuleParams = RuleParams()) -> Trigger | None:
    if len(z) == 0 or not np.isfinite(z[-1]):
        return None
    last = float(z[-1])
    direction = direction_of(last)
    if abs(last) > params.open_z:
        return Trigger("z_gt_open", direction, onset_index(z, direction, params))
    if abs(last) > params.run_z:
        previous = z[-3:-1]
        same_side = previous[np.isfinite(previous) & (np.sign(previous) == np.sign(last))]
        if np.any(np.abs(same_side) > params.run_z):
            return Trigger("two_of_three", direction, onset_index(z, direction, params))
    return None


def is_calm(z: np.ndarray, params: RuleParams = RuleParams()) -> bool:
    finite = z[np.isfinite(z)]
    if len(finite) < params.calm_hours:
        return False
    return bool(np.all(np.abs(finite[-params.calm_hours :]) < params.calm_z))
