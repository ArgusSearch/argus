"""Agent profiles: v1 stays byte-identical to the sealed recordings; v2 switches techniques on one by one."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from argus.agent import prompts
from argus.agent.fake import FakeLlmClient
from argus.agent.investigate import AgentSelector, tool_specs
from argus.agent.journal import Journal
from argus.agent.profile import V1, V2, Profile
from argus.agent.service import build
from argus.skeptic.critic import LlmCritic

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "agent" / "v1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@pytest.mark.parametrize("bundle", ["cassettes/s1", "cassettes/s4", "s1", "s4"])
def test_v1_prompt_and_tools_match_the_sealed_pins(bundle: str) -> None:
    manifest = json.loads((FIXTURES / bundle / "manifest.json").read_text())
    assert manifest["prompt_sha"] == _sha(prompts.SELECT.encode())
    assert manifest["tools_sha"] == _sha(_canonical(tool_specs()))
    assert manifest["tools_sha"] == _sha(_canonical(tool_specs(V1)))


def test_profiles_from_names_and_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARGUS_AGENT_PROFILE", raising=False)
    monkeypatch.delenv("ARGUS_AGENT_FEATURES", raising=False)
    assert Profile.from_env() == V1 and not V1.features
    monkeypatch.setenv("ARGUS_AGENT_PROFILE", "v2")
    assert Profile.from_env() == V2 and V2.on("critic") and V2.on("hypotheses")
    monkeypatch.setenv("ARGUS_AGENT_FEATURES", "critic")
    assert Profile.from_env().features == {"critic"}
    assert Profile.from_env("v2", "hypotheses").features == {"hypotheses"}
    assert Profile.from_env("v2").features == {"critic"}
    monkeypatch.setenv("ARGUS_AGENT_FEATURES", "")
    assert Profile.from_env().features == frozenset()
    assert Profile.of("v1", "critic") == V1  # v1 never takes features
    with pytest.raises(ValueError):
        Profile.of("v2", "critic,telepathy")
    with pytest.raises(ValueError):
        Profile.of("v3")


def test_v2_tools_add_the_declaration_and_card_ids_only_with_hypotheses() -> None:
    v1 = tool_specs(V1)
    assert tool_specs(Profile.of("v2", "critic")) == v1  # the critic does not change the detective
    v2 = tool_specs(Profile.of("v2", "hypotheses"))
    names = [t["name"] for t in v2]
    assert names == [*(t["name"] for t in v1[:-1]), "propose_hypotheses", "submit_findings"]
    for spec in v2:
        if spec["name"] in ("propose_hypotheses", "submit_findings"):
            assert "hypothesis_id" not in spec["input_schema"]["properties"]
        else:
            assert "hypothesis_id" in spec["input_schema"]["properties"]
            assert "hypothesis_id" not in spec["input_schema"]["required"]
    assert tool_specs(V1) == v1  # building v2 specs never mutates v1's
    assert prompts.SELECT_V2.startswith(prompts.SELECT)


def test_selector_wires_the_critic_only_in_v2() -> None:
    client = FakeLlmClient()
    v1 = AgentSelector(client, Journal(), mode="replay")
    assert v1.profile == V1 and v1.critic is None and v1.memory is None
    v2 = AgentSelector(client, Journal(), mode="replay", profile=V2)
    assert isinstance(v2.critic, LlmCritic) and v2.critic.model == "claude-opus-5-5"
    v2.world_revision = "branch_1"
    assert v2.critic.world_revision == "branch_1"
    hypotheses_only = AgentSelector(client, Journal(), mode="replay", profile=Profile.of("v2", "hypotheses"))
    assert hypotheses_only.critic is None


def test_health_names_profile_features_and_critic_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARGUS_AGENT_PROFILE", raising=False)
    health = build("off").health()
    assert health["profile"] == "v1" and health["features"] == [] and health["board_version"] == "agent-board/1"
    assert "critic" not in health["models"]
    v2 = build("off", profile=V2).health()
    assert v2["profile"] == "v2" and "critic" in v2["features"]
    assert v2["models"]["critic"] == "claude-opus-5-5" and v2["caps"]["critic"]["tool_calls"] == 3
