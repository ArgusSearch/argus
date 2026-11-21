"""C3 metric graph: nodes, typed edges, edge tests, changes and placement certificates.

`graph.json` is a serialized `Graph`. Every status change is a `GraphChange` appended to the changelog.

Node kinds:

* `additive`: a SUM over one fact view (`table`, `measure`). Parts sum to the whole.
* `ratio`: `numerator / denominator`, both additive node ids. Stored separately so it can be decomposed.
* `derived`: arithmetic `expr` over node ids that is neither of the above (reserved, for example margins).

Edge kinds and the reasoning each one supports:

| kind      | meaning                                | test                         | used for                 |
|-----------|----------------------------------------|------------------------------|--------------------------|
| formula   | target = expr(sources), exact          | identity_residual            | LMDI split of a change   |
| breakdown | target split by one dimension          | children_sum                 | segment search           |
| cause     | source can drive target with a lag     | lagged_corr_bh               | next hop, always "maybe" |
| evidence  | a log of state changes attached to a node | onset_alignment           | first-cause candidates   |

Status values: VALID (formula, breakdown passed), SUPPORTED (cause, evidence passed), PROBATION (new or
ambiguous, half weight), PROPOSED (LLM-only suggestion, zero weight), BROKEN (test stopped passing).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NodeKind(StrEnum):
    ADDITIVE = "additive"
    RATIO = "ratio"
    DERIVED = "derived"


class EdgeKind(StrEnum):
    FORMULA = "formula"
    BREAKDOWN = "breakdown"
    CAUSE = "cause"
    EVIDENCE = "evidence"


class EdgeStatus(StrEnum):
    VALID = "VALID"
    SUPPORTED = "SUPPORTED"
    PROBATION = "PROBATION"
    PROPOSED = "PROPOSED"
    BROKEN = "BROKEN"


class Provenance(StrEnum):
    SEED = "seed"
    LINEAGE = "lineage"
    ARITHMETIC = "arithmetic"
    LLM = "llm"
    LEARNED = "learned"


class EdgeTestKind(StrEnum):
    IDENTITY_RESIDUAL = "identity_residual"
    CHILDREN_SUM = "children_sum"
    LAGGED_CORR_BH = "lagged_corr_bh"
    ONSET_ALIGNMENT = "onset_alignment"


Unit = Literal["count", "eur", "share", "ratio", "eur_per_unit"]
NodeState = Literal["watching", "probation", "proposed", "retired"]

STATUS_WEIGHT: dict[EdgeStatus, float] = {
    EdgeStatus.VALID: 1.0,
    EdgeStatus.SUPPORTED: 1.0,
    EdgeStatus.PROBATION: 0.5,
    EdgeStatus.PROPOSED: 0.0,
    EdgeStatus.BROKEN: 0.0,
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Node(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    description: str
    kind: NodeKind
    unit: Unit
    north_star: bool = False
    dims: list[str] = Field(description="dimensions this node can be broken down by")
    table: str | None = Field(default=None, description="additive: the fact view")
    measure: str | None = Field(default=None, description="additive: the column that is summed")
    numerator: str | None = Field(default=None, description="ratio: additive node id")
    denominator: str | None = Field(default=None, description="ratio: additive node id")
    expr: str | None = Field(default=None, description="derived: arithmetic over node ids")
    sql: str | None = Field(default=None, description="C2 SQL form of the node, for display and receipts")
    source: str = Field(default="seed", description="'seed' or the metrics/*.yml file it came from")
    state: NodeState = "watching"

    @model_validator(mode="after")
    def _kind_fields(self) -> Node:
        if self.kind is NodeKind.ADDITIVE and not (self.table and self.measure):
            raise ValueError(f"additive node {self.id} needs table and measure")
        if self.kind is NodeKind.RATIO and not (self.numerator and self.denominator):
            raise ValueError(f"ratio node {self.id} needs numerator and denominator")
        if self.kind is NodeKind.DERIVED and not self.expr:
            raise ValueError(f"derived node {self.id} needs expr")
        return self


class LogSource(_Strict):
    """A log table that evidence edges attach to nodes (rendered as a special source in the UI)."""

    id: str = Field(description="log view name, e.g. log_deploys")
    label: str
    description: str


class EdgeTest(_Strict):
    kind: EdgeTestKind
    window_days: int = 28
    median_max: float | None = Field(default=None, description="identity_residual: max median relative residual")
    p95_max: float | None = Field(default=None, description="identity_residual: max p95 relative residual")
    max_rel_err: float | None = Field(default=None, description="children_sum: max relative error per hour")
    alpha: float | None = Field(default=None, description="lagged_corr_bh: false discovery rate")
    lag_hours: list[int] | None = Field(default=None, description="lagged_corr_bh: lags to test")


class EdgeTestResult(_Strict):
    ran_at: datetime = Field(description="as_of the test ran at")
    passed: bool | None = Field(description="None when the test kind is not implemented yet")
    median_rel: float | None = None
    p95_rel: float | None = None
    max_rel_err: float | None = None
    hours: int = 0
    receipts: list[str] = Field(default_factory=list)
    note: str = ""


class Edge(_Strict):
    id: str
    kind: EdgeKind
    target: str = Field(description="node id the edge points to (the parent / the effect)")
    sources: list[str] = Field(
        default_factory=list,
        description="formula and cause: node ids; evidence: log ids; breakdown: empty",
    )
    expr: str | None = Field(default=None, description="formula: target = expr over source node ids")
    dim: str | None = Field(default=None, description="breakdown: the dimension")
    lag_hours: list[int] | None = Field(default=None, description="cause: plausible lags")
    filter: dict[str, list[str]] | None = Field(default=None, description="evidence: e.g. {'kind': ['deploy']}")
    status: EdgeStatus
    weight: float = 1.0
    provenance: Provenance = Provenance.SEED
    test: EdgeTest | None = None
    last_test: EdgeTestResult | None = None
    note: str = ""

    @model_validator(mode="after")
    def _kind_fields(self) -> Edge:
        if self.kind is EdgeKind.FORMULA and not (self.expr and self.sources):
            raise ValueError(f"formula edge {self.id} needs expr and sources")
        if self.kind is EdgeKind.BREAKDOWN and not self.dim:
            raise ValueError(f"breakdown edge {self.id} needs dim")
        if self.kind in (EdgeKind.CAUSE, EdgeKind.EVIDENCE) and not self.sources:
            raise ValueError(f"{self.kind} edge {self.id} needs sources")
        return self


class Graph(_Strict):
    version: int = 1
    nodes: list[Node]
    edges: list[Edge]
    logs: list[LogSource] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references(self) -> Graph:
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("duplicate node ids")
        log_ids = {log.id for log in self.logs}
        for node in self.nodes:
            for ref in (node.numerator, node.denominator):
                if ref is not None and ref not in ids:
                    raise ValueError(f"node {node.id} references unknown node {ref}")
        edge_ids = set()
        for edge in self.edges:
            if edge.id in edge_ids:
                raise ValueError(f"duplicate edge id {edge.id}")
            edge_ids.add(edge.id)
            if edge.target not in ids:
                raise ValueError(f"edge {edge.id} targets unknown node {edge.target}")
            known = log_ids if edge.kind is EdgeKind.EVIDENCE else ids
            for src in edge.sources:
                if src not in known:
                    raise ValueError(f"edge {edge.id} has unknown source {src}")
            if edge.kind is EdgeKind.BREAKDOWN:
                target = next(n for n in self.nodes if n.id == edge.target)
                if edge.dim not in target.dims:
                    raise ValueError(f"edge {edge.id}: {edge.target} has no dimension {edge.dim}")
        return self

    def node(self, node_id: str) -> Node:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)

    def edge(self, edge_id: str) -> Edge:
        for edge in self.edges:
            if edge.id == edge_id:
                return edge
        raise KeyError(edge_id)

    def edges_into(self, node_id: str, kind: EdgeKind | None = None) -> list[Edge]:
        return [e for e in self.edges if e.target == node_id and (kind is None or e.kind is kind)]

    def north_stars(self) -> list[Node]:
        return [n for n in self.nodes if n.north_star]


class GraphChange(_Strict):
    """One append-only changelog entry (`state/graph_changelog.jsonl`)."""

    seq: int
    sim_ts: datetime
    kind: Literal["node_added", "edge_added", "edge_status", "node_retired", "test_run"]
    node: str | None = None
    edge: str | None = None
    old_status: EdgeStatus | None = None
    new_status: EdgeStatus | None = None
    reason: str = ""
    receipts: list[str] = Field(default_factory=list)


class Certificate(_Strict):
    """Placement certificate for an onboarded metric (lane G fills this in Stage 2)."""

    metric: str
    placed_as: Literal["EXACT", "NEW_DIMENSION", "ALIAS", "AMBIGUOUS", "REJECTED"]
    summary: str
    tried: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)
    uncertain: list[str] = Field(default_factory=list)
    edges: list[str] = Field(default_factory=list)
    receipts: list[str] = Field(default_factory=list)
