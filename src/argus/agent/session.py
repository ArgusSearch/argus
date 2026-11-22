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

A `v2` recording names its profile and features in `session.json`; a replay runs the same profile (a
recording without them is `v1`).
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from argus.agent.ask import AskRunner, AskScope
from argus.agent.investigate import AgentSelector
from argus.agent.journal import Journal
from argus.agent.profile import V1, Profile
from argus.agent.provider import (
    ANTHROPIC_MODELS,
    OPENAI_ASTRA,
    AgentModels,
    Cassette,
    RecordingClient,
    ReplayClient,
    SpendLedger,
    live_client,
)
from argus.agent.service import AgentService
from argus.agent.types import AgentMode, Decision, LlmClient
from argus.evidence import EvidenceStore

TURNS = "turns.jsonl"
ACTIVITY = "activity.jsonl"
EVENTS = "events.jsonl"
RUNS = "runs.json"
USAGE = "usage.jsonl"
ASK = "ask.jsonl"


@dataclass
class SessionResult:
    journal: Journal
    events: list[dict[str, Any]]
    incidents: list[dict[str, Any]]
    asks: list[dict[str, Any]]


@dataclass(frozen=True)
class AskPlan:
    """Questions a scripted human asks at one simulated hour, in one conversation (the later ones follow up)."""

    at: datetime
    questions: tuple[str, ...]
    incident_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"at": self.at.isoformat(), "questions": list(self.questions), "incident_id": self.incident_id}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> AskPlan:
        return cls(datetime.fromisoformat(data["at"]), tuple(data["questions"]), data.get("incident_id"))


Decide = Literal["approve", "deny", "none"]
OPERATOR = "recording operator"


def run_world(
    world: Path,
    client: LlmClient,
    mode: AgentMode,
    spend: SpendLedger | None = None,
    decide: Decide = "none",
    asks: Sequence[AskPlan] = (),
    profile: Profile = V1,
    models: AgentModels = ANTHROPIC_MODELS,
) -> SessionResult:
    """Run the live window with the agent. `decide`: what the scripted operator does with each proposal, in
    the hour it appears (the clock holds for a decision, so that is the hour a human would decide in)."""
    from argus.agent.actions import Proposer
    from argus.remediation import RemediationService
    from argus.runtime.loop import Runtime

    journal = Journal()
    runtime_ref: list[Any] = []
    selector = AgentSelector(
        client,
        journal,
        mode=mode,
        spend=spend,
        through_seq=lambda: runtime_ref[0].bus.history[-1].seq,
        profile=profile,
        model=models.loop,
        critic_model=models.critic,
    )
    runtime = Runtime(world, selector=selector)
    runtime_ref.append(runtime)
    with tempfile.TemporaryDirectory(prefix="argus-remediation-") as state:
        proposer: list[Proposer] = []
        service = RemediationService.for_runtime(
            runtime, publish=lambda e: proposer[0].publish(e), state_dir=Path(state), background=False
        )
        proposer.append(Proposer(journal, service))
        runtime.on_incident = proposer[0].on_incident
        store = EvidenceStore()
        agent = AgentService(
            mode,
            journal,
            client=client,
            store=store,
            models=models,
            asker=AskRunner(client, journal, store, mode, spend, model=models.loop),
        )
        answers: list[dict[str, Any]] = []

        def ask_now(plan: AskPlan) -> None:
            tick = runtime.bus.history[-1]
            scope = AskScope(
                stream=journal.stream,
                through_seq=tick.seq,
                as_of=tick.sim_ts,
                latest_hour=tick.sim_ts - runtime.lag,
                graph=runtime.graph,
                incidents=list(runtime.book.incidents.values()),
                world=runtime.runner.world_path,
                world_revision=revision(),
                proposals=[p.model_dump(mode="json") for p in service.proposals()],
            )
            conversation = None
            for question in plan.questions:
                result = agent.ask(question, scope, plan.incident_id, conversation)
                conversation = result.conversation_id
                answers.append({"question": question, "through_seq": tick.seq, "response": result.to_json(0)})

        def revision() -> str:
            active = service.active_world()
            return str(active[1]) if active else "factual"

        def on_tick(as_of: datetime) -> None:
            service.tick(as_of)
            selector.world_revision = revision()
            for plan in asks:
                if plan.at == as_of:
                    ask_now(plan)
            for view in service.proposals():
                if view.state == "AWAIT_OPERATOR" and decide != "none":
                    choice = Decision(decision=decide, principal=OPERATOR, at=as_of)
                    service.decide(view.id, view.digest, choice, idempotency_key=f"record-{view.id}")

        try:
            runtime.run(on_tick=on_tick)
        finally:
            service.close()
            runtime.runner.close()
    return SessionResult(
        journal,
        [e.model_dump(mode="json") for e in runtime.bus.history],
        [i.model_dump(mode="json") for i in runtime.book.incidents.values()],
        answers,
    )


