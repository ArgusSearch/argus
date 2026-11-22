"""Graph extension at run time: a new metric (C2) places itself in the running graph, live or from a recording.

`classify` decides where a metric belongs and proves it; this module makes that reachable while Argus runs:

* `GraphExtension.place` runs the classifier against the live world (`LiveSource`) and swaps the placed graph
  into the runtime the same way its daily edge re-test does, so the next re-test covers the new edges too.
  The placement's changelog and edge tests go onto the event stream as C5 `graph_changed` / `edge_status`.
* A replay has no world. It serves the recorded placement of the demo pack (`fixtures/graph_extension/`),
  matched by name and SQL, and adds the recorded node and edges to the replayed graph. Replay owns the event
  seq space, so nothing is published there; clients read `GET /graph/metrics` (its `version` moves).
* A local replay restart resets its graph and placements. Public deployments apply recorded placements as
  visitor overlays that expire with the operator session.

Every result is a `PlacementResult`: the verdict, the certificate, every candidate edge with its lifecycle and
test, the repair diff of a fan-out, the before/after cards and the receipts of every query the placement ran.

Record the demo pack (re-run after changing the classifier or the world):
`uv run python -m argus.graph.extension record --world runs/s4-1/world.duckdb`
(`make world SCENARIO=s4 SEED=1` first). Onboard it into a running API:
`uv run python -m argus.graph.extension post fixtures/graph_extension/metrics/*.yml`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from argus.contracts.events import Event
from argus.contracts.findings import Receipt
from argus.contracts.graph import Certificate, Edge, EdgeTestResult, Graph, GraphChange, Node
from argus.contracts.metric import MetricDefinition, load_metric
from argus.graph.classify import PlacedAs, Placement, classify
from argus.graph.classify_cards import Card, placement_cards, to_events
from argus.graph.store import REPO, Changelog, load_seed_graph
from argus.semantic.runner import Runner

if TYPE_CHECKING:
    from argus.api.hub import EventHub
    from argus.runtime.loop import Runtime

RECORDING = REPO / "fixtures" / "graph_extension"
"""The recorded demo pack: `metrics/*.yml` (placed in file order) and `placements.json`."""
RECORDED_RECEIPT_PREFIX = "gx-"
"""Recorded receipt ids are prefixed so they never collide with the receipts of the replayed run."""

Lifecycle = Literal["proposed", "tested", "accepted", "rejected"]


class PlacementError(RuntimeError):
    """The placement cannot run here (409): no world and no recording, or a missing prerequisite."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CandidateView(_Strict):
    """One candidate edge and what happened to it: tested, accepted into the graph, kept as alternative or rejected."""

    edge: Edge
    reads: str = Field(description="the edge in words, e.g. 'cost_per_impression = ctr * cpc'")
    lifecycle: Lifecycle
    why: str = Field(description="why it was proposed")
    verdict: str = Field(description="the test outcome and the decision taken on it")
    proposed_by: str = ""
    result: EdgeTestResult | None = None


class RepairView(_Strict):
    """A join fan-out: how far the SQL as written is off, and the per-table form that fixes it."""

    factor: float
    sql: str
    diff: str


class PlacementResult(_Strict):
    """Where a metric landed in the graph, and the proof (`GET /graph/metrics/{name}`)."""

    metric: MetricDefinition
    placed_as: PlacedAs
    summary: str
    definition: str = Field(description="the definition check in one line")
    mode: Literal["live", "recorded"]
    world: str = Field(description="the world the classifier ran on, e.g. 'S4 world, seed 1'")
    as_of: datetime = Field(description="data cut: the 28 complete days before it are the test window")
    certificate: Certificate
    node: Node | None = Field(default=None, description="the new node; None for an alias or a rejection")
    alias_of: str | None = None
    alias_scale: float = 1.0
    segment: dict[str, str] = Field(default_factory=dict)
    parents: list[str] = Field(default_factory=list, description="sources of the chosen decomposition of the node")
    alternatives: list[str] = Field(default_factory=list, description="equally simple decompositions kept aside")
    candidates: list[CandidateView] = Field(default_factory=list)
    added_edges: list[Edge] = Field(default_factory=list, description="edges that entered the graph")
    repair: RepairView | None = None
    cards: list[Card] = Field(default_factory=list)
    changes: list[GraphChange] = Field(default_factory=list)
    receipts: list[Receipt] = Field(default_factory=list)
    requires: list[str] = Field(
        default_factory=list, description="nodes placed before this one that the placement relies on"
    )

    @property
    def enters_graph(self) -> bool:
        return self.node is not None or bool(self.added_edges)


