"""Open, onset, resolve and family-wise thresholds."""

from __future__ import annotations

import numpy as np
import pytest

from argus.detect.rules import RuleParams, family_params, is_calm, normal_isf, normal_sf, onset_index, open_trigger

nan = float("nan")


def z(*values: float) -> np.ndarray:
    return np.array(values, dtype=float)


def test_single_extreme_hour_opens_z_gt_open() -> None:
    trig = open_trigger(z(0.1, -0.5, 1.0, -4.5))
    assert trig is not None and trig.rule == "z_gt_open" and trig.direction == "down"


def test_two_of_three_beyond_3_on_the_same_side() -> None:
    trig = open_trigger(z(0.2, 3.4, 0.5, 3.2))
    assert trig is not None and trig.rule == "two_of_three" and trig.direction == "up"
    assert open_trigger(z(0.2, -3.4, 0.5, 3.2)) is None  # opposite sides do not add up
    assert open_trigger(z(3.4, 0.1, 0.5, 3.2)) is None  # outside the last three hours


def test_scored_hour_must_be_extreme() -> None:
    assert open_trigger(z(5.0, 3.5, 2.9)) is None
    assert open_trigger(z(1.0, nan)) is None
    assert open_trigger(z()) is None


def test_onset_is_the_start_of_the_run_beyond_2() -> None:
    series = z(0.3, 2.5, 1.0, -2.2, -3.1, -4.6)
    trig = open_trigger(series)
    assert trig is not None and trig.onset_index == -3
    assert onset_index(z(-2.5, nan, -2.6, -5.0), "down") == -2  # a missing hour breaks the run


def test_calm_needs_three_quiet_scored_hours() -> None:
    assert is_calm(z(-6.0, 1.0, -0.5, 1.9))
    assert not is_calm(z(1.0, -0.5, 2.1))
    assert is_calm(z(1.0, nan, -0.5, 0.2))
    assert not is_calm(z(0.5, nan))


def test_family_thresholds_keep_the_single_series_rate() -> None:
    base = RuleParams()
    assert family_params(base, 1) == base
    six = family_params(base, 6)
    assert six.open_z == pytest.approx(4.405, abs=0.01)
    assert normal_sf(six.open_z) * 6 == pytest.approx(normal_sf(base.open_z))
    assert family_params(base, 16).open_z > six.open_z > base.open_z
    assert six.run_z > base.run_z
    assert normal_isf(normal_sf(3.0)) == pytest.approx(3.0)
