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

from argus.contracts.graph import EdgeKind, EdgeStatus, Graph
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
