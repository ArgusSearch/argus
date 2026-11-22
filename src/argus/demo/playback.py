"""A monotonic playback clock with no background worker or client-owned timer."""

from __future__ import annotations

import asyncio
import time
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from argus.demo.agent import AgentTimeline, AgentView
from argus.demo.contracts import Action, AgentDemoState, Decision, DemoState, Status
from argus.demo.timeline import Timeline


class ControlError(ValueError):
    """The requested action is invalid for the current playback state."""


@dataclass
class PlaybackRun:
    id: str
    timeline: Timeline | AgentTimeline
    speed: float
    anchor: float
    position: float = 0.0
    paused: bool = False
    decision: Decision | None = None
    decision_key: str | None = None

    @property
    def approval_offset(self) -> int | None:
        index = self.timeline.approval_index
        return self.timeline.offsets[index] if index is not None else None

    def elapsed(self, now: float) -> float:
        advanced = 0.0 if self.paused else (now - self.anchor) * 1000 * self.speed
        limit = self.approval_offset if self.decision != "approve" else None
        return min(self.position + advanced, self.timeline.duration_ms if limit is None else limit)

    def state(self, now: float) -> DemoState:
        position = self.elapsed(now)
        status: Status = "paused" if self.paused else "playing"
        if position >= self.timeline.duration_ms or self.decision == "deny":
            status = "completed"
        elif position == self.approval_offset and self.decision is None:
            status = "awaiting_approval"
        state = DemoState(
            run_id=self.id,
            scenario=self.timeline.scenario,
            status=status,
            speed=self.speed,
            elapsed_ms=int(position),
            duration_ms=self.timeline.duration_ms,
            beat_index=bisect_right(self.timeline.offsets, position) - 1,
            beat_count=len(self.timeline.cues),
        )
        if isinstance(self.timeline, AgentTimeline):
            assert state.beat_index is not None
            return AgentDemoState(
                **state.model_dump(),
                decision=self.decision,
                sim_ts=self.timeline.cues[state.beat_index].sim_ts,
                through_seq=self.timeline.through_seq(state.beat_index),
            )
        return state

    def delay(self, now: float, next_index: int) -> float | None:
        offsets = self.timeline.offsets
        target = offsets[next_index] if next_index < len(offsets) else self.timeline.duration_ms
        limit = self.approval_offset
        if self.paused or (limit is not None and self.decision != "approve" and target > limit):
            return None
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

    def start(self, timeline: Timeline | AgentTimeline, speed: float) -> DemoState:
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
        if state.status == "awaiting_approval":
            raise ControlError("choose approve or deny to continue the demo")
        position = run.elapsed(now)
        match action:
            case "pause":
                run.paused = True
            case "resume":
                run.paused = False
            case "skip":
                offsets = run.timeline.offsets
                next_index = bisect_right(offsets, position)
                position = offsets[next_index] if next_index < len(offsets) else run.timeline.duration_ms
        run.position = position
        run.anchor = now
        self._notify()
        return run.state(now)

    def agent_view(self, run_id: str) -> AgentView:
        run = self.run
        if run is None or run.id != run_id or not isinstance(run.timeline, AgentTimeline):
            raise ControlError("no matching agent demo run")
        state = run.state(self.clock())
        assert isinstance(state, AgentDemoState)
        return run.timeline.view(state)

    def decide(
        self, run_id: str, action_id: str, decision: Decision, digest: str, idempotency_key: str
    ) -> AgentDemoState:
        run = self.run
        if (
            run is None
            or run.id != run_id
            or not isinstance(run.timeline, AgentTimeline)
            or run.approval_offset is None
        ):
            raise ControlError("no matching agent demo action")
        proposal = run.timeline.bundle.prefix.actions.get(action_id)
        if proposal is None or proposal.digest != digest or not idempotency_key.strip():
            raise ControlError("no matching agent demo proposal digest or decision key")
        now = self.clock()
        state = run.state(now)
        assert isinstance(state, AgentDemoState)
        if run.decision == decision and run.decision_key == idempotency_key:
            return state
        if state.status != "awaiting_approval":
            raise ControlError("the demo has no pending decision")
        run.position = run.approval_offset
        run.anchor = now
        run.decision = decision
        run.decision_key = idempotency_key
        self._notify()
        decided = run.state(now)
        assert isinstance(decided, AgentDemoState)
        return decided
