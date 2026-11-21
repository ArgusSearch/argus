"""Where the API reads from: a live runtime over a world, or a replay of a recorded run.

Both publish through the same `EventHub`, so replay and live share every code path after the hub.
Both can be paced and paused through `POST /replay`; only a replay can restart.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any, Literal, Protocol

from argus.api.hub import EventHub
from argus.api.recording import FIXTURES, Recording, load_recording
from argus.api.replay import Action, Pace, Replayer
from argus.api.rerun import RerunResult, RerunUnavailable, WorldRerunner
from argus.api.state import RunState
from argus.contracts.findings import Incident, Note, Receipt
from argus.contracts.graph import Graph
from argus.graph.store import load_seed_graph
from argus.narrator.report import render
from argus.runtime.loop import Runtime

__all__ = ["FIXTURES", "ControlError", "LiveSource", "ReplaySource", "RerunUnavailable", "Source"]

MAX_SPEED = 64.0


class ControlError(RuntimeError):
    """A run control the source cannot do (for example restarting a live run)."""


class Source(Protocol):
    mode: Literal["replay", "live"]
    bus: EventHub

    def start(self) -> None:
        """Called once on the server's event loop."""

    def stop(self) -> None: ...

    async def closed(self) -> None: ...

    def graph(self) -> Graph: ...

    def incidents(self) -> list[Incident]: ...

    def notes(self) -> list[Note]: ...

    def receipt(self, receipt_id: str) -> Receipt | None: ...

    def rerun(self, receipt_id: str) -> RerunResult | None:
        """None: there is no world to re-run against. Raises RerunUnavailable with a reason."""

    def report(self, incident_id: str) -> str | None: ...

    def status(self) -> dict[str, Any]: ...

    def control(self, action: Action | None, speed: float | None) -> dict[str, Any]: ...

    def describe(self) -> dict[str, Any]: ...


def _incident(incidents: list[Incident], incident_id: str) -> Incident | None:
    return next((i for i in incidents if i.id == incident_id), None)


class ReplaySource:
    """Replays a recording (default `fixtures/`), `seconds_per_tick` wall seconds per simulated hour.

    REST serves the recorded incidents as of the replay position. Receipts re-run only against an
    explicit `world` (the recording's manifest must match it).
    """

    mode: Literal["replay", "live"] = "replay"

    def __init__(
        self,
        fixtures: Path = FIXTURES,
        seconds_per_tick: float = 2.0,
        loop: bool = False,
        world: Path | None = None,
        recording: Recording | None = None,
    ) -> None:
        self.recording = recording or load_recording(fixtures)
        self.bus = EventHub(RunState(self.recording.graph))
        self.replayer = Replayer(self.bus, self.recording, Pace.per_tick(seconds_per_tick), loop=loop)
        self._rerunner = WorldRerunner(world=world, manifest=self.recording.manifest) if world else None

    def start(self) -> None:
        self.bus.bind(asyncio.get_running_loop())
        self.replayer.start()

    def stop(self) -> None:
        self.replayer.stop()

    async def closed(self) -> None:
        await self.replayer.closed()
        if self._rerunner:
            self._rerunner.close()

    def graph(self) -> Graph:
        return self.bus.state.current_graph()

    def incidents(self) -> list[Incident]:
        return self.replayer.incidents

    def notes(self) -> list[Note]:
        return self.bus.state.note_list()

    def receipt(self, receipt_id: str) -> Receipt | None:
        return next((r for r in self.recording.receipts if r.id == receipt_id), None)

    def rerun(self, receipt_id: str) -> RerunResult | None:
        found = self.receipt(receipt_id)
        if found is None or self._rerunner is None:
            return None
        return self._rerunner.rerun(found)

    def report(self, incident_id: str) -> str | None:
        found = _incident(self.incidents(), incident_id)
        return render(found, self.graph()) if found else None

    def status(self) -> dict[str, Any]:
        return self.replayer.status()

    def control(self, action: Action | None, speed: float | None) -> dict[str, Any]:
        self.replayer.control(action, speed)
        return self.status()

    def describe(self) -> dict[str, Any]:
        manifest = self.recording.manifest
        return {
            "source": str(self.recording.path),
            "world_start": manifest.get("world_start"),
            "rerun": self._rerunner is not None,
        }


