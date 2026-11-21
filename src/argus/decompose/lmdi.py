"""Additive LMDI (Log Mean Divisia Index) split of a product's change. Exact, zero residual.

For Y = x_1 * x_2 * ... * x_n between a baseline (0) and the current window (1):

    contribution_i = L(Y1, Y0) * ln(x_i1 / x_i0),   L(a, b) = (a - b) / (ln a - ln b),  L(a, a) = a
    sum_i contribution_i = L(Y1, Y0) * ln(Y1 / Y0) = Y1 - Y0

Zero or negative factors have no logarithm; they are replaced by `EPS` (documented approximation,
the residual is then reported instead of being hidden).
"""

from __future__ import annotations

import math

EPS = 1e-12


def log_mean(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        raise ValueError("log mean needs positive values")
    if math.isclose(a, b, rel_tol=1e-15, abs_tol=0.0):
        return a
    return (a - b) / (math.log(a) - math.log(b))


def lmdi(x0: dict[str, float], x1: dict[str, float]) -> tuple[dict[str, float], float, float]:
    """Return (contribution per factor, Y1 - Y0, residual). Factor order follows `x0`."""
    if set(x0) != set(x1):
        raise ValueError("baseline and current need the same factors")
    a = {k: max(v, EPS) for k, v in x0.items()}
    b = {k: max(v, EPS) for k, v in x1.items()}
    y0 = math.prod(a.values())
    y1 = math.prod(b.values())
    weight = log_mean(y1, y0)
    contrib = {k: weight * math.log(b[k] / a[k]) for k in x0}
    change = math.prod(x1.values()) - math.prod(x0.values())
    return contrib, change, change - sum(contrib.values())


def shares(contrib: dict[str, float], change: float) -> dict[str, float]:
    """Share of the change carried by each factor (signed; sums to 1 when the residual is 0)."""
    if change == 0:
        return dict.fromkeys(contrib, 0.0)
    return {k: v / change for k, v in contrib.items()}
