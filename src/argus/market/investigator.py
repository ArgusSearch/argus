"""Stage 2 with a market control check after its normal data and calendar checks."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from argus.contracts.findings import Anomaly, Findings, TrailStep, Verdict
from argus.contracts.graph import Graph
from argus.investigate.planner import Planner
from argus.investigate.procedure import StageTwoInvestigation
from argus.market import check_control_group
from argus.semantic.runner import Runner


class MarketInvestigation(StageTwoInvestigation):
    def _data_checks(self) -> tuple[Verdict, str] | None:
        stop = super()._data_checks()
        if stop is not None:
            return stop
        assessment = check_control_group(self.runner, self.graph, self.anomaly, self.as_of)
        if assessment is None:
            return None
        expected = assessment.verdict == "market"
        self.step(
            "holdout",
            "check_control_group",
            assessment.reason,
            "stop: EXPECTED" if expected else "continue: investigate the metric",
            receipts=[assessment.receipt_id],
            data={"market_control": assessment.model_dump(mode="json")},
        )
        return (Verdict.EXPECTED, f"{assessment.reason} Evidence from {assessment.control}.") if expected else None


def investigate(
    graph: Graph,
    runner: Runner,
    anomaly: Anomaly,
    as_of: datetime,
    on_step: Callable[[TrailStep], None] | None = None,
    planner: Planner | None = None,
) -> Findings:
    return MarketInvestigation(graph, runner, anomaly, as_of, on_step, planner).run()
