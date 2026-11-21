"""Pacing rule on synthetic spend and plan series."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from argus.detect.pacing import LINE_DIMS, burn_scores, pacing_breach
from argus.detect.series import NodeSeries

LINE = "adv_01|DE"
DAYS = 15


def series(node: str, values: np.ndarray, hours: pd.DatetimeIndex) -> NodeSeries:
    return NodeSeries(node, LINE_DIMS, hours, pd.DataFrame({LINE: values}, index=hours), None)


def world(burn_from: int | None, factor: float, until_hour: int) -> tuple[NodeSeries, NodeSeries, datetime]:
    hours = pd.date_range("2026-11-01", periods=DAYS * 24, freq="h")[: (DAYS - 1) * 24 + until_hour + 1]
    shape = 1.0 + 0.5 * np.sin(2 * np.pi * (hours.hour.to_numpy() - 10) / 24)
    plan = 3000.0 * shape / shape[:24].sum()
    rng = np.random.default_rng(0)
    spend = plan * np.exp(rng.normal(0.0, 0.04, len(hours)))
    if burn_from is not None:
        today = hours >= hours[-1].normalize() + pd.Timedelta(hours=burn_from)
        spend = np.where(today, spend * factor, spend)
    return series("ad_spend", spend, hours), series("planned_spend", plan, hours), hours[-1].to_pydatetime()


def test_early_overspend_breaches_the_pacing_rule() -> None:
    spend, plan, hour = world(burn_from=6, factor=2.6, until_hour=9)
    score = burn_scores(spend, plan, tail=24)[LINE]
    assert score.observed[-1] > 1.5
    onset = pacing_breach(score, hour)
    assert onset is not None
    assert hour.hour + onset + 1 >= 6  # onset is today, at or after the overspend started


def test_normal_pacing_does_not_breach() -> None:
    spend, plan, hour = world(burn_from=None, factor=1.0, until_hour=9)
    score = burn_scores(spend, plan, tail=24)[LINE]
    assert abs(score.observed[-1] - 1.0) < 0.1
    assert pacing_breach(score, hour) is None


def test_the_rule_only_applies_before_noon() -> None:
    spend, plan, hour = world(burn_from=0, factor=2.6, until_hour=14)
    score = burn_scores(spend, plan, tail=24)[LINE]
    assert score.observed[-1] > 1.5
    assert pacing_breach(score, hour) is None
