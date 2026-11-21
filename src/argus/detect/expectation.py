"""Seasonal expectation and robust, volume-aware z-scores for one hourly series.

Expectation: the same hour of the week in the previous `weeks` weeks. Planned uplift (budget and calendar plans)
is removed from the baseline hours and applied to the scored hour, so a promo changes the expectation
instead of muting the metric:

    expected_t = median_k( y_{t-168k} / (1 + u_{t-168k}) ) * (1 + u_t)        k = 1..weeks

For share ratios (payment_success_rate, cvr, ...) the baseline is pooled instead of a median:
sum of numerators / sum of denominators over the same baseline hours.

Noise: a residual `e_t` and a two-component variance

    Var(e_t) = a + b * x_t

* ``binomial`` (share ratios): ``e = p - p_exp`` and ``x = p_exp (1 - p_exp) / n``. b >= 1 keeps the band
  at least as wide as pure binomial noise; a is extra-binomial noise (mix shifts, provider wobble).
* ``log`` (counts, EUR amounts, other ratios): ``e = ln(y / expected)`` and x the Poisson part that makes
  a quiet night noisier than a busy afternoon; a is multiplicative noise. When the caller knows the event
  counts behind the series (`poisson_x`, e.g. 1 / orders for gmv, 1 / clicks + 1 / conversions for cpa),
  b >= 1 is a hard floor: the band is never narrower than counting noise. Otherwise x = 1 / volume, b >= 0.

a and b are fitted on the trailing `history_hours` hours (each scored against its own seasonal
expectation) from two robust variances (1.4826 x MAD, squared): hours with low x and hours with high x.
So every series, the whole business or a small segment, gets its own noise scale, and the scale follows
the daily volume cycle, without per-metric tuning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

HOURS_PER_WEEK = 168
MAD_TO_SIGMA = 1.4826

Method = Literal["binomial", "log", "burn"]
"""burn is the pacing check's cumulative spend / plan (see `argus.detect.pacing`)."""


@dataclass(frozen=True)
class ScoreParams:
    weeks: int = 4
    min_weeks: int = 2
    history_hours: int = 336
    min_history: int = 48
    sigma_floor: float = 0.005
    min_volume: float = 30.0


@dataclass(frozen=True)
class SeriesScore:
    """Scores of the last `len(z)` hours of a series; index -1 is the scored hour.

    Hours that cannot be scored (no baseline, too little volume, missing data) are NaN in every array.
    `scale` is the noise std of the scored hour in the units of `observed`.
    """

    z: np.ndarray
    observed: np.ndarray
    expected: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    volume: np.ndarray
    scale: float
    method: Method

    @property
    def last_z(self) -> float:
        return float(self.z[-1])


def shift(values: np.ndarray, hours: int) -> np.ndarray:
    """values moved `hours` later (value at t is the input at t - hours); NaN where there is no input."""
    out = np.full(values.shape, np.nan)
    if hours < len(values):
        out[hours:] = values[: len(values) - hours]
    return out


def robust_var(values: np.ndarray) -> float:
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return float("nan")
    return float((MAD_TO_SIGMA * np.median(np.abs(values - np.median(values)))) ** 2)


def fit_variance(e: np.ndarray, x: np.ndarray, min_b: float) -> tuple[float, float]:
    """Fit Var(e) = a + b x from two robust variances: the hours below and above the median x."""
    ok = np.isfinite(e) & np.isfinite(x)
    e, x = e[ok], x[ok]
    split = np.median(x)
    low, high = x <= split, x > split
    if low.sum() < 8 or high.sum() < 8 or np.mean(x[high]) <= np.mean(x[low]) * 1.05:
        pooled = robust_var(e)
        b = min_b
        return max(pooled - b * float(np.mean(x)), 0.0), b
    v_low, v_high = robust_var(e[low]), robust_var(e[high])
    x_low, x_high = float(np.mean(x[low])), float(np.mean(x[high]))
    b = max((v_high - v_low) / (x_high - x_low), min_b)
    a = max(v_low - b * x_low, 0.0)
    return a, b


