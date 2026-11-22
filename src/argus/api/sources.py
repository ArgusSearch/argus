"""Where the API reads from: a live runtime over a world, or a replay of a recorded run.

Both publish through the same `EventHub`, so replay and live share every code path after the hub.
Both can be paced and paused through `POST /replay`; only a replay can restart.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from argus.api.hub import EventHub
from argus.api.recording import FIXTURES, Recording, load_recording
from argus.api.replay import Action, Pace, Replayer
from argus.api.rerun import RerunResult, RerunUnavailable, WorldRerunner
from argus.api.state import RunState
from argus.contracts.findings import Incident, Note, Receipt
from argus.contracts.graph import Graph
from argus.graph.store import load_seed_graph
from argus.narrator.report import render
from argus.notifications import IncidentNotices
from argus.runtime.loop import Runtime
from argus.settings import SettingsStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from argus.agent.profile import Profile
    from argus.agent.provider import AgentModels, SpendLedger
    from argus.agent.service import AgentService
    from argus.agent.settings_runtime import SettingsAgent
    from argus.agent.types import LlmClient
    from argus.investigate.procedure import EvidenceSelector

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
        *,
        agent_provider: Callable[[], tuple[LlmClient, AgentModels]] | None = None,
        agent_spend: SpendLedger | None = None,
        agent_profile: Profile | None = None,
        hold_for_approval: bool = True,
        wall_clock: bool = False,
    ) -> None:
        from argus.agent.service import build, configured_mode

        self.bus = EventHub(RunState(load_seed_graph()))
        # the agent (argus.agent): off unless --agent live/record or ARGUS_AGENT, and then only with a key
        self._agent_mode = configured_mode(agent)
        self._initial_agent = build(
            self._agent_mode,
            stream=self.bus.stream,
            recording=agent_recording,
            profile=agent_profile,
            provider=agent_provider,
            spend=agent_spend,
        )
        self._settings_agent: SettingsAgent | None = None
        self._notices: IncidentNotices | None = None
        if self._initial_agent.selector is not None:
            self._initial_agent.selector.through_seq = lambda: self.bus.last_seq
        self.runtime = Runtime(world, bus=self.bus, stage=stage, selector=self._initial_agent.selector)
        self.remediation: Any = None
        if self._agent_mode != "off":
            # PROPOSE -> AWAIT_OPERATOR -> APPLY -> VERIFY (lane C); the clock holds while an operator decides
            from argus.agent.actions import Proposer
            from argus.remediation import RemediationService

            proposer: list[Proposer] = []
            self.remediation = RemediationService.for_runtime(self.runtime, publish=lambda e: proposer[0].publish(e))
            proposer.append(Proposer(self._initial_agent.journal, self.remediation))
            self.runtime.on_incident = proposer[0].on_incident
        self.seconds_per_tick = seconds_per_tick
        self.hold_for_approval = hold_for_approval
        self.wall_clock = wall_clock
        self.speed = 1.0
        self.playing = True
        self.position = 0
        self._last_checked_at: datetime | None = None
        self._ticks = self.runtime.ticks()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._to_end = False
        if not wall_clock:
            self.bus.pace_steps = lambda: 0.0 if self._to_end else 0.45 * self.seconds_per_tick / self.speed
        self._thread: threading.Thread | None = None

    @property
    def agent(self) -> AgentService:
        return self._settings_agent.refresh() if self._settings_agent is not None else self._initial_agent

    @agent.setter
    def agent(self, service: AgentService) -> None:
        self._initial_agent = service
        self._settings_agent = None

    def configure_settings(self, settings: SettingsStore) -> None:
        from argus.agent.settings_runtime import SettingsAgent

        self._settings_agent = SettingsAgent(self._initial_agent, self._agent_mode, settings)
        self.runtime.settings = settings.read
        self.runtime.prepare_selector = self._prepare_selector
        self._notices = IncidentNotices(settings)
        self.runtime.on_notice = self._notices.add

    def _prepare_selector(self) -> EvidenceSelector | None:
        selector = self.agent.selector
        if selector is not None and self._settings_agent is not None:
            selector.budget = self._settings_agent.budget()
            selector.through_seq = lambda: self.bus.last_seq
            selector.world_revision = self.world_revision()
        return selector

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
            started = time.monotonic()
            try:
                self.runtime.tick(as_of)
            except asyncio.CancelledError:
                if self._stop.is_set():
                    return
                raise
            self._last_checked_at = datetime.now(UTC)
            if self._stop.is_set():
                return
            tick = self.bus.state.last_tick
            agent = self.agent
            if agent.enabled and tick is not None:
                agent.journal.add(
                    "watch",
                    "WATCH",
                    tick.as_of,
                    None,
                    text=f"Scored {len(tick.scored_nodes)} metrics · {len(tick.pending_nodes)} pending",
                )
            if self._notices is not None:
                self._notices.flush(as_of)
            if self.remediation is not None:
                self.remediation.tick(as_of)
                if agent.selector is not None:
                    agent.selector.world_revision = self.world_revision()
            self.position += 1
            deadline = (started if self.wall_clock else time.monotonic()) + self.seconds_per_tick / self.speed
            while not self._to_end and not self._stop.is_set() and (left := deadline - time.monotonic()) > 0:
                self._wake.wait(left)  # a speed change or pause re-evaluates the wait
                self._wake.clear()
                deadline = min(deadline, time.monotonic() + self.seconds_per_tick / self.speed)
                if not self.playing:
                    break

    def world_revision(self) -> str:
        """'factual', or the branch of the action the run switched to."""
        active = self.remediation.active_world() if self.remediation is not None else None
        return str(active[1]) if active else "factual"

    def _held(self) -> bool:
        """The simulated clock waits while an action waits for the operator or the simulator."""
        return (
            self.hold_for_approval
            and self.remediation is not None
            and bool(self.remediation.holds_clock())
            and not self._stop.is_set()
        )

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    async def closed(self) -> None:
        # A stopped monitor can still serve receipt SQL until the API closes.
        self.runtime.runner.cancel()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 30)
        self.runtime.runner.close()
        self.agent.save()
        if self._notices is not None:
            await asyncio.to_thread(self._notices.close)
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
        checked_at = self._last_checked_at
        return {
            "source": str(self.runtime.world),
            "world_start": self.runtime.manifest.get("world_start"),
            "last_checked_at": checked_at.isoformat() if checked_at else None,
            "rerun": True,
        }
