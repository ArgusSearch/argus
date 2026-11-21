"""Scenario library. A scenario mutates `WorldParams` and records its ground truth in the same step.

Every scenario takes its random start, segment and size from the scenario RNG, so no two runs are the
same scripted demo. Stage 1 ships S1 and `quiet`; the others are placeholders owned by lane W.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from mockmart.scenarios.s1_payco import apply_s1
from mockmart.sim import WorldParams

ScenarioFn = Callable[[WorldParams, np.random.Generator], None]


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
    "s2": _placeholder("s2", "planned +40% budget increase for a big advertiser in FR: EXPECTED, no page"),
    "s3": _placeholder("s3", "fact_orders_hourly stalls for 3 h: DATA_ISSUE, not a business incident"),
    "s4": _placeholder("s4", "pacer v1.7 burns DE/FR budgets by 10:00: SUPPORTED_CAUSE pacer v1.7"),
    "s5": _placeholder("s5", "ES traffic surge, each country's rate flat: EXPECTED mix shift"),
    "s6": _placeholder("s6", "click fraud on one advertiser: HYPOTHESIS invalid traffic"),
}