def score_series(
    num: np.ndarray,
    den: np.ndarray | None,
    method: Method,
    tail: int,
    uplift: np.ndarray | None = None,
    params: ScoreParams = ScoreParams(),
    poisson_x: np.ndarray | None = None,
) -> SeriesScore | None:
    """Score the last `tail` hours of a contiguous hourly series ending at the scored hour.

    `num` is the value of an additive node or the numerator of a ratio; `den` is the ratio's denominator
    (None for additive nodes). `poisson_x` (log method only) is the counting-noise variance of ln(value)
    per hour, sum of 1 / count over the counts that drive the series. Returns None when the history is too
    short to estimate the noise.
    """
    num = np.asarray(num, dtype=float)
    den_arr = None if den is None else np.asarray(den, dtype=float)
    lift = 1.0 + (np.zeros(len(num)) if uplift is None else np.asarray(uplift, dtype=float))
    n_hours = len(num)
    if n_hours < params.min_weeks * HOURS_PER_WEEK + params.min_history + 1:
        return None

    lags = [k * HOURS_PER_WEEK for k in range(1, params.weeks + 1)]
    with np.errstate(divide="ignore", invalid="ignore"):
        if method == "binomial":
            if den_arr is None:
                raise ValueError("binomial scoring needs a denominator")
            observed = np.where(den_arr > 0, num / den_arr, np.nan)
            base_num = np.stack([shift(num / lift, lag) for lag in lags])
            base_den = np.stack([shift(den_arr, lag) for lag in lags])
            ok = np.isfinite(base_num) & np.isfinite(base_den) & (base_den > 0)
            weeks_ok = ok.sum(axis=0)
            pooled = np.where(ok, base_num, 0.0).sum(axis=0) / np.where(ok, base_den, 0.0).sum(axis=0)
            expected = np.clip(pooled * lift, 1e-9, 1 - 1e-9)
            volume = den_arr
            resid = observed - expected
            x = expected * (1 - expected) / volume
            min_b = 1.0
        else:
            observed = num if den_arr is None else np.where(den_arr > 0, num / den_arr, np.nan)
            observed = np.where(observed > 0, observed, np.nan)
            base = np.stack([shift(observed / lift, lag) for lag in lags])
            weeks_ok = np.isfinite(base).sum(axis=0)
            none = weeks_ok == 0
            expected = np.where(none, np.nan, np.nanmedian(np.where(none, 1.0, base), axis=0)) * lift
            resid = np.log(observed / expected)
            if poisson_x is not None:
                x = np.asarray(poisson_x, dtype=float)
                volume = 1.0 / x
                min_b = 1.0
            else:
                volume = den_arr if den_arr is not None else num
                x = 1.0 / volume
                min_b = 0.0

    valid = (weeks_ok >= params.min_weeks) & np.isfinite(resid) & (np.nan_to_num(volume) >= params.min_volume)
    resid = np.where(valid, resid, np.nan)

    hist = slice(max(0, n_hours - 1 - params.history_hours), n_hours - 1)
    if np.isfinite(resid[hist]).sum() < params.min_history:
        return None
    a, b = fit_variance(resid[hist], x[hist], min_b)
    with np.errstate(invalid="ignore"):
        sigma = np.sqrt(a + b * x)
    if method == "log":
        sigma = np.maximum(sigma, params.sigma_floor)
        lo, hi = expected * np.exp(-2.0 * sigma), expected * np.exp(2.0 * sigma)
        scale = float(expected[-1] * sigma[-1])
    else:
        lo, hi = expected - 2.0 * sigma, expected + 2.0 * sigma
        scale = float(sigma[-1])
    z = resid / sigma

    sl = slice(n_hours - tail, n_hours)

    def cut(values: np.ndarray) -> np.ndarray:
        return np.where(valid[sl], values[sl], np.nan)

    return SeriesScore(
        z=cut(z),
        observed=cut(observed),
        expected=cut(expected),
        lo=cut(lo),
        hi=cut(hi),
        volume=cut(np.asarray(volume, dtype=float)),
        scale=scale,
        method=method,
    )
