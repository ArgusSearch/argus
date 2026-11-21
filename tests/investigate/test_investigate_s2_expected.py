"""S2 on the investigator side: a planned budget increase that delivers inside its plan is EXPECTED.

The watcher does not open an anomaly for S2 yet (the line is a few percent of total spend), so this test
hands the investigator the anomaly a segment-level watcher would open at the change. The planned uplift in
log_calendar changes the expectation; the investigator must cite the planned change and not page.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from argus.contracts.findings import Anomaly, Verdict
from argus.graph.store import load_seed_graph
from argus.investigate.claims import claims_of
from argus.investigate.procedure import StageTwoInvestigation
from argus.semantic.runner import Runner
from mockmart.sim import WorldConfig
from mockmart.truth import read_truth
from mockmart.world import generate


@pytest.mark.e2e
@pytest.mark.parametrize("seed", [1, 2])
def test_planned_budget_increase_is_expected_and_cites_the_plan(tmp_path, seed: int) -> None:  # type: ignore[no-untyped-def]
    paths = generate("s2", WorldConfig(seed=seed), tmp_path)
    truth = next(e for e in read_truth(paths.truth) if e["kind"] == "innocent")
    t0 = truth["start_ts"]
    anomaly = Anomaly(
        id="an_s2",
        node="ad_spend",
        segment=truth["segment"],
        direction="up",
        hour=t0 + timedelta(hours=2),
        detected_at=t0 + timedelta(hours=4),
        onset=t0,
        observed=1.0,
        expected=1.0,
        band=(0.9, 1.1),
        z=5.0,
        rule="z_gt_open",
    )
    runner = Runner(paths.world)
    try:
        findings = StageTwoInvestigation(load_seed_graph(), runner, anomaly, anomaly.detected_at).run()
    finally:
        runner.close()
    assert findings.verdict is Verdict.EXPECTED
    assert any(ref in findings.headline for ref in truth["expected"]["evidence_any"])
    calendar = next(s for s in findings.trail if s.kind == "calendar")
    assert calendar.data["planned"][0]["status"] == "as planned"
    assert any(c.label == "evidence" and c.text.startswith("Planned:") for c in claims_of(findings))