class ExtensionState(_Strict):
    """`GET /graph/metrics`: what has been placed in this stream. `version` moves with every placement."""

    mode: Literal["live", "replay"]
    stream: str
    version: int
    placements: list[PlacementResult]
    recorded: list[MetricDefinition] = Field(
        default_factory=list, description="the recorded demo pack, in order (a replay can place only these)"
    )


# --------------------------------------------------------------------------------------------- results


def _same_metric(a: MetricDefinition, b: MetricDefinition) -> bool:
    def norm(sql: str) -> str:
        return re.sub(r"\s+", " ", sql).strip().rstrip(";").lower()

    return a.name == b.name and norm(a.sql) == norm(b.sql)


def build_result(
    p: Placement,
    receipts: dict[str, Receipt],
    *,
    mode: Literal["live", "recorded"],
    world: str,
    placed_before: Sequence[str] = (),
) -> PlacementResult:
    """The API view of one placement. `receipts` maps receipt ids to receipts (the runner's book)."""
    node_id = p.node.id if p.node else None
    decompositions = [
        c for c in p.candidates if c.edge.kind == "formula" and node_id is not None and c.edge.target == node_id
    ]
    parents = next((list(c.edge.sources) for c in decompositions if c.lifecycle == "accepted"), [])
    alternatives = [c.describe() for c in decompositions if c.lifecycle == "tested"]
    touched = {i for c in p.candidates for i in (c.edge.target, *c.edge.sources)}
    ids = list(dict.fromkeys(p.certificate.receipts))
    return PlacementResult(
        metric=p.metric,
        placed_as=p.placed_as,
        summary=p.certificate.summary,
        definition=p.definition,
        mode=mode,
        world=world,
        as_of=p.as_of,
        certificate=p.certificate,
        node=p.node,
        alias_of=p.alias_of,
        alias_scale=p.alias_scale,
        segment=dict(p.segment),
        parents=parents,
        alternatives=alternatives,
        candidates=[
            CandidateView(
                edge=c.edge,
                reads=c.describe(),
                lifecycle=c.lifecycle.value,
                why=c.why,
                verdict=c.verdict,
                proposed_by=c.proposed_by,
                result=c.result,
            )
            for c in p.candidates
        ],
        added_edges=p.added_edges(),
        repair=RepairView(factor=p.repair.factor, sql=p.repair.sql, diff=p.repair.diff) if p.repair else None,
        cards=placement_cards(p),
        changes=p.changes,
        receipts=[receipts[r] for r in ids if r in receipts],
        requires=[n for n in placed_before if n in touched],
    )


def _prefix_receipts(result: PlacementResult, prefix: str) -> PlacementResult:
    """Rename every receipt id the result mentions (`r12` -> `gx-r12`), everywhere it appears."""

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if k == "receipts" and isinstance(v, list):
                    out[k] = [prefix + r if isinstance(r, str) else walk(r) for r in v]
                else:
                    out[k] = walk(v)
            return out
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    data = walk(result.model_dump(mode="json"))
    for receipt in data["receipts"]:
        receipt["id"] = prefix + receipt["id"]
    return PlacementResult.model_validate(data)


def graph_with(graph: Graph, result: PlacementResult) -> Graph:
    """`graph` plus the node and edges a placement added (edges already present by id are kept as they are)."""
    have_nodes = {n.id for n in graph.nodes}
    have_edges = {e.id for e in graph.edges}
    nodes = [*graph.nodes, *([result.node] if result.node and result.node.id not in have_nodes else [])]
    edges = [*graph.edges, *(e for e in result.added_edges if e.id not in have_edges)]
    return graph.model_copy(update={"nodes": nodes, "edges": edges})


def graph_with_placements(graph: Graph, placements: Sequence[PlacementResult]) -> Graph:
    for placement in placements:
        if placement.enters_graph:
            graph = graph_with(graph, placement)
    return graph


# --------------------------------------------------------------------------------------------- recording


def recorded_metrics(recording: Path = RECORDING) -> list[MetricDefinition]:
    return [load_metric(p) for p in sorted((recording / "metrics").glob("*.yml"))]


