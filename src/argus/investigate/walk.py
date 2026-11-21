"""The LMDI walk along the metric graph, made significance-aware.

The exact split says how much of a change each factor carries. It does not say which factor *moved*:
traffic swings a few percent every day, so on a total the `sessions` factor can carry as much as a real
payment fault. The walk therefore follows the largest contribution among the factors that moved beyond
their normal week-to-week spread (|z| >= 3), and only falls back to the plain largest contribution
when no factor is significant (the trail then says the choice is weak).

`hops` turns the flattened factor list back into the path through the graph
(gmv -> orders -> cvr -> payment_success_rate), so the UI can animate the walk hop by hop. Shares of an
intermediate node are the sums of its leaves' shares, which is exact because LMDI is additive across
nested products.
"""

from __future__ import annotations

from dataclasses import dataclass

from argus.contracts.graph import EdgeKind, EdgeStatus, Graph, NodeKind
from argus.graph.store import product_factors

FOLLOW_Z = 3.0


@dataclass(frozen=True)
class FactorView:
    node: str
    contribution: float
    share: float
    z: float | None = None
    rel_change: float | None = None


@dataclass(frozen=True)
class Hop:
    node: str
    children: list[str]
    follow: str


def choose_factor(factors: list[FactorView], change: float, z_min: float = FOLLOW_Z) -> tuple[FactorView, bool]:
    """Largest same-sign contribution among significant factors. Returns (factor, significant)."""
    if not factors:
        raise ValueError("no factors to choose from")
    sign = 1.0 if change >= 0 else -1.0
    same = [f for f in factors if f.contribution * sign > 0]
    strong = [f for f in same if f.z is not None and abs(f.z) >= z_min]
    pool = strong or same or factors
    return max(pool, key=lambda f: abs(f.contribution)), bool(strong)


def formula_children(graph: Graph, node_id: str) -> list[str] | None:
    """Sources of the node's product formula (same rule as `product_factors`), or None for a leaf."""
    for edge in graph.edges_into(node_id, EdgeKind.FORMULA):
        if len(edge.sources) > 1 and edge.expr == " * ".join(edge.sources) and edge.status is not EdgeStatus.BROKEN:
            return list(edge.sources)
    return None


def leaves(graph: Graph, node_id: str) -> list[str]:
    return product_factors(graph, node_id) or [node_id]


def hops(graph: Graph, root: str, leaf: str) -> list[Hop]:
    """Path of product-formula hops from `root` down to the subtree that ends in `leaf`."""
    path: list[Hop] = []
    node = root
    seen = {root}
    while node != leaf:
        children = formula_children(graph, node)
        if not children:
            break
        nxt = next((c for c in children if leaf in leaves(graph, c)), None)
        if nxt is None or nxt in seen:
            break
        path.append(Hop(node=node, children=children, follow=nxt))
        seen.add(nxt)
        node = nxt
    return path


def subtree_share(graph: Graph, node_id: str, shares: dict[str, float]) -> float:
    return sum(shares.get(leaf, 0.0) for leaf in leaves(graph, node_id))


@dataclass(frozen=True)
class Decomposition:
    """One exact way to write the node as a product.

    * a product formula edge of the graph (`orders = sessions * cvr`), or
    * a ratio identity: every ratio node R = N / D gives N = D * R exactly. The seed graph has no formula
      `ad_spend = planned_spend * pacing_ratio`, but `pacing_ratio` defines it, and it is the split that
      compares delivery with its plan.
    """

    label: str
    top: list[str]
    leaves: list[str]


def decompositions(graph: Graph, node_id: str) -> list[Decomposition]:
    out: list[Decomposition] = []
    formula = formula_children(graph, node_id)
    if formula:
        edge = next(
            e.id
            for e in graph.edges_into(node_id, EdgeKind.FORMULA)
            if list(e.sources) == formula and e.status is not EdgeStatus.BROKEN
        )
        out.append(Decomposition(f"formula {edge}", formula, [leaf for c in formula for leaf in leaves(graph, c)]))
    for ratio in graph.nodes:
        if ratio.kind is not NodeKind.RATIO or ratio.numerator != node_id or not ratio.denominator:
            continue
        top = [ratio.denominator, ratio.id]
        if formula and set(top) == set(formula):
            continue
        out.append(Decomposition(f"identity via {ratio.id}", top, [leaf for c in top for leaf in leaves(graph, c)]))
    return out


def decomposition_hops(graph: Graph, root: str, decomposition: Decomposition, leaf: str) -> list[Hop]:
    follow = next((c for c in decomposition.top if leaf in leaves(graph, c)), None)
    if follow is None:
        return []
    return [Hop(node=root, children=list(decomposition.top), follow=follow), *hops(graph, follow, leaf)]


def has_direct_evidence(graph: Graph, node_id: str) -> bool:
    """Does the graph attach a log of state changes to this node (where a first cause can be checked)?"""
    return bool(graph.edges_into(node_id, EdgeKind.EVIDENCE))


def evidence_logs(graph: Graph, node_id: str) -> list[str]:
    """Logs attached to the node, and for a ratio also to its numerator and denominator: whatever can move
    a part of a ratio can move the ratio."""
    node = graph.node(node_id)
    ids = [node_id, *(p for p in (node.numerator, node.denominator) if p)]
    return sorted({src for i in ids for e in graph.edges_into(i, EdgeKind.EVIDENCE) for src in e.sources})
