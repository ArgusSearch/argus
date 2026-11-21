"""The tick loop. One tick = one simulated hour.

```
for each tick (as_of advances one hour):
    freshness gate for the newest hour that should be complete (as_of - delivery lag)
    re-test every formula and breakdown edge once per simulated day
    score the north-star nodes; open anomalies
    for each anomaly not covered by an open incident: investigate (Stage 2), file findings
    advance the lifecycle of open incidents
    publish every step on the event bus
```

Investigations run through the Stage-2 investigator (`argus.investigate`: hypothesis ledger, placebo, claim
labels). The Stage-1 fixed opening (`argus.investigator`) is the fallback: `Runtime(stage=1)` uses it for every
anomaly, and an anomaly the Stage-2 investigator fails on is re-investigated with it and listed in `fallbacks`.

Argus sees only world.duckdb (and its public manifest). It never receives a path to the hidden ground truth.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from argus.contracts.events import (
    EdgeStatusPayload,
    Event,
    IncidentUpdatedPayload,
    InvestigationStepPayload,
    TickPayload,
)
from argus.contracts.findings import Anomaly, Findings, Incident, TableFreshness, TrailStep
from argus.contracts.graph import Graph
from argus.graph.edge_tests import EdgeStatusChange, EdgeTester
from argus.graph.store import Changelog, load_seed_graph, write_graph
from argus.incidents.lifecycle import IncidentBook
from argus.investigate import investigate
from argus.investigator.procedure import investigate as investigate_stage_one
from argus.narrator.report import render
from argus.runtime.bus import EventBus
from argus.semantic.runner import Runner
from argus.watcher.detect import Detector
from argus.watcher.freshness import COMPLETE, completeness

HOUR = timedelta(hours=1)
STALE_LOOKBACK = timedelta(hours=48)
STAGES = (1, 2)

log = logging.getLogger(__name__)


def read_manifest(world: Path) -> dict[str, str | int]:
    path = world.parent / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


class Runtime:
    def __init__(
        self, world: str | Path, graph: Graph | None = None, bus: EventBus | None = None, stage: int = 2
    ) -> None:
        if stage not in STAGES:
            raise ValueError(f"investigator stage must be one of {STAGES}, got {stage}")
        self.world = Path(world)
        self.stage = stage
        self.manifest = read_manifest(self.world)
        self.lag = timedelta(hours=int(self.manifest.get("delivery_lag_hours", 2)))
        self.runner = Runner(self.world)
        self.tester = EdgeTester(graph or load_seed_graph(), self.runner, lag_hours=int(self.lag / HOUR))
        self.detector = Detector(self.graph, self.runner)
        self.book = IncidentBook(self.graph)
        self.changelog = Changelog()
        self.bus = bus or EventBus()
        self.anomalies: dict[str, Anomaly] = {}
        self.lock = threading.RLock()
        self.as_of: datetime | None = None
        self._last_edge_test_day: datetime | None = None
        self._pending_tables: set[str] = set()
        self.fallbacks: list[str] = []  # "<anomaly id>: <error>" for each Stage-2 failure Stage 1 took over

    @property
    def graph(self) -> Graph:
        return self.tester.graph

    # ------------------------------------------------------------------ clock
    def ticks(self) -> list[datetime]:
        """as_of values for the live window from the manifest: first hour live_start, last hour world_end - 1h."""
        live_start = datetime.fromisoformat(str(self.manifest["live_start"]))
        world_end = datetime.fromisoformat(str(self.manifest["world_end"]))
        out, as_of = [], live_start + self.lag
        while as_of <= world_end - HOUR + self.lag:
            out.append(as_of)
            as_of += HOUR
        return out

    def run(
        self,
        ticks: list[datetime] | None = None,
        seconds_per_tick: float = 0.0,
        stop: threading.Event | None = None,
        on_tick: Callable[[datetime], None] | None = None,
    ) -> None:
        for as_of in ticks or self.ticks():
            if stop is not None and stop.is_set():
                return
            self.tick(as_of)
            if on_tick:
                on_tick(as_of)
            if seconds_per_tick:
                time.sleep(seconds_per_tick)

    # ------------------------------------------------------------------ one tick
    def emit(self, payload: BaseModel, sim_ts: datetime) -> None:
        self.bus.publish(Event.make(self.bus.next_seq(), sim_ts, payload))

    def tick(self, as_of: datetime) -> None:
        with self.lock:
            self.as_of = as_of
            hour = as_of - self.lag
            day = hour.replace(hour=0)
            if self._last_edge_test_day != day:
                self._last_edge_test_day = day
                for edge_change in self.tester.run_all(as_of, self.changelog):
                    self._emit_edge(edge_change, as_of)
                self.book.graph = self.detector.graph = self.graph

            tables = sorted(self.detector.all_tables())
            found = completeness(self.runner, tables, hour - STALE_LOOKBACK, hour, as_of)
            fresh = [
                TableFreshness(
                    table=t,
                    hour=hour,
                    completeness=round(min(1.0, found.get((t, hour), 0.0)), 4),
                    status="ok" if found.get((t, hour), 0.0) >= COMPLETE else "pending",
                )
                for t in tables
            ]
            pending_tables = {f.table for f in fresh if f.status == "pending"}
            self._data_notes(fresh, pending_tables, as_of)
            stale = {t: {ts for (name, ts), v in found.items() if name == t and v < COMPLETE} for t in tables}
            self.detector.refresh(hour, as_of, stale)

            scored, pending, zs = [], [], {}
            for node in self.detector.nodes:
                if set(self.detector.tables(node)) & pending_tables:
                    pending.append(node)
                    continue
                score = self.detector.score(node, hour)
                if score is None:
                    pending.append(node)
                    continue
                scored.append(node)
                zs[node] = round(abs(score.z), 2)
                opened, _closed = self.detector.observe(score, as_of)
                if opened is not None:
                    self._on_anomaly(opened, as_of)

            for inc, change in self.book.monitor(self.runner, hour, as_of):
                self._emit_incident(inc, change, as_of, inc.history[-1].reason)

            self.emit(
                TickPayload(
                    as_of=as_of,
                    hour=hour,
                    freshness=fresh,
                    scored_nodes=scored,
                    pending_nodes=pending,
                    max_abs_z=zs,
                    open_incidents=len(self.book.open_incidents()),
                ),
                as_of,
            )

    def _on_anomaly(self, anomaly: Anomaly, as_of: datetime) -> None:
        self.anomalies[anomaly.id] = anomaly
        self.emit(anomaly, as_of)
        covering = self.book.covering(anomaly.node, anomaly.direction)
        if covering is not None:
            note = self.book.suppress(anomaly, covering, as_of)
            self.emit(note, as_of)
            return

        def on_step(step: TrailStep) -> None:
            self.emit(InvestigationStepPayload(anomaly_id=anomaly.id, step=step), as_of)

        findings = self._investigate(anomaly, as_of, on_step)
        incident, change = self.book.record(findings, anomaly, as_of)
        if incident is None:
            self.emit(self.book.notes[-1], as_of)
        else:
            self._emit_incident(incident, change, as_of, findings.verdict.value)

    def _investigate(self, anomaly: Anomaly, as_of: datetime, on_step: Callable[[TrailStep], None]) -> Findings:
        if self.stage == 1:
            return investigate_stage_one(self.graph, self.runner, anomaly, as_of, on_step)
        try:
            return investigate(self.graph, self.runner, anomaly, as_of, on_step)
        except Exception as exc:
            # One failing investigation must not stop the watch: Stage 1 still files findings for it.
            log.exception("Stage-2 investigation of %s failed; falling back to Stage 1", anomaly.id)
            self.fallbacks.append(f"{anomaly.id}: {type(exc).__name__}: {exc}")
            return investigate_stage_one(self.graph, self.runner, anomaly, as_of, on_step)

    def _emit_incident(self, inc: Incident, change: str, as_of: datetime, reason: str) -> None:
        self.emit(
            IncidentUpdatedPayload(
                id=inc.id,
                title=inc.title,
                state=inc.state,
                verdict=inc.verdict,
                root_node=inc.root_node,
                segment=inc.segment,
                direction=inc.direction,
                severity_eur=inc.severity_eur,
                change=change,  # type: ignore[arg-type]
                reason=reason,
            ),
            as_of,
        )

    def _emit_edge(self, change: EdgeStatusChange, as_of: datetime) -> None:
        self.emit(
            EdgeStatusPayload(edge=change.edge.id, old_status=change.old, new_status=change.new, result=change.result),
            as_of,
        )

    def _data_notes(self, fresh: list[TableFreshness], pending: set[str], as_of: datetime) -> None:
        """One DATA_ISSUE note when a table starts lagging beyond the normal delivery lag."""
        for f in fresh:
            if f.table in pending and f.table not in self._pending_tables:
                note = self.book.add_note(
                    kind="data_issue",
                    sim_ts=as_of,
                    reason=(
                        f"{f.table} {f.hour:%H:%M} is only {f.completeness:.0%} delivered at {as_of:%H:%M} "
                        f"(normal lag {int(self.lag / HOUR)} h); dependent nodes are not scored until it arrives"
                    ),
                )
                self.emit(note, as_of)
        self._pending_tables = pending

    # ------------------------------------------------------------------ outputs
    def export(self, out: Path) -> None:
        """Write the run's state: graph.json, incidents.json, notes.json, anomalies.json, receipts.json,
        events.jsonl, graph_changelog.jsonl and one markdown report per incident."""
        with self.lock:
            out.mkdir(parents=True, exist_ok=True)
            write_graph(self.graph, out / "graph.json")

            def dump(items: list[BaseModel]) -> str:
                return json.dumps([i.model_dump(mode="json") for i in items], indent=2) + "\n"

            (out / "incidents.json").write_text(dump(list(self.book.incidents.values())))
            (out / "notes.json").write_text(dump(list(self.book.notes)))
            (out / "anomalies.json").write_text(dump(list(self.anomalies.values())))
            (out / "receipts.json").write_text(dump(list(self.runner.receipts.values())))
            (out / "events.jsonl").write_text(
                "".join(json.dumps(e.model_dump(mode="json")) + "\n" for e in self.bus.history)
            )
            self.changelog.write(out / "graph_changelog.jsonl")
            reports = out / "reports"
            reports.mkdir(exist_ok=True)
            for inc in self.book.incidents.values():
                (reports / f"{inc.id}.md").write_text(render(inc, self.graph))
