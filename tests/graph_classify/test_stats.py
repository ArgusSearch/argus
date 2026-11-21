"""The statistics behind placement: BH correction, lagged correlation, de-seasonalising, explained variance."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from argus.graph.classify_stats import (
    benjamini_hochberg,
    corr_p_value,
    deseasonalise,
    explained_share,
    lag_tests,
    passes_identity,
    residuals,
    with_q,
)

HOURS = [datetime(2026, 10, 12) + timedelta(hours=i) for i in range(28 * 24)]


def test_benjamini_hochberg_matches_a_hand_computed_example() -> None:
    assert benjamini_hochberg([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert benjamini_hochberg([]) == []


def test_lag_test_finds_a_planted_lead() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(size=len(HOURS))
    y = np.roll(x, 3) + 0.5 * rng.normal(size=len(HOURS))
    tests = with_q(lag_tests("x", x, "y", y, range(7)))
    best = min(tests, key=lambda t: t.q)
    assert (best.leader, best.follower, best.lag) == ("x", "y", 3)
    assert best.r > 0.8 and best.q < 1e-50
    assert len(tests) == 13  # lag 0 once, lags 1..6 both ways
    noise = [t for t in tests if t.lag != 3]
    assert all(abs(t.r) < 0.15 for t in noise)


def test_deseasonalise_removes_daily_and_weekly_shape() -> None:
    shape = np.array([(1 + 0.5 * np.sin(h.hour / 24 * 2 * np.pi)) * (1 + 0.2 * h.weekday()) for h in HOURS])
    out = deseasonalise(100 * shape, HOURS)
    assert np.nanstd(out) < 1e-9


def test_explained_share_rejects_a_level_only_fit() -> None:
    rng = np.random.default_rng(2)
    target = 0.95 + 0.003 * rng.normal(size=500)
    constant_like = 0.90 + 0.003 * rng.normal(size=500)
    k = np.median(target / constant_like)
    median, p95, _ = residuals(target, k * constant_like)
    assert passes_identity(median, p95)  # the level fits within 0.5 % ...
    assert explained_share(target, k * constant_like) < 0.5  # ... but the movement does not
    assert explained_share(target, target) == pytest.approx(1.0)


def test_p_value_shrinks_with_strength_and_sample() -> None:
    assert corr_p_value(0.0, 600) == pytest.approx(1.0)
    assert corr_p_value(0.3, 600) < corr_p_value(0.3, 60) < corr_p_value(0.1, 60)
