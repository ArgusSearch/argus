"""Machine-readable boundaries for monitoring, investigation and human decisions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from argus.contracts.graph import EdgeStatus, Graph
from argus.narrator.playbooks import PlaybookDefinition, playbook_registry


class Rule(BaseModel):
    id: str
    when: str
    behavior: str


class ProbationCase(BaseModel):
    kind: Literal["node", "edge"]
    id: str
    status: Literal["PROBATION"] = "PROBATION"


class Autonomy(BaseModel):
    decides_alone: tuple[Rule, ...]
    asks_first: tuple[Rule, ...]
    probation: list[ProbationCase]
    playbooks: tuple[PlaybookDefinition, ...]


_DECIDES_ALONE = (
    Rule(
        id="monitor",
        when="A simulated hour is ready for monitoring.",
        behavior="Check freshness and score available metrics against their expectations.",
    ),
    Rule(
        id="defer_late_data",
        when="Required source data is incomplete.",
        behavior="Record a data issue and wait for complete data before scoring dependent metrics.",
    ),
    Rule(
        id="investigate",
        when="A metric crosses its opening rule.",
        behavior="Run the appropriate investigation, test candidates and record the supported verdict.",
    ),
    Rule(
        id="hold_alert",
        when="The change follows a plan or is a symptom of an existing incident.",
        behavior="Record a note and suppress a separate incident.",
    ),
    Rule(
        id="retest_graph",
        when="A scheduled graph check is due.",
        behavior="Test formula and breakdown edges against the data and update their status.",
    ),
    Rule(
        id="manage_incident",
        when="An investigation warrants an incident or the root segment returns to normal.",
        behavior="File, deduplicate, monitor, reopen and resolve incidents by their lifecycle rules.",
    ),
)

_ASKS_FIRST = (
    Rule(
        id="approve_action",
        when="A suggested action requires approval.",
        behavior="Present the recommendation for human approval before applying it.",
    ),
    Rule(
        id="review_probation",
        when="A graph placement is ambiguous or an edge is supported only by correlation.",
        behavior="Keep it on PROBATION and ask for stronger evidence or a human decision before promotion.",
    ),
    Rule(
        id="review_ambiguous_cause",
        when="The verdict is HYPOTHESIS or UNEXPLAINED.",
        behavior="Keep the uncertainty visible and ask for evidence before treating the cause as confirmed.",
    ),
)


def build_autonomy(graph: Graph) -> Autonomy:
    probation = [
        ProbationCase(kind="node", id=node.id)
        for node in sorted(graph.nodes, key=lambda n: n.id)
        if node.state == "probation"
    ]
    probation.extend(
        ProbationCase(kind="edge", id=edge.id)
        for edge in sorted(graph.edges, key=lambda e: e.id)
        if edge.status is EdgeStatus.PROBATION
    )
    return Autonomy(
        decides_alone=_DECIDES_ALONE,
        asks_first=_ASKS_FIRST,
        probation=probation,
        playbooks=playbook_registry(),
    )
