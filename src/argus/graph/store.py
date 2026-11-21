"""Load the seed graph, keep the changelog, export graph.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from argus.contracts.graph import (
    Edge,
    EdgeKind,
    EdgeStatus,
    EdgeTest,
    EdgeTestKind,
    Graph,
    GraphChange,
    Node,
    Provenance,
)
from argus.semantic.compile import render_node_sql

REPO = Path(__file__).resolve().parents[3]
SEED_GRAPH = REPO / "graph" / "seed_graph.yml"

IDENTITY_TEST = EdgeTest(kind=EdgeTestKind.IDENTITY_RESIDUAL, window_days=28, median_max=0.005, p95_max=0.02)
CHILDREN_SUM_TEST = EdgeTest(kind=EdgeTestKind.CHILDREN_SUM, window_days=28, max_rel_err=0.005)
LAG_TEST = EdgeTest(kind=EdgeTestKind.LAGGED_CORR_BH, window_days=28, alpha=0.05, lag_hours=[0, 1, 2, 3, 4, 5, 6])
ONSET_TEST = EdgeTest(kind=EdgeTestKind.ONSET_ALIGNMENT, window_days=28)


def _edge(raw: dict[str, Any]) -> Edge:
    kind = EdgeKind(raw["kind"])
    default_status = {
        EdgeKind.FORMULA: EdgeStatus.VALID,
        EdgeKind.BREAKDOWN: EdgeStatus.VALID,
        EdgeKind.CAUSE: EdgeStatus.PROBATION,
        EdgeKind.EVIDENCE: EdgeStatus.SUPPORTED,
    }[kind]
    test = {
        EdgeKind.FORMULA: IDENTITY_TEST,
        EdgeKind.BREAKDOWN: CHILDREN_SUM_TEST,
        EdgeKind.CAUSE: LAG_TEST,
        EdgeKind.EVIDENCE: ONSET_TEST,
    }[kind]
    data = {"status": default_status, "test": test, "provenance": Provenance.SEED, **raw}
    edge = Edge.model_validate(data)
    return edge.model_copy(update={"weight": 0.0 if edge.status is EdgeStatus.PROPOSED else edge.weight})


def load_seed_graph(path: Path = SEED_GRAPH) -> Graph:
    raw = yaml.safe_load(path.read_text())
    nodes = [Node.model_validate(n) for n in raw["nodes"]]
    edges = [_edge(e) for e in raw["edges"]]
    for node_id, dims in (raw.get("breakdowns") or {}).items():
        for dim in dims:
            edges.append(_edge({"id": f"b_{node_id}_{dim}", "kind": "breakdown", "target": node_id, "dim": dim}))
    graph = Graph(version=raw.get("version", 1), nodes=nodes, edges=edges, logs=raw.get("logs", []))
    rendered = [n.model_copy(update={"sql": render_node_sql(graph, n)}) for n in graph.nodes]
    return graph.model_copy(update={"nodes": rendered})


def product_factors(graph: Graph, node_id: str, _seen: frozenset[str] = frozenset()) -> list[str] | None:
    """Factors of the node's product formula (for LMDI), flattened through nested product formulas.

    `orders = sessions * cvr` and `cvr = view_rate * ... * payment_success_rate` flatten to
    sessions, view_rate, cart_rate, checkout_rate, attempt_rate, payment_success_rate.
    Single-source identities (orders = payment_successes) are checks, not decompositions.
    """
    candidates = [
        e
        for e in graph.edges_into(node_id, EdgeKind.FORMULA)
        if len(e.sources) > 1 and e.expr == " * ".join(e.sources) and e.status is not EdgeStatus.BROKEN
    ]
    if not candidates or node_id in _seen:
        return None
    factors: list[str] = []
    for source in candidates[0].sources:
        nested = product_factors(graph, source, _seen | {node_id})
        factors.extend(nested or [source])
    return factors


class Changelog:
    """Append-only graph changelog (state/graph_changelog.jsonl when persisted)."""

    def __init__(self) -> None:
        self.entries: list[GraphChange] = []

    def append(self, **fields: Any) -> GraphChange:
        change = GraphChange(seq=len(self.entries) + 1, **fields)
        self.entries.append(change)
        return change

    def write(self, path: Path) -> None:
        path.write_text("".join(json.dumps(c.model_dump(mode="json")) + "\n" for c in self.entries))


def write_graph(graph: Graph, path: Path) -> None:
    path.write_text(json.dumps(graph.model_dump(mode="json"), indent=2) + "\n")