def load_recorded(recording: Path = RECORDING) -> list[PlacementResult]:
    path = recording / "placements.json"
    if not path.exists():
        return []
    return [PlacementResult.model_validate(p) for p in json.loads(path.read_text())]


def world_label(world: Path) -> str:
    """'S4 world, seed 1' for runs/s4-1/world.duckdb; the folder name otherwise."""
    m = re.fullmatch(r"([a-z]+\d?)-(\d+)", world.parent.name)
    return f"{m[1].upper()} world, seed {m[2]}" if m else f"world {world.parent.name or world}"


def first_tick(world: Path) -> datetime:
    """The as_of of a live run's first tick: live_start plus the delivery lag (`Runtime.ticks`)."""
    manifest = json.loads((world.parent / "manifest.json").read_text())
    return datetime.fromisoformat(manifest["live_start"]) + timedelta(hours=int(manifest.get("delivery_lag_hours", 2)))


def record(world: Path, out: Path = RECORDING, as_of: datetime | None = None, label: str | None = None) -> list[str]:
    """Place the pack in `out/metrics` on the seed graph against `world` and write `out/placements.json`.

    `as_of` defaults to the first live tick, so the recording equals what a live run places before it ticks.
    """
    as_of = as_of or first_tick(world)
    label = label or world_label(world)
    runner = Runner(world)
    graph = load_seed_graph()
    changelog = Changelog()
    results: list[PlacementResult] = []
    placed: list[str] = []
    try:
        for path in sorted((out / "metrics").glob("*.yml")):
            source = str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)
            p = classify(load_metric(path), graph, runner, as_of, source=source, changelog=changelog)
            graph = p.graph
            result = build_result(p, runner.receipts, mode="recorded", world=label, placed_before=placed)
            results.append(_prefix_receipts(result, RECORDED_RECEIPT_PREFIX))
            if p.node is not None:
                placed.append(p.node.id)
    finally:
        runner.close()
    payload = [r.model_dump(mode="json") for r in results]
    (out / "placements.json").write_text(json.dumps(payload, indent=2) + "\n")
    return [f"{r.metric.name} -> {r.placed_as}" for r in results]


# --------------------------------------------------------------------------------------------- the service


