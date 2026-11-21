"""Planned changes: a logged plan is a reason to look at exactly the segment it names.

Planned changes are budget changes in `log_ad_budgets` (kind ``budget_change``) and calendar entries with a
`planned_uplift` in `log_calendar`. A +40% budget for one advertiser in FR is a few percent of total spend,
so no north star and no single-dimension breakdown ever shows it; its scope says where to look.

From the hour the change takes effect, the watcher tests the step in that segment (see `step_z`):

* against the plain seasonal expectation: the segment moved, so an anomaly opens and the investigator
  decides whether delivery follows the plan (EXPECTED, "didn't wake you") or not;
* against the planned expectation (plain expectation x (1 + planned uplift)): a campaign that delivers far
  below its plan is itself an alert, even when nothing moved.

Plans also change the expectation of every regular look (`relation`): fully for a series inside the
change's scope, and weighted by the baseline share of the scope inside a wider additive series (the whole
advertiser, the whole country, one platform, the total), so once the change is in force nothing pages on it
again. A plan scales its line: every other additive measure of the same fact view in the scope (impressions,
clicks and conversions of a budget line) gets the same expectation uplift, marked `derived`; only the named
node gets the step look.

Plans are not watched themselves (nodes named ``planned_*``, such as planned_spend): they move by design.
Quiet worlds carry no planned changes, so these looks add no tests there.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import numpy as np

from argus.contracts.findings import Segment
from argus.contracts.graph import EdgeKind, Graph, NodeKind
from argus.semantic.runner import Runner

PLAN_PREFIX = "planned_"
BUDGET_LOG = "log_ad_budgets"
CALENDAR_LOG = "log_calendar"


@dataclass(frozen=True)
class PlannedChange:
    """One planned change of one node in one segment, announced by one or more log rows."""

    node: str
    segment: Segment
    start: datetime
    uplift: float | None
    ids: tuple[str, ...] = field(default_factory=tuple)
    end: datetime | None = None
    derived: bool = False
    """Not named by the plan: another measure of the same fact view that the plan scales with it."""

    @property
    def is_plan(self) -> bool:
        """The node is a plan itself (planned_spend): it moves by design and is never watched for the step."""
        return self.node.startswith(PLAN_PREFIX)

    @property
    def key(self) -> tuple[str, tuple[tuple[str, str], ...], datetime]:
        return self.node, tuple(sorted(self.segment.items())), self.start


def _json(value: object) -> dict[str, object]:
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    return dict(value) if isinstance(value, dict) else {}


def _segments(scope: dict[str, object], dims: list[str]) -> list[Segment] | None:
    """Scope -> the segments it names on a node's dims (one per value combination); None if not expressible."""
    if any(d not in dims for d in scope):
        return None
    keys = sorted(scope)
    values: list[list[str]] = []
    for k in keys:
        raw = scope[k]
        values.append([str(v) for v in raw] if isinstance(raw, list) else [str(raw)])
    return [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*values)]


def relation(scope: Segment, segment: Segment) -> Literal["inside", "contains"] | None:
    """How a series' segment relates to a change's scope.

    ``inside``: the segment pins every scope dimension to the scope's value (full uplift);
    ``contains``: the segment leaves a scope dimension open, so part of it is in scope (uplift weighted by
    the share of the scope inside the segment);
    None: they disagree on a shared dimension (the change does not touch the series).
    """
    if any(d in segment and segment[d] != v for d, v in scope.items()):
        return None
    return "inside" if all(d in segment for d in scope) else "contains"


def step_z(z: np.ndarray) -> tuple[float, int]:
    """Stouffer's combination of the per-hour z since the change: sum(z) / sqrt(n), and n.

    The pooled test for a shift at a known time: a +30% step that is z = 3 per hour reaches 5 after three
    hours, while one noisy hour cannot.
    """
    finite = z[np.isfinite(z)]
    if len(finite) == 0:
        return float("nan"), 0
    return float(finite.sum() / math.sqrt(len(finite))), len(finite)