class LiveSource:
    """Runs Argus over a world in a background thread, one tick per `seconds_per_tick` (divided by speed)."""

    mode: Literal["replay", "live"] = "live"

    def __init__(
        self,
        world: Path,
        seconds_per_tick: float = 2.0,
        stage: int = 2,
        agent: str | None = None,
        agent_recording: Path | None = None,
    ) -> None:
        from argus.agent.service import build, configured_mode

        self.bus = EventHub(RunState(load_seed_graph()))
        # the agent (argus.agent): off unless --agent live/record or ARGUS_AGENT, and then only with a key
        self.agent = build(configured_mode(agent), stream=self.bus.stream, recording=agent_recording)
        if self.agent.selector is not None:
            self.agent.selector.through_seq = lambda: self.bus.last_seq
        self.runtime = Runtime(world, bus=self.bus, stage=stage, selector=self.agent.selector)
        self.remediation: Any = None
        if self.agent.enabled:
            # PROPOSE -> AWAIT_OPERATOR -> APPLY -> VERIFY (lane C); the clock holds while an operator decides
            from argus.agent.actions import Proposer
            from argus.remediation import RemediationService

            proposer: list[Proposer] = []
            self.remediation = RemediationService.for_runtime(self.runtime, publish=lambda e: proposer[0].publish(e))
            proposer.append(Proposer(self.agent.journal, self.remediation))
            self.runtime.on_incident = proposer[0].on_incident
        self.seconds_per_tick = seconds_per_tick
        self.speed = 1.0
        self.playing = True
        self.position = 0
        self._ticks = self.runtime.ticks()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._to_end = False
        self.bus.pace_steps = lambda: 0.0 if self._to_end else 0.45 * self.seconds_per_tick / self.speed
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ run

    def start(self) -> None:
        self.bus.bind(asyncio.get_running_loop())
        self._thread = threading.Thread(target=self._run, name="argus-runtime", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        for as_of in self._ticks:
            while (not self.playing and not self._to_end) or self._held():
                if self._stop.is_set():
                    return
                self._wake.wait(0.5)
                self._wake.clear()
            if self._stop.is_set():
                return
            self.runtime.tick(as_of)
            if self.remediation is not None:
                self.remediation.tick(as_of)
            self.position += 1
            deadline = time.monotonic() + self.seconds_per_tick / self.speed
            while not self._to_end and not self._stop.is_set() and (left := deadline - time.monotonic()) > 0:
                self._wake.wait(left)  # a speed change or pause re-evaluates the wait
                self._wake.clear()
                deadline = min(deadline, time.monotonic() + self.seconds_per_tick / self.speed)
                if not self.playing:
                    break

    def _held(self) -> bool:
        """The simulated clock waits while an action waits for the operator or the simulator."""
        return self.remediation is not None and bool(self.remediation.holds_clock()) and not self._stop.is_set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    async def closed(self) -> None:
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 30)
        self.runtime.runner.close()
        self.agent.save()
        if self.remediation is not None:
            self.remediation.close()

    # ------------------------------------------------------------------ read

    def graph(self) -> Graph:
        with self.runtime.lock:
            return self.runtime.graph.model_copy(deep=True)

    def incidents(self) -> list[Incident]:
        with self.runtime.lock:
            return [i.model_copy(deep=True) for i in self.runtime.book.incidents.values()]

    def notes(self) -> list[Note]:
        with self.runtime.lock:
            return sorted(self.runtime.book.notes, key=lambda n: (n.sim_ts, n.id), reverse=True)

    def receipt(self, receipt_id: str) -> Receipt | None:
        return self.runtime.runner.receipts.get(receipt_id)

    def rerun(self, receipt_id: str) -> RerunResult | None:
        found = self.receipt(receipt_id)
        if found is None:
            return None
        started = time.perf_counter()
        result_hash, matches = self.runtime.runner.rerun(receipt_id)
        world = self.runtime.runner.world_path
        return RerunResult(
            receipt=found.id,
            as_of=found.as_of,
            expected_hash=found.result_hash,
            result_hash=result_hash,
            matches=matches,
            rows=found.rows,
            ms=round((time.perf_counter() - started) * 1000, 2),
            world=world.parent.name or str(world),
        )

    def report(self, incident_id: str) -> str | None:
        with self.runtime.lock:
            found = self.runtime.book.incidents.get(incident_id)
            return render(found, self.runtime.graph) if found else None

    # ------------------------------------------------------------------ control

    def status(self) -> dict[str, Any]:
        done = self.position >= len(self._ticks)
        as_of = self.runtime.as_of
        return {
            "playing": self.playing and not done,
            "finished": done,
            "speed": self.speed,
            "position": self.position,
            "total": len(self._ticks),
            "sim_ts": as_of.isoformat() if as_of else None,
            "loop": False,
            "held": self._held(),
        }

    def control(self, action: Action | None, speed: float | None) -> dict[str, Any]:
        if action == "restart":
            raise ControlError("a live run cannot restart: restart the API (make demo)")
        if speed is not None:
            self.speed = max(0.1, min(speed, MAX_SPEED))
        if action in ("play", "pause"):
            self.playing = action == "play"
        elif action == "end":
            self._to_end = True
        self._wake.set()
        return self.status()

    def describe(self) -> dict[str, Any]:
        return {
            "source": str(self.runtime.world),
            "world_start": self.runtime.manifest.get("world_start"),
            "rerun": True,
        }
