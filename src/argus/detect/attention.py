"""Attention budget: which series the watcher looks at in a tick.

    attention = business_weight x surprise x data_confidence x novelty

A unit of attention is a node's total or one breakdown of a node (every slice of one dimension).
North-star totals and the series of open anomalies are always watched; every other unit competes for
`budget` looks per tick.

* business_weight: 1.0 for a north-star node, 0.7 for a direct driver of one (a formula source, or the
  numerator or denominator of a north-star ratio), 0.5 otherwise. A breakdown inherits its node's weight.
* surprise: 1 + min(|z|, 8), where |z| is the larger of the unit's own last |z| and the |z| of its parent
  in this tick (the node's total for a breakdown, the node it drives for a total). Surprise flows down the
  graph, so a north star that moves pulls attention onto its breakdowns and drivers in the same tick.
* data_confidence: completeness of the unit's source tables for the scored hour (0 while pending).
* novelty: 1 - exp(-hours since the last look / 6), 1 when never looked at, halved while the node already
  has an open anomaly (it is being handled).

The budget is also a false-alarm control: every look is a statistical test, and testing hundreds of slices
every hour would page on noise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from argus.contracts.events import AttentionPayload
from argus.contracts.graph import EdgeKind, EdgeStatus, Graph, NodeKind

SURPRISE_CAP = 8.0
NOVELTY_HOURS = 6.0
WEIGHT_NORTH_STAR = 1.0
WEIGHT_DRIVER = 0.7
WEIGHT_OTHER = 0.5


@dataclass(frozen=True)
class Unit:
    node: str
    dims: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return self.node if not self.dims else f"{self.node}[{','.join(self.dims)}]"

    @property
    def is_total(self) -> bool:
        return not self.dims


@dataclass(frozen=True)
class Terms:
    weight: float
    surprise: float
    confidence: float
    novelty: float

    @property
    def score(self) -> float:
        return self.weight * self.surprise * self.confidence * self.novelty


def watchable_nodes(graph: Graph) -> list[str]:
    return [n.id for n in graph.nodes if n.kind in (NodeKind.ADDITIVE, NodeKind.RATIO) and n.state != "retired"]


def candidate_units(graph: Graph) -> list[Unit]:
    """Every node total plus every breakdown edge that is still trusted."""
    watchable = set(watchable_nodes(graph))
    units = [Unit(n) for n in watchable_nodes(graph)]
    for edge in graph.edges:
        if (
            edge.kind is EdgeKind.BREAKDOWN
            and edge.dim
            and edge.target in watchable
            and edge.status not in (EdgeStatus.BROKEN, EdgeStatus.PROPOSED)
        ):
            units.append(Unit(edge.target, (edge.dim,)))
    return units


def drives(graph: Graph) -> dict[str, set[str]]:
    """node -> nodes it drives (formula targets, and ratios that use it as numerator or denominator)."""
    out: dict[str, set[str]] = {n.id: set() for n in graph.nodes}
    for edge in graph.edges:
        if edge.kind is EdgeKind.FORMULA and edge.status is not EdgeStatus.BROKEN:
            for src in edge.sources:
                out.setdefault(src, set()).add(edge.target)
    for node in graph.nodes:
        for part in (node.numerator, node.denominator):
            if part:
                out.setdefault(part, set()).add(node.id)
    return out


class AttentionBudget:
    """Keeps when each unit was last looked at and what it showed, and picks the next looks."""

    def __init__(self, graph: Graph, budget: int = 6):
        self.graph = graph
        self.budget = budget
        self.units = candidate_units(graph)
        self._drives = drives(graph)
        north = {n.id for n in graph.north_stars()}
        self._weight: dict[str, float] = {}
        for node_id in watchable_nodes(graph):
            if node_id in north:
                self._weight[node_id] = WEIGHT_NORTH_STAR
            elif self._drives.get(node_id, set()) & north:
                self._weight[node_id] = WEIGHT_DRIVER
            else:
                self._weight[node_id] = WEIGHT_OTHER
        self.last_look: dict[Unit, datetime] = {}
        self.last_abs_z: dict[Unit, float] = {}

    def weight(self, node_id: str) -> float:
        return self._weight.get(node_id, WEIGHT_OTHER)

    def mark(self, unit: Unit, hour: datetime, max_abs_z: float | None) -> None:
        self.last_look[unit] = hour
        if max_abs_z is not None and math.isfinite(max_abs_z):
            self.last_abs_z[unit] = max_abs_z

    def terms(
        self,
        unit: Unit,
        hour: datetime,
        z_now: dict[str, float],
        confidence: float,
        open_nodes: set[str],
    ) -> Terms:
        own = self.last_abs_z.get(unit, 0.0)
        if unit.is_total:
            parents = [z_now.get(p, self.last_abs_z.get(Unit(p), 0.0)) for p in self._drives.get(unit.node, set())]
            parent = max(parents, default=0.0)
        else:
            parent = z_now.get(unit.node, self.last_abs_z.get(Unit(unit.node), 0.0))
        surprise = 1.0 + min(max(own, parent), SURPRISE_CAP)
        seen = self.last_look.get(unit)
        if seen is None:
            novelty = 1.0
        else:
            idle = max((hour - seen) / timedelta(hours=1), 0.0)
            novelty = 1.0 - math.exp(-idle / NOVELTY_HOURS)
        if unit.node in open_nodes:
            novelty *= 0.5
        return Terms(self.weight(unit.node), surprise, confidence, novelty)

    def choose(self, scores: dict[Unit, Terms]) -> list[Unit]:
        ranked = sorted((u for u, t in scores.items() if t.score > 0), key=lambda u: (-scores[u].score, u.key))
        return ranked[: self.budget]

    @staticmethod
    def payload(scores: dict[Unit, Terms]) -> AttentionPayload:
        return AttentionPayload(
            scores={u.key: round(t.score, 4) for u, t in sorted(scores.items(), key=lambda x: x[0].key)}
        )
