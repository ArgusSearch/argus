"""Seasonal expectation and z-scores on synthetic series with known noise."""

from __future__ import annotations

import numpy as np
import pytest

from argus.detect.expectation import HOURS_PER_WEEK, ScoreParams, fit_variance, score_series

WEEKS = 6
N = WEEKS * HOURS_PER_WEEK


def seasonal_level(base: float) -> np.ndarray:
    hours = np.arange(N)
    daily = 1.0 + 0.5 * np.sin(2 * np.pi * (hours % 24 - 10) / 24)
    weekend = np.where((hours // 24) % 7 >= 5, 1.12, 1.0)
    return base * daily * weekend


def counts(seed: int, base: float = 2000.0, noise: float = 0.03) -> np.ndarray:
    rng = np.random.default_rng(seed)
    mu = seasonal_level(base) * np.exp(rng.normal(0.0, noise, N))
    return rng.poisson(mu).astype(float)


def test_normal_hour_scores_near_zero_and_a_drop_scores_far_below() -> None:
    y = counts(1)
    normal = score_series(y, None, "log", tail=24)
    assert normal is not None and abs(normal.last_z) < 3.5
    assert normal.lo[-1] < normal.expected[-1] < normal.hi[-1]

    dropped = y.copy()
    dropped[-1] *= 0.75
    drop = score_series(dropped, None, "log", tail=24)
    assert drop is not None and drop.last_z < -4
    assert drop.observed[-1] < drop.lo[-1]


def test_z_is_calibrated_on_pure_noise() -> None:
    z = []
    for seed in range(150):
        score = score_series(counts(seed), None, "log", tail=1)
        assert score is not None
        z.append(score.last_z)
    assert 0.8 < float(np.std(z)) < 1.25
    assert abs(float(np.mean(z))) < 0.3


def test_binomial_rate_detects_a_small_drop_in_a_high_volume_rate() -> None:
    rng = np.random.default_rng(3)
    attempts = rng.poisson(seasonal_level(5000.0)).astype(float)
    p = np.full(N, 0.95)
    p[-1] = 0.93
    successes = rng.binomial(attempts.astype(int), p).astype(float)
    score = score_series(successes, attempts, "binomial", tail=24)
    assert score is not None
    assert score.last_z < -4
    assert np.nanmax(np.abs(score.z[:-1])) < 4
    assert score.expected[-1] == pytest.approx(0.95, abs=0.003)


def test_planned_uplift_moves_the_expectation_instead_of_alerting() -> None:
    y = counts(4)
    y[-1] *= 1.4
    plain = score_series(y, None, "log", tail=24)
    uplift = np.zeros(N)
    uplift[-1] = 0.4
    planned = score_series(y, None, "log", tail=24, uplift=uplift)
    assert plain is not None and planned is not None
    assert plain.last_z > 4
    assert abs(planned.last_z) < 3.5
    assert planned.expected[-1] == pytest.approx(plain.expected[-1] * 1.4)


def test_too_little_history_is_not_scored() -> None:
    short = counts(5)[: 2 * HOURS_PER_WEEK]
    assert score_series(short, None, "log", tail=24) is None


def test_low_volume_hours_are_skipped() -> None:
    y = counts(6, base=10.0)
    score = score_series(y, None, "log", tail=24, params=ScoreParams(min_volume=30.0))
    assert score is None or np.isnan(score.last_z)


def test_fit_variance_recovers_both_components() -> None:
    rng = np.random.default_rng(7)
    x = 1.0 / seasonal_level(400.0)[:336]
    a_true, b_true = 0.03**2, 1.5
    e = rng.normal(0.0, np.sqrt(a_true + b_true * x))
    a, b = fit_variance(e, x, min_b=0.0)
    assert a == pytest.approx(a_true, rel=0.6)
    assert b == pytest.approx(b_true, rel=0.6)


def test_poisson_floor_keeps_the_band_at_least_as_wide_as_counting_noise() -> None:
    rng = np.random.default_rng(8)
    x = np.full(336, 1.0 / 50.0)
    e = rng.normal(0.0, 0.01, 336)  # far narrower than Poisson noise for 50 events
    _, b = fit_variance(e, x, min_b=1.0)
    assert b >= 1.0
