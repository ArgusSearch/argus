"""Scenario library. A scenario mutates `WorldParams` and records its ground truth in the same step.

Every scenario takes its random start, segment and size from the scenario RNG, so no two runs are the
same scripted demo. Built: `quiet` and S1 through S5. S6 is a placeholder owned by lane W.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from mockmart.scenarios.s1_payco import apply_s1
from mockmart.scenarios.s2_budget import apply_s2
from mockmart.scenarios.s3_orders_stall import apply_s3
from mockmart.scenarios.s4_pacer import apply_s4
from mockmart.scenarios.s5_market import apply_s5
from mockmart.sim import WorldParams

ScenarioFn = Callable[[WorldParams, np.random.Generator], Callable[[Path], dict[str, int]] | None]


def _quiet(params: WorldParams, rng: np.random.Generator) -> None:
    """No injected change: the false-alarm baseline."""


def _placeholder(scenario_id: str, summary: str) -> ScenarioFn:
    def apply(params: WorldParams, rng: np.random.Generator) -> None:
        raise NotImplementedError(f"scenario {scenario_id} ({summary}) is a placeholder, owned by lane W")

    apply.__doc__ = summary
    return apply


SCENARIOS: dict[str, ScenarioFn] = {
    "quiet": _quiet,
    "s1": apply_s1,
    "s2": apply_s2,
    "s3": apply_s3,
    "s4": apply_s4,
    "s5": apply_s5,
    "s6": _placeholder("s6", "click fraud on one advertiser: HYPOTHESIS invalid traffic"),
}
