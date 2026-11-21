"""A monotonic playback clock with no background worker or client-owned timer."""

from __future__ import annotations

import asyncio
import time
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from argus.demo.contracts import Action, DemoState, Status
from argus.demo.timeline import DURATION_MS, OFFSETS, Timeline


class ControlError(ValueError):
    """The requested action is invalid for the current playback state."""


@dataclass
class PlaybackRun:
    id: str
    timeline: Timeline
    speed: float
    anchor: float
    position: float = 0.0
    paused: bool = False

    def elapsed(self, now: float) -> float:
        advanced = 0.0 if self.paused else (now - self.anchor) * 1000 * self.speed
        return min(self.position + advanced, DURATION_MS)

    def state(self, now: float) -> DemoState:
        position = self.elapsed(now)
        status: Status = "paused" if self.paused else "playing"
        if position >= DURATION_MS:
            status = "completed"
        return DemoState(
            run_id=self.id,
            scenario=self.timeline.scenario,
            status=status,
            speed=self.speed,
            elapsed_ms=int(position),
            duration_ms=DURATION_MS,
            beat_index=bisect_right(OFFSETS, position) - 1,
            beat_count=len(self.timeline.cues),
        )

    def delay(self, now: float, next_index: int) -> float | None:
        if self.paused:
            return None
        target = OFFSETS[next_index] if next_index < len(OFFSETS) else DURATION_MS
        return max(0.0, (target - self.elapsed(now)) / (1000 * self.speed))


class Playback:
    """Keep one run per API app. Call transitions on the app event loop."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.run: PlaybackRun | None = None
        self.changed = asyncio.Event()

    def _notify(self) -> None:
        self.changed.set()
        self.changed = asyncio.Event()

    def start(self, timeline: Timeline, speed: float) -> DemoState:
        now = self.clock()
        self.run = PlaybackRun(uuid4().hex, timeline, speed, now)
        self._notify()
        return self.run.state(now)

    def state(self) -> DemoState:
        return self.run.state(self.clock()) if self.run else DemoState()

    def control(self, action: Action) -> DemoState:
        run = self.run
        if run is None:
            raise ControlError("start a demo first")
        if action == "restart":
            return self.start(run.timeline, run.speed)

        now = self.clock()
        state = run.state(now)
        if state.status == "completed":
            raise ControlError("restart the completed demo")
        position = run.elapsed(now)
        match action:
            case "pause":
                run.paused = True
            case "resume":
                run.paused = False
            case "skip":
                next_index = bisect_right(OFFSETS, position)
                position = OFFSETS[next_index] if next_index < len(OFFSETS) else DURATION_MS
        run.position = position
        run.anchor = now
        self._notify()
        return run.state(now)
