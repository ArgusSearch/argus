"""The lifecycle's calm test: shares keep their binomial z; a ratio of amounts (pacing) has a noise floor."""

from __future__ import annotations

from argus.decompose.segments import Cell
from argus.incidents.lifecycle import CALM_Z, calm_z


def test_a_healthy_pacing_hour_just_below_plan_is_calm() -> None:
    cell = Cell("h", cur=681.61, base=718.70, cur_den=721.86, base_den=721.86)  # 0.94 against 0.996
    assert abs(cell.z) > 10  # the binomial branch: far too strict for spend / plan
    assert abs(calm_z(cell, share=False)) < CALM_Z


def test_a_burnt_budget_hour_is_never_calm() -> None:
    assert abs(calm_z(Cell("h", cur=2900.0, base=720.0, cur_den=721.0, base_den=721.0), share=False)) > 10
    assert abs(calm_z(Cell("h", cur=0.0, base=720.0, cur_den=721.0, base_den=721.0), share=False)) > 10


def test_shares_and_counts_keep_their_z() -> None:
    share = Cell("h", cur=900.0, base=950.0, cur_den=1000.0, base_den=1000.0)
    assert calm_z(share, share=True) == share.z
    count = Cell("h", cur=900.0, base=1000.0)
    assert calm_z(count, share=False) == count.z
