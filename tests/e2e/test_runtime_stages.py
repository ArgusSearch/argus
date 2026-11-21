"""The runtime investigates with Stage 2 and keeps Stage 1 as its fallback.

Stage 2 is the default; `Runtime(stage=1)` runs the Stage-1 fixed opening for every anomaly, and an anomaly
the Stage-2 investigator fails on is re-investigated with Stage 1 instead of stopping the watch.
"""

from __future__ import annotations

import pytest

from argus.contracts.findings import Incident, Verdict
from argus.runtime import loop
from argus.runtime.loop import Runtime
from mockmart.world import WorldPaths

pytestmark = pytest.mark.e2e

STAGE_TWO_TOOLS = {"placebo_test"}  # only the Stage-2 investigator runs the placebo


def _payco(runtime: Runtime) -> Incident:
    (incident,) = runtime.book.incidents.values()
    assert incident.verdict is Verdict.SUPPORTED_CAUSE and incident.root_node == "payment_success_rate"
    assert incident.findings.root and incident.findings.root.evidence
    assert incident.findings.root.evidence.ref == "ps_payco_degraded"
    return incident


def _tools(incident: Incident) -> set[str]:
    return {step.tool for step in incident.findings.trail}


def test_runtime_investigates_with_stage_two_by_default(s1_world: WorldPaths) -> None:
    runtime = Runtime(s1_world.world)
    runtime.run()
    assert runtime.stage == 2 and runtime.fallbacks == []
    assert _tools(_payco(runtime)) >= STAGE_TWO_TOOLS


def test_stage_one_on_request(s1_world: WorldPaths) -> None:
    runtime = Runtime(s1_world.world, stage=1)
    runtime.run()
    assert not STAGE_TWO_TOOLS & _tools(_payco(runtime))


def test_a_failing_stage_two_falls_back_to_stage_one(s1_world: WorldPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("planner exploded")

    monkeypatch.setattr(loop, "investigate", broken)
    runtime = Runtime(s1_world.world)
    runtime.run()
    incident = _payco(runtime)
    assert not STAGE_TWO_TOOLS & _tools(incident)
    assert runtime.fallbacks == [f"{incident.anomalies[0]}: RuntimeError: planner exploded"]


def test_unknown_stage_is_rejected(s1_world: WorldPaths) -> None:
    with pytest.raises(ValueError, match="stage"):
        Runtime(s1_world.world, stage=3)
