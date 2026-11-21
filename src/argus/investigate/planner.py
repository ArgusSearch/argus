"""Planner interface: who proposes the next hypothesis when the fixed opening leaves a remainder.

The planner only *proposes*: typed checks from the C6 menu with a prediction and an expected outcome.
The investigator runs every check itself and the ledger decides validated / refuted / inconclusive,
so a planner can never produce a number or a verdict.

An LLM planner (lane `llm`) implements `Planner`: it renders `PlannerContext` into its prompt, asks the
model for JSON only and returns `proposals_from_json(reply, source=...)`, which drops every proposal
that names an unknown tool, fills the input model wrongly or expects an outcome the tool cannot have.
Without a planner (or without an API key) the remainder is reported as UNEXPLAINED.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from argus.contracts.findings import Anomaly, EvidenceRef, Segment, Window
from argus.investigate.ledger import OUTCOMES, Hypothesis, LedgerEntry

MAX_PROPOSALS = 3


class PlannerContext(BaseModel):
    """Everything a planner may see: the case so far, the graph neighbourhood and the tool menu."""

    model_config = ConfigDict(extra="forbid")

    anomaly: Anomaly
    focus: str = Field(description="node the walk ended on")
    segment: Segment = Field(description="root segment found so far ({} = not localised)")
    window: Window
    explained_share: float
    neighbourhood: list[str] = Field(description="node ids one formula, cause or evidence hop from the focus")
    edges: list[dict[str, Any]] = Field(description="id, kind, target, sources, status of those edges")
    events: list[EvidenceRef] = Field(default_factory=list, description="log entries already considered")
    tried: list[LedgerEntry] = Field(default_factory=list, description="hypotheses already tested")
    tools: dict[str, list[str]] = Field(default_factory=lambda: {k: list(v) for k, v in OUTCOMES.items()})
    budget: int = Field(description="how many hypotheses may still be tested")


class Planner(Protocol):
    name: str
    uses_llm: bool

    def propose(self, context: PlannerContext) -> list[Hypothesis]: ...


class NullPlanner:
    """The default: no proposals, the remainder stays UNEXPLAINED."""

    name = "none"
    uses_llm = False

    def propose(self, context: PlannerContext) -> list[Hypothesis]:
        return []


class ScriptedPlanner:
    """Fixed proposals (tests, replays of a recorded LLM session)."""

    uses_llm = False

    def __init__(self, hypotheses: list[Hypothesis], name: str = "scripted"):
        self.name = name
        self.hypotheses = hypotheses
        self.calls = 0

    def propose(self, context: PlannerContext) -> list[Hypothesis]:
        self.calls += 1
        return [h.model_copy(update={"source": f"planner:{self.name}"}) for h in self.hypotheses]


def proposals_from_json(text: str, source: str, limit: int = MAX_PROPOSALS) -> tuple[list[Hypothesis], list[str]]:
    """Parse an LLM reply (a JSON list of hypotheses, or {"hypotheses": [...]}) into typed proposals.

    Returns (accepted, rejection reasons). Never raises on bad model output: a planner that talks
    nonsense simply contributes nothing.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        return [], [f"not JSON: {err.msg}"]
    if isinstance(data, dict):
        data = data.get("hypotheses", [])
    if not isinstance(data, list):
        return [], ["expected a JSON list of hypotheses"]
    accepted: list[Hypothesis] = []
    rejected: list[str] = []
    for i, item in enumerate(data):
        if len(accepted) == limit:
            rejected.append(f"#{i}: over the limit of {limit} hypotheses")
            continue
        if not isinstance(item, dict):
            rejected.append(f"#{i}: not an object")
            continue
        try:
            accepted.append(Hypothesis.model_validate({**item, "source": source}))
        except ValidationError as err:
            first = err.errors()[0]
            rejected.append(f"#{i}: {first.get('msg', 'invalid')}")
    return accepted, rejected
