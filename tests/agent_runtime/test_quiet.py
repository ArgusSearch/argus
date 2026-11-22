"""Quiet hours never call a model, and the agent does not change what Stage 2 files on a quiet world."""

from __future__ import annotations

import pytest

from argus.agent.fake import FakeLlmClient
from argus.agent.session import run_world
from mockmart.world import WorldPaths

pytestmark = pytest.mark.e2e


def test_quiet_world_makes_no_model_call(quiet_world: WorldPaths) -> None:
    client = FakeLlmClient()  # raises on the first call
    result = run_world(quiet_world.world, client, "replay")
    assert client.requests == []
    assert result.journal.runs == {} and result.journal.usage == []
    assert result.incidents == []
