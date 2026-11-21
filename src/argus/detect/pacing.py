"""Pacing check: an advertiser budget line that burns its daily budget too early.

    budget_burn(line, h) = sum(ad_spend, 00:00..h) / sum(planned_spend, 00:00..h)      per advertiser x country

A burn above 1.5 before 12:00 opens a `pacing` anomaly on `pacing_ratio` for that line, even when the day's
total spend looks normal: the money is gone by the afternoon. World hours are UTC and so is the
simulator's daily shape, so "12:00" is in data time.

The burn only counts once `min_plan_share` of the day's plan is due (about 04:00): at 00:00 the burn is one
noisy hour, not a pace. The plan view holds the whole day ahead, so the day's plan is known in the morning.

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
    min_plan_share: float = 0.10


def burn_scores(
    spend: NodeSeries, plan: NodeSeries, tail: int, params: PacingParams = PacingParams()
) -> dict[str, SeriesScore]:
    """Burn scores of the last `tail` hours for every budget line present in both series.

    `plan` may run past the last spend hour (to the end of the day): the day's planned total comes from it.
    """
    hours = spend.hours
    day = hours.normalize()
    out: dict[str, SeriesScore] = {}
    for key in spend.slices():
        if key not in plan.num.columns:
            continue
        s = pd.Series(spend.num[key].to_numpy(dtype=float), index=hours).fillna(0.0)
        plan_all = pd.Series(plan.num[key].to_numpy(dtype=float), index=plan.hours)
        p = plan_all.reindex(hours)
        if p.isna().all():
            continue
        day_plan = plan_all.fillna(0.0).groupby(plan.hours.normalize()).sum().reindex(day).to_numpy()
        cum_s = s.groupby(day).cumsum()
        cum_p = p.fillna(0.0).groupby(day).cumsum().to_numpy()
        due = (cum_p >= params.min_plan_eur) & (cum_p >= params.min_plan_share * np.nan_to_num(day_plan))
        with np.errstate(divide="ignore", invalid="ignore"):
            burn = np.where(due, cum_s.to_numpy() / cum_p, np.nan)
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
            volume=cum_p[sl],
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
