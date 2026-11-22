"""S4 seed-1 world, generated once, and the incident Argus opens on it (the pacer rollout, supported)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import pytest

from argus.agent.types import ReceiptLink, RunContext
from argus.contracts.findings import Incident, IncidentState
from argus.remediation import RemediationService
from argus.runtime.loop import Runtime
from mockmart.sim import WorldConfig
from mockmart.world import WorldPaths, generate

EFFECTIVE = datetime(2026, 11, 21, 0)


@pytest.fixture(scope="session")
def s4_world(tmp_path_factory: pytest.TempPathFactory) -> WorldPaths:
    return generate("s4", WorldConfig(seed=1), tmp_path_factory.mktemp("s4-world"))


@pytest.fixture(scope="session")
def s4_incident(s4_world: WorldPaths) -> Incident:
    """The supported pacer incident, as the runtime files it at the first tick that has it."""
    runtime = Runtime(s4_world.world)
    try:
        for as_of in runtime.ticks():
            runtime.tick(as_of)
            if runtime.book.incidents:
                incident = next(iter(runtime.book.incidents.values()))
                assert incident.state is IncidentState.EXPLAINED
                return incident.model_copy(deep=True)
    finally:
        runtime.runner.close()
    raise AssertionError("S4 opened no incident")


def context(as_of: datetime, run_id: str = "run_0001", revision: str = "factual") -> RunContext:
    return RunContext(
        run_id=run_id,
        stream="s-test",
        through_seq=1,
        world_revision=revision,
        as_of=as_of,
        incident_id="INC-0001",
    )


def evidence(run_id: str = "run_0001", revision: str = "factual") -> list[ReceiptLink]:
    return [ReceiptLink(run_id=run_id, world_revision=revision, receipt_id="r7")]


class Clock:
    def __init__(self, now: datetime | None) -> None:
        self.now = now

    def __call__(self) -> datetime | None:
        return self.now


@pytest.fixture
def make_service(
    s4_world: WorldPaths, s4_incident: Incident, tmp_path: Path
) -> Iterator[Callable[..., tuple[RemediationService, Clock, dict[str, Incident]]]]:
    """A service over the shared S4 world with its own state directory; incidents are editable per test."""
    made: list[RemediationService] = []

    def make(
        now: datetime | None = datetime(2026, 11, 20, 3), **kwargs: object
    ) -> tuple[RemediationService, Clock, dict[str, Incident]]:
        clock = Clock(now)
        incidents = {s4_incident.id: s4_incident.model_copy(deep=True)}
        kwargs.setdefault("state_dir", tmp_path / "state")
        kwargs.setdefault("background", False)
        service = RemediationService(
            s4_world.world,
            incidents=incidents.get,
            clock=clock,
            **kwargs,  # type: ignore[arg-type]
        )
        made.append(service)
        return service, clock, incidents

    yield make
    for service in made:
        service.close()
