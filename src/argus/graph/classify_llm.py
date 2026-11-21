"""Edge proposers for metric self-classification: an interface where an LLM (or anything else) suggests edges.

A proposer only proposes. The classifier tests every suggestion like a deterministic candidate: a formula
must pass the identity residual test, a cause must show a BH-significant lagged correlation, and a suggestion
that cannot be tested here (a log as the cause) enters the graph only as PROPOSED with zero weight.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from argus.contracts.graph import Graph, Node
from argus.contracts.metric import MetricDefinition


class EdgeSuggestion(BaseModel):
    """A typed edge a proposer (for example an LLM) suggests. Only a proposal: the tests decide."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["formula", "cause"]
    target: str
    sources: list[str] = Field(min_length=1)
    expr: str | None = Field(default=None, description="formula: arithmetic over the sources (default: product)")
    lag_hours: list[int] | None = Field(default=None, description="cause: lags at which the source leads")
    why: str = ""


class SuggestionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edges: list[EdgeSuggestion]


@dataclass(frozen=True)
class ProposalContext:
    metric: MetricDefinition
    node: Node
    graph: Graph
    """The graph with the proposed node already in it."""


class EdgeProposer(Protocol):
    name: str

    def propose(self, context: ProposalContext) -> list[EdgeSuggestion]: ...


class LlmProposer:
    """Asks a language model for typed edges; `complete` is any prompt -> reply function (JSON reply).

    The model never decides. Every suggestion is tested like a deterministic candidate, and one that cannot
    be tested here (for example a log as the source) enters the graph only as PROPOSED with zero weight.
    """

    name = "llm"

    def __init__(self, complete: Callable[[str], str]):
        self.complete = complete

    def prompt(self, context: ProposalContext) -> str:
        new = context.node
        nodes = "\n".join(
            f"- {n.id} ({n.kind}, {n.unit}): {n.description}" for n in context.graph.nodes if n is not new
        )
        logs = "\n".join(f"- {log.id}: {log.description}" for log in context.graph.logs)
        return (
            "You place a new metric in a typed metric graph. Suggest edges that connect it to existing nodes.\n"
            "formula: target = expr over source node ids (an exact arithmetic identity, + - * / only).\n"
            "cause: a source node or log that can drive the target with a lag in hours (a mechanism).\n"
            'Reply with JSON only: {"edges": [{"kind": "formula"|"cause", "target": id, "sources": [ids], '
            '"expr": str|null, "lag_hours": [int]|null, "why": str}]}\n\n'
            f"New metric {new.id} ({new.kind}, {new.unit}): {context.metric.description}\n"
            f"SQL:\n{context.metric.sql}\n\nExisting nodes:\n{nodes}\n\nLogs:\n{logs}\n"
        )

    def propose(self, context: ProposalContext) -> list[EdgeSuggestion]:
        reply = re.sub(r"^```(?:json)?\s*|\s*```$", "", self.complete(self.prompt(context)).strip())
        try:
            return SuggestionBatch.model_validate(json.loads(reply)).edges
        except (json.JSONDecodeError, ValidationError) as err:
            raise ValueError(f"reply is not a valid suggestion batch: {err}") from err
