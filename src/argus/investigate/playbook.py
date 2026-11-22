"""Named playbooks: the fixed opening shown as a repeatable, named workflow with step status.

Every trail step carries `data["playbook"]` (playbook id and name, the named step, its question and its
position), so the findings (C4) and the `investigation_step` events (C5) show it without a contract
change, and the UI can render "Revenue drop playbook: Data freshness -> Exact split -> ... -> Verdict".
The final verdict step also carries `data["playbook_run"]`: every step of the playbook with its status
(done, or skipped when the investigation stopped early or the step did not apply).

The playbook is chosen from the anomaly: the family of its node (revenue and payments, traffic, ads and
pacing) and the direction of the change. All playbooks share the same steps; the names make the
procedure legible, they do not change it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from argus.contracts.graph import Graph

ADS_TABLES = ("fact_ads_hourly", "fact_ad_plan_hourly")
TRAFFIC_NODES = ("sessions", "product_views", "view_rate")


@dataclass(frozen=True)
class PlaybookStep:
    id: str
    label: str
    question: str


STEPS: tuple[PlaybookStep, ...] = (
    PlaybookStep("data_freshness", "Data freshness", "Did all source data arrive?"),
    PlaybookStep("identities", "Identity check", "Do the cross-table identities hold?"),
    PlaybookStep("planned_events", "Planned events", "Was this change planned?"),
    PlaybookStep("exact_split", "Exact split (LMDI)", "Which factor carries the change?"),
    PlaybookStep("mix_vs_rate", "Mix vs rate", "Did the mix shift, or did the rates move?"),
    PlaybookStep("segment_search", "Segment search", "Where is the change concentrated?"),
    PlaybookStep("root_onset", "Root onset", "When did the root segment start to deviate?"),
    PlaybookStep("evidence_lookup", "Evidence lookup", "Which logged changes line up with the onset?"),
    PlaybookStep("hypothesis_tests", "Hypothesis tests", "Does each candidate survive its holdout?"),
    PlaybookStep("placebo", "Placebo", "Is the deviation unusual for these hours of the week?"),
    PlaybookStep("impact", "Impact", "What does it cost against the expectation?"),
    PlaybookStep("planner", "Planner hypotheses", "What else could explain the remainder?"),
    PlaybookStep("verdict", "Verdict", "What is known, and how sure is it?"),
)
_BY_ID = {s.id: s for s in STEPS}

_BY_KIND_TOOL: dict[tuple[str, str], str] = {
    ("freshness", "check_freshness"): "data_freshness",
    ("identities", "check_identities"): "identities",
    ("calendar", "list_events"): "planned_events",
    ("decompose", "decompose_formula"): "exact_split",
    ("decompose", "mix_rate_split"): "mix_vs_rate",
    ("segment", "segment_search"): "segment_search",
    ("segment", "get_series"): "root_onset",
    ("events", "list_events"): "evidence_lookup",
    ("holdout", "holdout_check"): "hypothesis_tests",
    ("holdout", "placebo_test"): "placebo",
    ("impact", "decompose_formula"): "impact",
    ("impact", "counterfactual_impact"): "impact",
    ("verdict", "verdict"): "verdict",
}
_BY_KIND = {
    "freshness": "data_freshness",
    "identities": "identities",
    "calendar": "planned_events",
    "decompose": "exact_split",
    "segment": "segment_search",
    "events": "evidence_lookup",
    "holdout": "hypothesis_tests",
    "impact": "impact",
    "verdict": "verdict",
}


@dataclass(frozen=True)
class Playbook:
    id: str
    name: str

    def step_for(self, kind: str, tool: str, data: dict[str, Any]) -> PlaybookStep:
        ledger = data.get("ledger")
        if isinstance(ledger, dict) and str(ledger.get("hypothesis", {}).get("source", "")).startswith("planner:"):
            return _BY_ID["planner"]
        return _BY_ID[_BY_KIND_TOOL.get((kind, tool)) or _BY_KIND.get(kind, "verdict")]

    def tag(self, kind: str, tool: str, data: dict[str, Any]) -> dict[str, Any]:
        step = self.step_for(kind, tool, data)
        return {
            "id": self.id,
            "name": self.name,
            "step": step.id,
            "label": step.label,
            "question": step.question,
            "index": STEPS.index(step) + 1,
            "of": len(STEPS),
        }

    def run_status(self, done: set[str]) -> list[dict[str, str]]:
        """Every playbook step with `done` or `skipped`, in playbook order."""
        return [{"step": s.id, "label": s.label, "status": "done" if s.id in done else "skipped"} for s in STEPS]


def family(graph: Graph, node_id: str) -> tuple[str, str]:
    """(family id, display name) of the node the anomaly fired on."""
    node = graph.node(node_id)
    tables = {graph.node(p).table for p in (node.numerator, node.denominator) if p} | {node.table}
    if tables & set(ADS_TABLES):
        return "ads", "Ad spend"
    if node_id in TRAFFIC_NODES:
        return "traffic", "Traffic"
    return "revenue", "Revenue"


GENERAL_PLAYBOOK = Playbook(id="general", name="General investigation")


def choose_playbook(graph: Graph, node_id: str, direction: str) -> Playbook:
    fam, label = family(graph, node_id)
    move = "drop" if direction == "down" else "spike"
    return Playbook(id=f"{fam}_{move}", name=f"{label} {move} playbook")