def _jsonl(path: Path, rows: list[Any]) -> None:
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def record(
    world: Path,
    out: Path,
    client: LlmClient | None = None,
    decide: Decide = "none",
    asks: Sequence[AskPlan] = (),
    profile: Profile = V1,
    *,
    models: AgentModels = ANTHROPIC_MODELS,
) -> SessionResult:
    if client is None:
        client, models = live_client(critic=profile.on("critic"))
    recorder = RecordingClient(client)
    result = run_world(
        world, recorder, "record", spend=SpendLedger(), decide=decide, asks=asks, profile=profile, models=models
    )
    out.mkdir(parents=True, exist_ok=True)
    session: dict[str, Any] = {"decide": decide, "asks": [a.to_json() for a in asks]}
    if profile != V1:
        session.update(profile.to_json())
    if models.provider == "openai":
        session.update(provider=models.provider, critic_model=models.critic)
    (out / "session.json").write_text(json.dumps(session) + "\n")
    if asks:
        _jsonl(out / ASK, result.asks)
    recorder.cassette.write(out / TURNS)
    j = result.journal
    _jsonl(out / ACTIVITY, [r.model_dump(mode="json") for r in j.records])
    _jsonl(out / EVENTS, result.events)
    (out / RUNS).write_text(json.dumps([r.model_dump(mode="json") for r in j.runs.values()], indent=1) + "\n")
    _jsonl(out / USAGE, [u.model_dump(mode="json") for u in j.usage])
    (out / "incidents.json").write_text(json.dumps(result.incidents, indent=1) + "\n")
    return result


def _replay_investigation(world: Path, client: ReplayClient, profile: Profile, models: AgentModels) -> SessionResult:
    """Reproduce a sealed investigation capture, which has no operator or Ask service."""
    from argus.runtime.loop import Runtime

    journal = Journal()
    runtime: Runtime
    selector = AgentSelector(
        client,
        journal,
        mode="replay",
        profile=profile,
        through_seq=lambda: runtime.bus.history[-1].seq,
        model=models.loop,
        critic_model=models.critic,
    )
    runtime = Runtime(world, selector=selector)
    try:
        runtime.run()
        return SessionResult(
            journal,
            [event.model_dump(mode="json") for event in runtime.bus.history],
            [incident.model_dump(mode="json") for incident in runtime.book.incidents.values()],
            [],
        )
    finally:
        runtime.runner.close()


def replay(world: Path, recording: Path, strict: bool = True) -> list[str]:
    """Re-run the world on the recorded turns; returns the differences (empty: identical)."""
    client = ReplayClient(Cassette.load(recording / TURNS), strict=strict)
    meta = recording / "session.json"
    manifest = recording / "manifest.json"
    investigation_only = not meta.exists() and manifest.exists() and not (recording / "actions.json").exists()
    settings = manifest if investigation_only else meta
    session = json.loads(settings.read_text()) if settings.exists() else {}
    profile = Profile.of(session.get("profile") or "v1", session.get("features"))
    models = (
        AgentModels.openai(critic=session.get("critic_model", OPENAI_ASTRA))
        if session.get("provider") == "openai"
        else ANTHROPIC_MODELS
    )
    asks = [AskPlan.from_json(a) for a in session.get("asks", [])]
    if investigation_only:
        result = _replay_investigation(world, client, profile, models)
    else:
        result = run_world(
            world, client, "replay", decide=session.get("decide", "none"), asks=asks, profile=profile, models=models
        )
    problems: list[str] = []
    recorded_activity = [json.loads(line) for line in (recording / ACTIVITY).read_text().splitlines() if line]
    produced = [r.model_dump(mode="json") for r in result.journal.records]
    for name, want, got in (
        ("activity", recorded_activity, produced),
        ("events", [json.loads(x) for x in (recording / EVENTS).read_text().splitlines() if x], result.events),
        ("ask", [json.loads(x) for x in (recording / ASK).read_text().splitlines() if x] if asks else [], result.asks),
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
