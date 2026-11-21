"""Pacing check: an advertiser budget line that burns its daily budget too early.

    budget_burn(line, h) = sum(ad_spend, 00:00..h) / sum(planned_spend, 00:00..h)      per advertiser x country

A burn above 1.5 before 12:00 opens a `pacing` anomaly on `pacing_ratio` for that line, even when the day's
total spend looks normal: the money is gone by the afternoon. World hours are UTC and so is the
simulator's daily shape, so "12:00" is in data time.

The expected burn is the median burn at the same hour of the day over the previous `days` days, and the
band and z use the robust spread of ln(burn) at that hour, so a line with a jumpy pacer gets a wider band.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from argus.detect.expectation import MAD_TO_SIGMA, SeriesScore
from argus.detect.series import NodeSeries

PACING_NODE = "pacing_ratio"
SPEND_NODE = "ad_spend"
PLAN_NODE = "planned_spend"
LINE_DIMS = ("advertiser_id", "country")


@dataclass(frozen=True)
class PacingParams:
    burn_limit: float = 1.5
    before_hour: int = 12
    days: int = 14
    sigma_floor: float = 0.02
    min_plan_eur: float = 1.0


def burn_scores(
    spend: NodeSeries, plan: NodeSeries, tail: int, params: PacingParams = PacingParams()
) -> dict[str, SeriesScore]:
    """Burn scores of the last `tail` hours for every budget line present in both series."""
    hours = spend.hours
    day = hours.normalize()
    out: dict[str, SeriesScore] = {}
    for key in spend.slices():
        if key not in plan.num.columns:
            continue
        s = pd.Series(spend.num[key].to_numpy(dtype=float), index=hours).fillna(0.0)
        p = pd.Series(plan.num[key].to_numpy(dtype=float), index=hours)
        if p.isna().all():
            continue
        cum_s = s.groupby(day).cumsum()
        cum_p = p.fillna(0.0).groupby(day).cumsum()
        with np.errstate(divide="ignore", invalid="ignore"):
            burn = np.where(cum_p.to_numpy() >= params.min_plan_eur, cum_s.to_numpy() / cum_p.to_numpy(), np.nan)
        log_burn = np.log(np.where(burn > 0, burn, np.nan))
        n = len(hours)
        idx = np.arange(max(n - tail, 0), n)
        past_idx = idx[None, :] - 24 * np.arange(1, params.days + 1)[:, None]
        past = np.where(past_idx >= 0, log_burn[np.clip(past_idx, 0, None)], np.nan)
        enough = np.isfinite(past).sum(axis=0) >= params.days // 2
        with np.errstate(all="ignore"):
            centre = np.nanmedian(np.where(enough, past, 0.0), axis=0)
            spread = MAD_TO_SIGMA * np.nanmedian(np.abs(np.where(enough, past, 0.0) - centre), axis=0)
        expected = np.full(n, np.nan)
        scale = np.full(n, np.nan)
        expected[idx] = np.where(enough, np.exp(centre), np.nan)
        scale[idx] = np.where(enough, np.maximum(params.sigma_floor, spread), np.nan)
        sl = slice(n - tail, n)
        z = (log_burn[sl] - np.log(expected[sl])) / scale[sl]
        out[key] = SeriesScore(
            z=z,
            observed=burn[sl],
            expected=expected[sl],
            lo=expected[sl] * np.exp(-2.0 * scale[sl]),
            hi=expected[sl] * np.exp(2.0 * scale[sl]),
            volume=cum_p.to_numpy()[sl],
            scale=float(scale[-1]) if np.isfinite(scale[-1]) else float("nan"),
            method="burn",
        )
    return out


def pacing_breach(score: SeriesScore, hour: datetime, params: PacingParams = PacingParams()) -> int | None:
    """Index (negative, from the end) of the breach onset when the line breaches the pacing rule at `hour`."""
    burn = score.observed
    if hour.hour >= params.before_hour or not np.isfinite(burn[-1]) or burn[-1] <= params.burn_limit:
        return None
    i = len(burn) - 1
    start_of_day = len(burn) - 1 - hour.hour
    while i - 1 >= max(start_of_day, 0) and np.isfinite(score.hi[i - 1]) and burn[i - 1] > score.hi[i - 1]:
        i -= 1
    return i - len(burn)
