"""The API's view of one run, folded from the event stream: counters, anomalies, notes and edge states.

The hub is the only writer (`apply`, `reset`); REST handlers read under `lock`. Incidents and receipts
are not folded here: the source serves them (the runtime's book live, recorded snapshots in replay).
"""

from __future__ import annotations

import threading

from argus.contracts.events import EdgeStatusPayload, Event, EventType, TickPayload
from argus.contracts.findings import Anomaly, Note
from argus.contracts.graph import Graph
from argus.watcher.detect import Z_ONSET, Z_OPEN, Z_PAIR

ALARM_Z = Z_OPEN  # one hour above this opens an anomaly
PAIR_Z = Z_PAIR  # two of three hours above this open one too
WIGGLE_Z = Z_ONSET  # below this a move is noise; between this and the alarm line it is a wiggle


class RunState:
    def __init__(self, graph: Graph) -> None:
        self.lock = threading.Lock()
        self._initial_graph = graph
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.graph = self._initial_graph
            self.notes: list[Note] = []
            self.anomalies: dict[str, Anomaly] = {}
            self.last_tick: TickPayload | None = None
            self.first_tick: TickPayload | None = None
            self.tick_count = 0
            self.series_hours = 0
            self.wiggles = 0  # series-hours with WIGGLE_Z <= |z| < ALARM_Z
            self.alarms = 0  # series-hours with |z| >= ALARM_Z
            self.last_seq = 0

    def apply(self, event: Event) -> None:
        """Fold one event into the state."""
        with self.lock:
            self.last_seq = event.seq
            payload = event.payload
            match event.type:
                case EventType.TICK:
                    tick = TickPayload.model_validate(payload)
                    self.last_tick = tick
                    self.first_tick = self.first_tick or tick
                    self.tick_count += 1
                    self.series_hours += len(tick.scored_nodes)
                    zs = [abs(tick.max_abs_z.get(n, 0.0)) for n in tick.scored_nodes]
                    self.alarms += sum(1 for z in zs if z >= ALARM_Z)
                    self.wiggles += sum(1 for z in zs if WIGGLE_Z <= z < ALARM_Z)
                case EventType.EDGE_STATUS:
                    change = EdgeStatusPayload.model_validate(payload)
                    edges = [
                        e.model_copy(update={"status": change.new_status, "last_test": change.result})
                        if e.id == change.edge
                        else e
                        for e in self.graph.edges
                    ]
                    self.graph = self.graph.model_copy(update={"edges": edges})
                case EventType.ANOMALY_OPENED:
                    anomaly = Anomaly.model_validate(payload)
                    self.anomalies[anomaly.id] = anomaly
                case EventType.NOTE_LOGGED:
                    self.notes.append(Note.model_validate(payload))
                case _:
                    pass

    def note_list(self) -> list[Note]:
        with self.lock:
            return sorted(self.notes, key=lambda n: (n.sim_ts, n.id), reverse=True)

    def current_graph(self) -> Graph:
        with self.lock:
            return self.graph