class GraphExtension:
    """Places metrics into the running graph of one API source (live runtime or replay)."""

    def __init__(
        self,
        hub: EventHub,
        mode: Literal["live", "replay"],
        runtime: Runtime | None = None,
        recording: Path = RECORDING,
        *,
        isolated: bool = False,
        recorded: list[PlacementResult] | None = None,
        placement_limit: int | None = None,
    ) -> None:
        self.hub = hub
        self.mode = mode
        self.runtime = runtime
        self.recording = recording
        self.isolated = isolated
        self.placement_limit = placement_limit
        self._lock = threading.Lock()
        self._stream = hub.stream
        self._placements: list[PlacementResult] = []
        self._version = 0
        self._recorded = recorded

    # ------------------------------------------------------------------ read

    def _current(self) -> list[PlacementResult]:
        """Local placements follow the run. Public placements follow the visitor session."""
        if self.hub.stream != self._stream:
            self._stream = self.hub.stream
            if not self.isolated:
                self._placements = []
            self._version += 1
        return self._placements

    def recorded(self) -> list[PlacementResult]:
        if self._recorded is None:
            self._recorded = load_recorded(self.recording)
        return self._recorded

    def state(self) -> ExtensionState:
        with self._lock:
            placements = list(self._current())
            stream = self._stream
            version = self._version
        recorded = [r.metric for r in self.recorded()]
        return ExtensionState(mode=self.mode, stream=stream, version=version, placements=placements, recorded=recorded)

    def overlay(self, graph: Graph) -> Graph:
        with self._lock:
            return graph_with_placements(graph, self._current())

    def get(self, name: str) -> PlacementResult | None:
        with self._lock:
            return next((p for p in reversed(self._current()) if p.metric.name == name), None)

    def receipt(self, receipt_id: str) -> Receipt | None:
        """A receipt of a recorded placement in this stream (live receipts are in the runtime's runner)."""
        with self._lock:
            for p in self._current():
                for r in p.receipts:
                    if r.id == receipt_id:
                        return r
        return None

    # ------------------------------------------------------------------ write

    def place(self, metric: MetricDefinition) -> tuple[PlacementResult, bool]:
        """Place one metric. Returns the result and whether it is new (False: the same metric was placed before)."""
        with self._lock:
            current = self._current()
            for p in current:
                if _same_metric(p.metric, metric):
                    return p, False
            if self.placement_limit is not None and len(current) >= self.placement_limit:
                raise PlacementError(f"This session has reached its limit of {self.placement_limit} metric placements")
            result = self._place_live(metric) if self.runtime is not None else self._place_recorded(metric, current)
            current.append(result)
            self._version += 1
            return result, True

    def _place_live(self, metric: MetricDefinition) -> PlacementResult:
        rt = self.runtime
        assert rt is not None
        with rt.lock:  # the runtime ticks under this lock: no tick sees half a placement
            as_of = rt.as_of or first_tick(rt.world)
            placed_before = [n.id for n in rt.graph.nodes if n.source != "seed"]
            p = classify(metric, rt.graph, rt.runner, as_of, source="api: POST /graph/metrics", changelog=rt.changelog)
            if p.node is not None or p.added_edges():
                # exactly what the runtime does after its daily re-test
                rt.tester.graph = p.graph
                rt.book.graph = rt.detector.graph = rt.graph
                rt.plan_watch.update_graph(rt.graph)
            for kind, payload in to_events(p):
                self.hub.publish(Event(seq=self.hub.next_seq(), type=kind, sim_ts=as_of, payload=payload))
            return build_result(
                p, rt.runner.receipts, mode="live", world=world_label(rt.world), placed_before=placed_before
            )

    def _place_recorded(self, metric: MetricDefinition, current: list[PlacementResult]) -> PlacementResult:
        recorded = self.recorded()
        found = next((r for r in recorded if _same_metric(r.metric, metric)), None)
        if found is None:
            if self.isolated:
                raise PlacementError("Public metric placement accepts the recorded ad metrics as written")
            names = ", ".join(r.metric.name for r in recorded) or "none"
            raise PlacementError(
                f"a replay has no world to classify {metric.name} against; it can place the recorded demo metrics "
                f"({names}) exactly as written. `make demo` runs Argus live and places any metric"
            )
        graph = self.hub.state.current_graph()
        if self.isolated:
            graph = graph_with_placements(graph, current)
        have = {n.id for n in graph.nodes}
        missing = [n for n in found.requires if n not in have]
        if missing:
            raise PlacementError(
                f"{metric.name} was recorded after {', '.join(missing)}; place {'it' if len(missing) == 1 else 'them'}"
                " first, the placement depends on them"
            )
        if found.enters_graph and not self.isolated:
            with self.hub.state.lock:
                self.hub.state.graph = graph_with(self.hub.state.graph, found)
        return found


# --------------------------------------------------------------------------------------------- CLI


def _post(api: str, metric: MetricDefinition) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{api.rstrip('/')}/graph/metrics",
        data=metric.model_dump_json().encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return dict(json.loads(res.read()))
    except urllib.error.HTTPError as err:
        detail = json.loads(err.read() or b"{}").get("detail", err.reason)
        raise SystemExit(f"{metric.name}: HTTP {err.code}: {detail}") from err


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m argus.graph.extension", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="place the demo pack against a world and write placements.json")
    rec.add_argument("--world", type=Path, required=True, help="world.duckdb (the demo uses runs/s4-1)")
    rec.add_argument("--out", type=Path, default=RECORDING, help="recording directory with metrics/*.yml")
    rec.add_argument("--as-of", type=datetime.fromisoformat, help="default: the first live tick of the world")
    post = sub.add_parser("post", help="onboard metric YAML files into a running API, in order")
    post.add_argument("metrics", nargs="+", type=Path)
    post.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args(argv)
    if args.command == "record":
        for line in record(args.world, args.out, args.as_of):
            print(line)
        return 0
    for path in args.metrics:
        result = _post(args.api, load_metric(path))
        print(f"{result['metric']['name']:<28} {result['placed_as']:<10} {result['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

__all__ = [
    "RECORDING",
    "CandidateView",
    "ExtensionState",
    "GraphExtension",
    "PlacementError",
    "PlacementResult",
    "RepairView",
    "build_result",
    "graph_with",
    "load_recorded",
    "record",
    "recorded_metrics",
]
