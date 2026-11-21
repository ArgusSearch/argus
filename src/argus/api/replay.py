"""Replay a recording into the hub at demo pace, through the same path a live runtime uses.

Pacing follows the simulated clock: a new `sim_ts` (one tick, one simulated hour) waits `tick_seconds`,
events inside a tick wait `step_seconds` (investigation and skeptic steps) or `burst_seconds` (the rest),
all divided by `speed`. The replayer is controlled through `POST /replay`.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from dataclasses import dataclass
from typing import Any, Literal

from argus.api.hub import EventHub
from argus.api.recording import Recording
from argus.contracts.events import Event, EventType
from argus.contracts.findings import Incident

Action = Literal["play", "pause", "restart", "end"]

_STEP_TYPES = frozenset({EventType.INVESTIGATION_STEP, EventType.SKEPTIC_STEP, EventType.ANOMALY_OPENED})


@dataclass
class Pace:
    tick_seconds: float = 2.0
    step_seconds: float = 0.9
    burst_seconds: float = 0.04

    @classmethod
    def per_tick(cls, seconds: float) -> Pace:
        """Pace scaled to `seconds` per simulated hour (0 publishes everything at once)."""
        return cls(seconds, 0.45 * seconds, 0.02 * seconds)

    @property
    def instant(self) -> bool:
        return self.tick_seconds <= 0 and self.step_seconds <= 0 and self.burst_seconds <= 0


class Replayer:
    """Publishes a recording into the hub. Seqs are shifted past the previous stream on every restart.

    `incidents` holds the recorded incident snapshots published so far: replay never shows the future.
    """

    def __init__(self, hub: EventHub, recording: Recording, pace: Pace | None = None, loop: bool = False) -> None:
        self.hub = hub
        self.recording = recording
        self.pace = pace or Pace()
        self.loop = loop
        self.speed = 1.0
        self.position = 0
        self.playing = True
        self._resume = asyncio.Event()
        self._resume.set()
        self._wake = asyncio.Event()
        self._generation = 0  # bumped by every control action
        self._task: asyncio.Task[None] | None = None
        self._base = hub.base_seq
        self._lock = threading.Lock()
        self._incidents: dict[str, Incident] = {}
        self._snapshots: dict[int, list[Incident]] = {}
        for snap in recording.incidents:
            self._snapshots.setdefault(snap.seq, []).append(snap.incident)

    @property
    def incidents(self) -> list[Incident]:
        with self._lock:
            return list(self._incidents.values())

    # ------------------------------------------------------------------ control

    def start(self) -> None:
        """Start on the running event loop. An instant pace publishes the whole recording right here."""
        if self.pace.instant:
            self._publish_until(len(self.recording.events))
        self._task = asyncio.get_running_loop().create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def closed(self) -> None:
        if self._task:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def control(self, action: Action | None, speed: float | None) -> None:
        if speed is not None:
            self.speed = max(0.1, min(speed, 64.0))
        if action == "pause":
            self.playing = False
            self._resume.clear()
        elif action == "play":
            self.playing = True
            self._resume.set()
        elif action == "restart":
            self.position = 0
            with self._lock:
                self._incidents = {}
            self.hub.reset()
            self._base = self.hub.base_seq
            self.playing = True
            self._resume.set()
        elif action == "end":
            self._publish_until(len(self.recording.events))
        self._generation += 1
        self._wake.set()

    def status(self) -> dict[str, Any]:
        events = self.recording.events
        return {
            "playing": self.playing and self.position < len(events),
            "finished": self.position >= len(events),
            "speed": self.speed,
            "position": self.position,
            "total": len(events),
            "sim_ts": events[self.position - 1].sim_ts.isoformat() if self.position else None,
            "loop": self.loop,
        }

    # ------------------------------------------------------------------ loop

    def _publish_until(self, end: int) -> None:
        events = self.recording.events
        while self.position < min(end, len(events)):
            self._publish(events[self.position])
            self.position += 1

    def _publish(self, event: Event) -> None:
        with self._lock:  # the snapshot lands together with its event
            for incident in self._snapshots.get(event.seq, []):
                self._incidents[incident.id] = incident
        self.hub.publish(event.model_copy(update={"seq": self._base + event.seq}))

    def _delay(self, prev: Event | None, event: Event) -> float:
        if prev is None:
            return 0.0
        if event.sim_ts != prev.sim_ts:
            seconds = self.pace.tick_seconds
        elif event.type in _STEP_TYPES or prev.type in _STEP_TYPES:
            seconds = self.pace.step_seconds
        else:
            seconds = self.pace.burst_seconds
        return seconds / self.speed

    async def _sleep(self, seconds: float) -> bool:
        """Sleep, but wake early on any control action. Returns True when woken early."""
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)
        except TimeoutError:
            return False
        return True

    async def _run(self) -> None:
        events = self.recording.events
        while True:
            await self._resume.wait()
            if self.position >= len(events):
                if not self.loop:
                    await self._sleep(3600)
                    continue
                await self._sleep(8.0)
                if self.position >= len(events):
                    self.control("restart", None)
                continue
            prev = events[self.position - 1] if self.position else None
            event = events[self.position]
            delay = self._delay(prev, event)
            generation = self._generation
            if delay > 0:
                await self._sleep(delay)
            if generation != self._generation:
                continue  # a control action came in: re-evaluate position, pause and speed
            self._publish(event)
            self.position += 1
