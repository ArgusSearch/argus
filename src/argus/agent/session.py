"""Run Argus with the agent over a world: record a live session, or replay one strictly from its cassette.

`record` drives the runtime tick by tick with the pre-verdict loop on a live (recording) client and writes:

| file            | content                                                         |
|-----------------|-----------------------------------------------------------------|
| `turns.jsonl`   | the provider exchange, lane D's v1 line format                   |
| `activity.jsonl`| frozen `ActivityRecord`s in seq order                            |
| `events.jsonl`  | the C5 events of the same run                                   |
| `runs.json`     | `RunSummary` per agent run                                       |
| `usage.jsonl`   | one `UsageRecord` per provider call                              |

`replay` runs the same world again with a strict `ReplayClient` (no provider is constructed) and returns the
first difference from the recording, so a recording is a regression gate for the loop, the prompt and the
tools. Wall-clock fields (`UsageRecord.wall_ms`) are ignored in the comparison.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argus.agent.investigate import AgentSelector
from argus.agent.journal import Journal
from argus.agent.provider import AnthropicClient, Cassette, RecordingClient, ReplayClient, SpendLedger
from argus.agent.types import AgentMode, LlmClient

TURNS = "turns.jsonl"
ACTIVITY = "activity.jsonl"
EVENTS = "events.jsonl"
RUNS = "runs.json"
USAGE = "usage.jsonl"


@dataclass
class SessionResult:
    journal: Journal
    events: list[dict[str, Any]]
    incidents: list[dict[str, Any]]


def run_world(world: Path, client: LlmClient, mode: AgentMode, spend: SpendLedger | None = None) -> SessionResult:
    from argus.runtime.loop import Runtime

    journal = Journal()
    runtime_ref: list[Any] = []
    selector = AgentSelector(
        client, journal, mode=mode, spend=spend, through_seq=lambda: runtime_ref[0].bus.history[-1].seq
    )
    runtime = Runtime(world, selector=selector)
    runtime_ref.append(runtime)
    try:
        runtime.run()
    finally:
        runtime.runner.close()
    return SessionResult(
        journal,
        [e.model_dump(mode="json") for e in runtime.bus.history],
        [i.model_dump(mode="json") for i in runtime.book.incidents.values()],
    )


def _jsonl(path: Path, rows: list[Any]) -> None:
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def record(world: Path, out: Path, client: LlmClient | None = None) -> SessionResult:
    recorder = RecordingClient(client or AnthropicClient())
    result = run_world(world, recorder, "record", spend=SpendLedger())
    out.mkdir(parents=True, exist_ok=True)
    recorder.cassette.write(out / TURNS)
    j = result.journal
    _jsonl(out / ACTIVITY, [r.model_dump(mode="json") for r in j.records])
    _jsonl(out / EVENTS, result.events)
    (out / RUNS).write_text(json.dumps([r.model_dump(mode="json") for r in j.runs.values()], indent=1) + "\n")
    _jsonl(out / USAGE, [u.model_dump(mode="json") for u in j.usage])
    (out / "incidents.json").write_text(json.dumps(result.incidents, indent=1) + "\n")
    return result


def _stable(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k != "wall_ms"}


def replay(world: Path, recording: Path, strict: bool = True) -> list[str]:
    """Re-run the world on the recorded turns; returns the differences (empty: identical)."""
    client = ReplayClient(Cassette.load(recording / TURNS), strict=strict)
    result = run_world(world, client, "replay")
    problems: list[str] = []
    recorded_activity = [json.loads(line) for line in (recording / ACTIVITY).read_text().splitlines() if line]
    produced = [r.model_dump(mode="json") for r in result.journal.records]
    for name, want, got in (
        ("activity", recorded_activity, produced),
        ("events", [json.loads(x) for x in (recording / EVENTS).read_text().splitlines() if x], result.events),
    ):
        if len(want) != len(got):
            problems.append(f"{name}: recorded {len(want)}, replayed {len(got)}")
        for i, (a, b) in enumerate(zip(want, got, strict=False)):
            if a != b:
                problems.append(f"{name}[{i}]: recorded {json.dumps(a)[:200]} / replayed {json.dumps(b)[:200]}")
                break
    unused = list(client.unused())
    if unused:
        problems.append(f"unused recorded turns: {unused[:5]}")
    if client.drift:
        problems.append(f"request drift (lenient): {client.drift[:5]}")
    return problems