class PlannedChanges:
    """Reads the planned changes visible at `as_of` and maps them onto watched nodes and segments."""

    def __init__(self, runner: Runner, graph: Graph):
        self.runner = runner
        self.graph = graph

    def _watchable(self, node_id: str) -> bool:
        try:
            node = self.graph.node(node_id)
        except KeyError:
            return False
        return node.kind in (NodeKind.ADDITIVE, NodeKind.RATIO)

    def _budget_nodes(self) -> list[str]:
        return sorted(
            {
                e.target
                for e in self.graph.edges
                if e.kind is EdgeKind.EVIDENCE
                and BUDGET_LOG in e.sources
                and self._watchable(e.target)
                and self.graph.node(e.target).kind is NodeKind.ADDITIVE
            }
        )

    def refresh(self, as_of: datetime) -> list[PlannedChange]:
        found: dict[tuple[str, tuple[tuple[str, str], ...], datetime], PlannedChange] = {}

        def add(change: PlannedChange) -> None:
            known = found.get(change.key)
            if known is None:
                found[change.key] = change
                return
            uplift = known.uplift if known.uplift is not None else change.uplift
            ends = [e for e in (known.end, change.end) if e is not None]
            found[change.key] = PlannedChange(
                known.node,
                known.segment,
                known.start,
                uplift,
                tuple(sorted({*known.ids, *change.ids})),
                min(ends) if ends else None,
            )

        budgets = self.runner.fetch(
            f"SELECT id, ts, kind, scope, advertiser_id, country, daily_budget FROM {BUDGET_LOG} ORDER BY ts, id", as_of
        )
        last_budget: dict[tuple[str, str], float] = {}
        nodes = self._budget_nodes()
        next_ts: dict[int, datetime] = {}  # a budget change is in force until the line's next budget row
        seen: dict[tuple[str, str], int] = {}
        for i, row in enumerate(budgets):
            line = (str(row["advertiser_id"]), str(row["country"]))
            if line in seen:
                next_ts[seen[line]] = row["ts"]
            seen[line] = i
        for i, row in enumerate(budgets):
            line = (str(row["advertiser_id"]), str(row["country"]))
            budget = float(row["daily_budget"]) if row["daily_budget"] is not None else None
            before = last_budget.get(line)
            if budget is not None:
                last_budget[line] = budget
            if row["kind"] != "budget_change":
                continue
            uplift = budget / before - 1.0 if budget is not None and before else None
            segment = {"advertiser_id": line[0], "country": line[1]}
            for node_id in nodes:
                if set(segment) <= set(self.graph.node(node_id).dims):
                    add(PlannedChange(node_id, segment, row["ts"], uplift, (str(row["id"]),), next_ts.get(i)))

        calendar = self.runner.fetch(
            f"SELECT id, ts, end_ts, scope, planned_uplift FROM {CALENDAR_LOG} "
            "WHERE planned_uplift IS NOT NULL ORDER BY ts, id",
            as_of,
        )
        for row in calendar:
            scope = _json(row["scope"])
            for node_id, planned in _json(row["planned_uplift"]).items():
                if not self._watchable(node_id) or not isinstance(planned, int | float):
                    continue
                for segment in _segments(scope, self.graph.node(node_id).dims) or []:
                    add(PlannedChange(node_id, segment, row["ts"], float(planned), (str(row["id"]),), row["end_ts"]))
        named = list(found.values())
        for change in named:
            node = self.graph.node(change.node)
            if node.kind is not NodeKind.ADDITIVE or change.is_plan:
                continue
            for other in self.graph.nodes:
                derived = PlannedChange(
                    other.id, change.segment, change.start, change.uplift, change.ids, change.end, derived=True
                )
                if (
                    other.kind is NodeKind.ADDITIVE
                    and other.table == node.table
                    and other.id != node.id
                    and set(change.segment) <= set(other.dims)
                    and derived.key not in found
                ):
                    found[derived.key] = derived
        return sorted(found.values(), key=lambda c: (c.start, c.node, sorted(c.segment.items())))
