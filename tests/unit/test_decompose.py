"""Worked examples for the decomposition library (pure functions)."""

from __future__ import annotations

import math

import pytest

from argus.decompose.lmdi import lmdi, log_mean, shares
from argus.decompose.mix_rate import mix_rate_split
from argus.decompose.segments import Cell, best_choice, minimal_set, should_descend


def test_log_mean_limits() -> None:
    assert log_mean(2.0, 2.0) == 2.0
    assert log_mean(1.0, math.e) == pytest.approx((math.e - 1) / 1.0)
    with pytest.raises(ValueError):
        log_mean(0.0, 1.0)


def test_lmdi_is_exact_and_attributes_the_moving_factor() -> None:
    x0 = {"sessions": 1000.0, "cvr": 0.05}
    x1 = {"sessions": 1010.0, "cvr": 0.04}
    contrib, change, residual = lmdi(x0, x1)
    assert change == pytest.approx(1010 * 0.04 - 1000 * 0.05)
    assert abs(residual) < 1e-9
    assert sum(contrib.values()) == pytest.approx(change)
    s = shares(contrib, change)
    assert s["cvr"] > 0.9 and s["sessions"] < 0
    assert sum(s.values()) == pytest.approx(1.0)


def test_lmdi_many_factors_zero_residual() -> None:
    x0 = {"a": 1.2, "b": 0.6, "c": 0.24, "d": 0.52, "e": 0.9, "f": 0.95}
    x1 = {"a": 1.1, "b": 0.61, "c": 0.25, "d": 0.5, "e": 0.91, "f": 0.62}
    contrib, _, residual = lmdi(x0, x1)
    assert abs(residual) < 1e-12
    assert max(contrib, key=lambda k: abs(contrib[k])) == "f"


def test_mix_rate_is_exact_and_detects_simpsons_paradox() -> None:
    # every country's rate is flat, but traffic shifts to the low-converting country
    num0, den0 = {"DE": 50.0, "ES": 10.0}, {"DE": 1000.0, "ES": 500.0}
    num1, den1 = {"DE": 50.0, "ES": 30.0}, {"DE": 1000.0, "ES": 1500.0}
    split = mix_rate_split(num0, den0, num1, den1)
    assert split.change < 0
    assert abs(split.residual) < 1e-12
    assert abs(split.rate) < 1e-12
    assert split.mix == pytest.approx(split.change)


def _ratio_cells(rates: dict[str, tuple[float, float]], n: float = 4000.0, base_p: float = 0.95) -> list[Cell]:
    """value -> (current rate, volume share)"""
    return [Cell(v, n * w * p, n * w * base_p, n * w, n * w) for v, (p, w) in rates.items()]


def test_segment_choice_prefers_the_concentrated_dimension_and_descends() -> None:
    country = _ratio_cells(
        {"DE": (0.85, 0.3), "FR": (0.95, 0.22), "UK": (0.95, 0.22), "ES": (0.95, 0.13), "NL": (0.95, 0.13)}
    )
    platform = _ratio_cells({"android": (0.88, 0.4), "ios": (0.947, 0.35), "web": (0.95, 0.25)})
    choice = best_choice({"country": country, "platform": platform})
    assert choice is not None and choice.dim == "country" and [c.value for c in choice.cells] == ["DE"]
    assert should_descend(choice)


def test_uniform_children_stop_the_descent() -> None:
    # every child moves the same way: the parent is the answer
    uniform = _ratio_cells({"android": (0.85, 0.4), "ios": (0.85, 0.35), "web": (0.85, 0.25)})
    choice = minimal_set("platform", uniform)
    assert choice is None or not should_descend(choice)


def test_noise_is_not_a_segment() -> None:
    noise = _ratio_cells({"DE": (0.951, 0.3), "FR": (0.949, 0.3), "UK": (0.95, 0.4)})
    choice = best_choice({"country": noise})
    assert choice is None or not should_descend(choice)
