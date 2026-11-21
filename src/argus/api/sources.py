"""Where the API reads from: a live runtime over a world, or a replay of recorded fixtures.

Both modes publish through the same EventBus, so the UI's replay mode is the same code path as live.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Protocol

from argus.contracts.events import Event, EventType
from argus.contracts.findings import Incident, Note, Receipt
from argus.contracts.graph import Graph
from argus.narrator.report import render
from argus.runtime.bus import EventBus
from argus.runtime.loop import Runtime

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "fixtures"


class Source(Protocol):
    mode: str
    bus: EventBus

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def graph(self) -> Graph: ...
    def incidents(self) -> list[Incident]: ...
    def notes(self) -> list[Note]: ...
    def receipt(self, receipt_id: str) -> Receipt | None: ...
    def rerun(self, receipt_id: str) -> tuple[str, bool] | None: ...
    def report(self, incident_id: str) -> str | None: ...


class LiveSource:
    """Runs the tick loop in a background thread, `seconds_per_tick` wall seconds per simulated hour."""

    mode = "live"

    def __init__(self, world: Path, seconds_per_tick: float = 2.0):
        self.runtime = Runtime(world)
        self.bus = self.runtime.bus
        self.seconds_per_tick = seconds_per_tick
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.runtime.run,
            kwargs={"seconds_per_tick": self.seconds_per_tick, "stop": self._stop},
            name="argus-runtime",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def graph(self) -> Graph:
        return self.runtime.graph

    def incidents(self) -> list[Incident]:
        with self.runtime.lock:
            return [i.model_copy(deep=True) for i in self.runtime.book.incidents.values()]

    def notes(self) -> list[Note]:
        with self.runtime.lock:
            return list(self.runtime.book.notes)

    def receipt(self, receipt_id: str) -> Receipt | None:
        return self.runtime.runner.receipts.get(receipt_id)

    def rerun(self, receipt_id: str) -> tuple[str, bool] | None:
        if receipt_id not in self.runtime.runner.receipts:
            return None
        return self.runtime.runner.rerun(receipt_id)

    def report(self, incident_id: str) -> str | None:
        with self.runtime.lock:
            inc = self.runtime.book.incidents.get(incident_id)
            return render(inc, self.runtime.graph) if inc else None


class ReplaySource:
    """Replays fixtures/events.jsonl; REST routes serve the recorded end state of the same run."""

    mode = "replay"

    def __init__(self, fixtures: Path = FIXTURES, seconds_per_tick: float = 2.0, loop: bool = False):
        self.fixtures = fixtures
        self.bus = EventBus()
        self.seconds_per_tick = seconds_per_tick
        self.loop = loop
        self._graph = Graph.model_validate_json((fixtures / "graph.json").read_text())
        self._incidents = [Incident.model_validate(i) for i in json.loads((fixtures / "incidents.json").read_text())]
        self._notes = [Note.model_validate(n) for n in json.loads((fixtures / "notes.json").read_text())]
        self._receipts = {
            r["id"]: Receipt.model_validate(r) for r in json.loads((fixtures / "receipts.json").read_text())
        }
        self._events = [
            Event.model_validate_json(line) for line in (fixtures / "events.jsonl").read_text().splitlines() if line
        ]
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._play, name="argus-replay", daemon=True).start()

    def _play(self) -> None:
        seq = 0
        while not self._stop.is_set():
            for ev in self._events:
                if self._stop.is_set():
                    return
                seq += 1
                self.bus.publish(ev.model_copy(update={"seq": seq}))
                if ev.type is EventType.TICK and self.seconds_per_tick:
                    time.sleep(self.seconds_per_tick)
            if not self.loop:
                return

    def stop(self) -> None:
        self._stop.set()

    def graph(self) -> Graph:
        return self._graph

    def incidents(self) -> list[Incident]:
        return list(self._incidents)

    def notes(self) -> list[Note]:
        return list(self._notes)

    def receipt(self, receipt_id: str) -> Receipt | None:
        return self._receipts.get(receipt_id)

    def rerun(self, receipt_id: str) -> tuple[str, bool] | None:
        return None

    def report(self, incident_id: str) -> str | None:
        inc = next((i for i in self._incidents if i.id == incident_id), None)
        return render(inc, self._graph) if inc else None
