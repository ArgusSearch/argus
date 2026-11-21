"""Recording profile pins and isolated memory inputs for cold replay."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from scripts.agent_eval.bundle import FEATURES, Manifest, sha256

from argus.agent.investigate import AgentSelector
from argus.agent.journal import Journal
from argus.agent.types import LlmClient


@dataclass(frozen=True)
class ReplayConfig:
    profile: str = "v1"
    features: frozenset[str] = frozenset()
    memory: bytes | None = None

    def __post_init__(self) -> None:
        if self.profile not in {"v1", "v2"} or self.features - FEATURES:
            raise ValueError("unknown recording profile or feature")
        if self.profile == "v1" and (self.features or self.memory is not None):
            raise ValueError("profile v1 takes no intelligence settings")
        if self.memory is not None and "memory" not in self.features:
            raise ValueError("a memory seed requires the memory feature")
        if self.memory is not None:
            case_note = import_module("argus.agent.types").CaseNote

            for line in self.memory.splitlines():
                if line.strip():
                    case_note.model_validate(json.loads(line))

    def metadata(self, output: Path) -> dict[str, Any]:
        if self.profile == "v1":
            return {}
        meta: dict[str, Any] = {"profile": self.profile, "features": sorted(self.features)}
        if self.memory is not None:
            (output / "memory.jsonl").write_bytes(self.memory)
            meta["memory_sha"] = sha256(self.memory)
        return meta

    @classmethod
    def from_manifest(cls, manifest: Manifest, directory: Path) -> ReplayConfig:
        data = None
        if manifest.memory_sha is not None:
            path = directory / "memory.jsonl"
            if path.is_symlink():
                raise ValueError("memory seed cannot be a symbolic link")
            data = path.read_bytes()
            if sha256(data) != manifest.memory_sha:
                raise ValueError("memory seed does not match the manifest")
        return cls(manifest.profile or "v1", frozenset(manifest.features or []), data)

    def selector(
        self, client: LlmClient, journal: Journal, through_seq: Callable[[], int], state: Path
    ) -> AgentSelector:
        if self.profile == "v1":
            return AgentSelector(client, journal, mode="replay", through_seq=through_seq)
        profile = import_module("argus.agent.profile").Profile

        options: dict[str, Any] = {}
        if self.memory is not None:
            case_memory = import_module("argus.agent.memory").JsonlCaseMemory

            state.mkdir(parents=True, exist_ok=True)
            path = state / "memory.jsonl"
            path.write_bytes(self.memory)
            options["memory"] = case_memory(path)
        options["profile"] = profile(name="v2", features=self.features)
        return AgentSelector(client, journal, mode="replay", through_seq=through_seq, **options)


V1_REPLAY = ReplayConfig()


def add_profile_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", choices=("v1", "v2"), default="v1")
    parser.add_argument("--feature", choices=sorted(FEATURES), action="append", default=[])
    parser.add_argument("--memory-seed", type=Path, help="input memory snapshot from immediately before capture")


def profile_options(args: argparse.Namespace) -> ReplayConfig:
    return ReplayConfig(
        args.profile, frozenset(args.feature), args.memory_seed.read_bytes() if args.memory_seed else None
    )
