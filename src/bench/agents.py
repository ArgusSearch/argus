"""Agents the bench can grade, and the one interface they share.

An agent receives the paths of `world.duckdb` and the public `manifest.json` (never the sealed truth),
runs the live window however it likes, and returns an `AgentOutput` built from the C4/C5 contracts.

Ways to plug an agent in:

* `argus`: Argus itself, the runtime tick loop (`argus.runtime.loop.Runtime`) in process.
  Set `$ARGUS_BENCH_AGENT` to a `module:function` to grade another build under the same name.
* `argus-stage2`: the runtime with the Stage-2 investigator (`argus.investigate`), when it is merged.
* `threshold`: the built-in baseline (`bench.baselines`), a BI-style alert on north-star totals.
* `module:function`: any Python callable `fn(world: Path)` returning an `AgentOutput`, a dict of the same
  shape, or a finished runtime object (`.book`, `.anomalies`, `.bus`), like `Runtime` itself.
* `cmd:<template>`: a shell command, run in its own process, with `{world}`, `{manifest}` and `{out}`
  placeholders. It writes `incidents.json`, `notes.json`, `anomalies.json` (JSON lists of the C4
  models) and/or `events.jsonl` (C5 events) into `{out}`; every file is optional.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shlex
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from argus.contracts.events import Event
from argus.contracts.findings import Anomaly, Cost, Incident, Note

ARGUS_ENV = "ARGUS_BENCH_AGENT"
RUNTIME_MODULE = "argus.runtime.loop"
STAGE2_TARGET = "argus.investigate.__main__:run_world"


class AgentOutput(BaseModel):
    """Everything an agent claims about one world. Incidents carry their full findings."""

    model_config = ConfigDict(extra="forbid")

    incidents: list[Incident] = Field(default_factory=list)
    notes: list[Note] = Field(default_factory=list)
    anomalies: list[Anomaly] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list, description="C5 stream; used when incidents are absent")
    cost: Cost | None = None

    def write(self, out: Path) -> None:
        """Write the output in the `cmd:` file layout (also used by `--record`)."""
        out.mkdir(parents=True, exist_ok=True)
        for name in ("incidents", "notes", "anomalies"):
            items = [m.model_dump(mode="json") for m in getattr(self, name)]
            (out / f"{name}.json").write_text(json.dumps(items, indent=2) + "\n")
        findings = [i.findings.model_dump(mode="json") for i in self.incidents]
        (out / "findings.json").write_text(json.dumps(findings, indent=2) + "\n")
        if self.events:
            (out / "events.jsonl").write_text("".join(e.model_dump_json() + "\n" for e in self.events))

    @classmethod
    def read(cls, out: Path) -> AgentOutput:
        data: dict[str, Any] = {}
        for name in ("incidents", "notes", "anomalies"):
            path = out / f"{name}.json"
            if path.exists():
                data[name] = json.loads(path.read_text())
        events = out / "events.jsonl"
        if events.exists():
            data["events"] = [json.loads(line) for line in events.read_text().splitlines() if line.strip()]
        return cls.model_validate(data)


def output_from_runtime(rt: Any, seconds: float = 0.0) -> AgentOutput:
    """Collect a finished `argus.runtime.loop.Runtime` (or anything shaped like it) into an AgentOutput."""
    runner = getattr(rt, "runner", None)
    return AgentOutput(
        incidents=list(rt.book.incidents.values()),
        notes=list(rt.book.notes),
        anomalies=list(rt.anomalies.values()),
        events=list(rt.bus.history) if getattr(rt, "bus", None) is not None else [],
        cost=Cost(queries=int(getattr(runner, "query_count", 0)), seconds=round(seconds, 2)),
    )


def _as_output(result: Any) -> AgentOutput:
    if isinstance(result, AgentOutput):
        return result
    if hasattr(result, "book") and hasattr(result, "anomalies"):
        return output_from_runtime(result)
    if isinstance(result, BaseModel):
        result = result.model_dump(mode="json")
    return AgentOutput.model_validate(result)


class Agent(Protocol):
    name: str

    def run(self, world: Path, manifest: Path) -> AgentOutput: ...


class AgentUnavailable(RuntimeError):
    """The agent cannot run in this checkout (for example the Argus runtime is not merged yet)."""


def _load_target(target: str) -> Callable[..., Any]:
    module_name, _, attr = target.partition(":")
    if not attr:
        raise AgentUnavailable(f"agent target {target!r} must look like 'package.module:function'")
    try:
        found = importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        found = None
    if found is None:
        raise AgentUnavailable(f"module {module_name} is not importable")
    fn = getattr(importlib.import_module(module_name), attr, None)
    if not callable(fn):
        raise AgentUnavailable(f"{module_name} has no callable {attr}")
    return fn


class CallableAgent:
    """An in-process Python agent, resolved lazily so a missing runtime only disables this agent."""

    def __init__(self, name: str, target: str):
        self.name = name
        self.target = target

    def check(self) -> None:
        _load_target(self.target)

    def run(self, world: Path, manifest: Path) -> AgentOutput:
        return _as_output(_load_target(self.target)(world))


class ArgusAgent:
    """Argus: the runtime's tick loop over the live window. It gets the world path and nothing else."""

    name = "argus"

    def check(self) -> None:
        try:
            found = importlib.util.find_spec(RUNTIME_MODULE)
        except ModuleNotFoundError:
            found = None
        if found is None:
            raise AgentUnavailable(f"{RUNTIME_MODULE} is not importable")

    def run(self, world: Path, manifest: Path) -> AgentOutput:
        from argus.runtime.loop import Runtime

        started = time.perf_counter()
        runtime = Runtime(world)
        try:
            runtime.run()
        finally:
            runtime.runner.close()
        return output_from_runtime(runtime, time.perf_counter() - started)


class CommandAgent:
    """An agent in its own process. It shares nothing with the bench but the two paths and its out dir."""

    def __init__(self, name: str, template: str, timeout_s: float = 1800.0):
        self.name = name
        self.template = template
        self.timeout_s = timeout_s

    def check(self) -> None:
        if not self.template.strip():
            raise AgentUnavailable("empty command")

    def run(self, world: Path, manifest: Path) -> AgentOutput:
        with tempfile.TemporaryDirectory(prefix="argus-bench-agent-") as tmp:
            out = Path(tmp)
            cmd = self.template.format(
                world=shlex.quote(str(world)), manifest=shlex.quote(str(manifest)), out=shlex.quote(str(out))
            )
            subprocess.run(shlex.split(cmd), check=True, timeout=self.timeout_s)
            return AgentOutput.read(out)


def resolve_agent(spec: str) -> Agent:
    """Turn a CLI agent spec into an agent. Raises AgentUnavailable when it cannot run here."""
    from bench.baselines import ThresholdBaseline

    if spec == "threshold":
        return ThresholdBaseline()
    if spec.startswith("cmd:"):
        command = CommandAgent("cmd", spec.removeprefix("cmd:"))
        command.check()
        return command
    if spec == "argus" and not os.environ.get(ARGUS_ENV):
        argus = ArgusAgent()
        argus.check()
        return argus
    if spec == "argus":
        python = CallableAgent("argus", os.environ[ARGUS_ENV])
    elif spec == "argus-stage2":
        python = CallableAgent("argus-stage2", STAGE2_TARGET)
    else:
        python = CallableAgent(spec.partition(":")[0].rsplit(".", 1)[-1], spec)
    python.check()
    return python
