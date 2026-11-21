"""The numbers behind metric self-classification: identity fit, explained variance and lagged correlation.

* `residuals` mirrors the identity_residual edge test (median and p95 relative residual).
* `explained_share` guards empirical formulas: a candidate must reproduce the target's movement, not only
  its level, so a near-constant rate cannot pass as an identity.
* `deseasonalise`, `lag_tests` and `benjamini_hochberg` implement the lagged_corr_bh test: Pearson
  correlation of de-seasonalised hourly series at lags 0..6 h, both directions, BH-corrected.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

import numpy as np

from argus.graph.store import IDENTITY_TEST


def residuals(target: np.ndarray, predicted: np.ndarray) -> tuple[float, float, int]:
    """Median and p95 relative residual over the hours where both are finite (as in identity_residual)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.abs(target - predicted) / np.abs(target)
    rel = rel[np.isfinite(rel)]
    if not len(rel):
        return math.inf, math.inf, 0
    return float(np.median(rel)), float(np.percentile(rel, 95)), len(rel)


def passes_identity(median: float, p95: float) -> bool:
    """The seed identity thresholds (median 0.5 %, p95 2 %)."""
    return median <= (IDENTITY_TEST.median_max or 0) and p95 <= (IDENTITY_TEST.p95_max or 0)


def explained_share(target: np.ndarray, predicted: np.ndarray) -> float:
    """1 - var(residual) / var(target): how much of the target's movement the prediction reproduces."""
    ok = np.isfinite(target) & np.isfinite(predicted)
    if ok.sum() < 3:
        return 0.0
    total = float(np.var(target[ok]))
    if total == 0:
        return 0.0
    return 1.0 - float(np.var(target[ok] - predicted[ok])) / total


def deseasonalise(values: np.ndarray, hours: Sequence[datetime]) -> np.ndarray:
    """Log (when positive) minus the hour-of-day mean, then minus the day-of-week mean of what is left."""
    v = np.array(values, dtype=float)
    finite = np.isfinite(v)
    if finite.any() and (v[finite] > 0).all():
        v = np.log(np.where(finite, v, np.nan))
    for key in ([h.hour for h in hours], [h.weekday() for h in hours]):
        keys = np.array(key)
        for k in np.unique(keys):
            sel = keys == k
            if np.isfinite(v[sel]).any():
                v[sel] -= np.nanmean(v[sel])
    return v


def corr_p_value(r: float, n: int) -> float:
    """Two-sided p-value of a Pearson correlation via the Fisher z transform (normal approximation)."""
    if n <= 3:
        return 1.0
    z = math.atanh(max(min(r, 1 - 1e-12), -1 + 1e-12)) * math.sqrt(n - 3)
    return math.erfc(abs(z) / math.sqrt(2))


def benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    """BH adjusted p-values (q-values), in the input order."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    q = [1.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, p_values[i] * m / rank)
        q[i] = running
    return q


@dataclass(frozen=True)
class LagTest:
    """Correlation of `leader` at t - lag with `follower` at t, on de-seasonalised series."""

    leader: str
    follower: str
    lag: int
    r: float
    n: int
    p: float
    q: float = 1.0

    def describe(self) -> str:
        when = f"{self.leader} leads by {self.lag} h" if self.lag else "same hour, direction unknown"
        return f"r={self.r:.2f}, {when}, BH q={self.q:.1e}"


def _corr(a: np.ndarray, b: np.ndarray) -> tuple[float, int]:
    ok = np.isfinite(a) & np.isfinite(b)
    n = int(ok.sum())
    if n < 10 or np.std(a[ok]) == 0 or np.std(b[ok]) == 0:
        return 0.0, n
    return float(np.corrcoef(a[ok], b[ok])[0, 1]), n


def lag_tests(
    a_id: str, a: np.ndarray, b_id: str, b: np.ndarray, lags: Iterable[int], both: bool = True
) -> list[LagTest]:
    """`a` leads `b` at every lag; with `both`, also `b` leads `a` (lag 0 is tested once)."""
    out = []
    for lag in lags:
        pairs = [(a_id, a, b_id, b)] + ([(b_id, b, a_id, a)] if both and lag > 0 else [])
        for lead_id, lead, follow_id, follow in pairs:
            x, y = (lead[:-lag], follow[lag:]) if lag else (lead, follow)
            r, n = _corr(x, y)
            out.append(LagTest(lead_id, follow_id, lag, r, n, corr_p_value(r, n)))
    return out


def with_q(tests: list[LagTest]) -> list[LagTest]:
    """The same tests with BH q-values over the whole family."""
    q = benjamini_hochberg([t.p for t in tests])
    return [replace(t, q=qi) for t, qi in zip(tests, q, strict=True)]
