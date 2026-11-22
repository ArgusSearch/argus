"""Build a pinned presentation from a genuine cassette and real operator decisions."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from scripts.agent_eval.bundle import Bundle, canonical_json, read_bundle, receipt_keys, seal
from scripts.agent_eval.capture_cassette import CaptureMismatch, _compare, _OrderedReplay, _read_lines
from scripts.agent_eval.replay_config import V1_REPLAY, ReplayConfig, add_profile_options, profile_options

from argus.agent.actions import Proposer, supporting_receipts
from argus.agent.journal import Journal
from argus.agent.provider import Cassette
from argus.agent.session import OPERATOR, Decide
from argus.agent.types import INTERFACE_VERSION, Decision, ReceiptLink, RunSummary
from argus.contracts.findings import Receipt
from argus.remediation import RemediationService
from argus.runtime.loop import Runtime
from argus.semantic.runner import Runner
from mockmart.sim import WorldConfig
from mockmart.world import generate


@dataclass
class Segment:
    events: list[dict[str, Any]]
    activity: list[dict[str, Any]]
    incidents: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    asks: list[dict[str, Any]] = field(default_factory=list)
    receipts: dict[str, Any] = field(default_factory=dict)

    def bindings(self) -> set[str]:
        return set(receipt_keys([self.events, self.activity, self.incidents, self.actions, self.asks]))

    def write(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        for name in ("events", "activity", "asks"):
            rows = getattr(self, name)
            target = "ask" if name == "asks" else name
            (path / f"{target}.jsonl").write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))
        for name in ("incidents", "actions", "receipts"):
            (path / f"{name}.json").write_bytes(canonical_json(getattr(self, name)) + b"\n")


@dataclass
class Trace:
    graph: dict[str, Any]
    prefix: Segment
    continuation: Segment | None
    pins: tuple[str, str]


def _check_shared_prefix(approved: Segment, denied: Segment) -> None:
    for field_name in ("events", "activity", "incidents", "actions", "asks"):
        _compare(
            f"shared {field_name} prefix",
            getattr(denied, field_name),
            getattr(approved, field_name),
        )
    # Both replays rederive the same receipt. Bounded drawer samples may use different
    # row order because DuckDB is free to emit rows in any order absent ORDER BY.
    first = {key: value["receipt"] for key, value in approved.receipts.items()}
    second = {key: value["receipt"] for key, value in denied.receipts.items()}
    if first != second:
        raise CaptureMismatch("the denial changes a shared receipt binding")


def _snapshot(
    runtime: Runtime, journal: Journal, service: RemediationService, recorded_seconds: dict[str, float]
) -> Segment:
    incidents = [incident.model_dump(mode="json") for incident in runtime.book.incidents.values()]
    for incident in incidents:
        findings = incident["findings"]
        findings["cost"]["seconds"] = recorded_seconds[findings["anomaly_id"]]
    return Segment(
        [event.model_dump(mode="json") for event in runtime.bus.history],
        [record.model_dump(mode="json") for record in journal.records],
        incidents,
        [action.model_dump(mode="json") for action in service.proposals()],
    )


def _ask_at_cut(runtime: Runtime, journal: Journal, cut: Segment, scenario: str) -> None:
    """Project a deterministic answer from the same admitted incident and its actual query receipts."""
    (incident,) = runtime.book.incidents.values()
    if scenario == "s4":
        alternative = next(
            item for item in incident.findings.ruled_out if "sessions" in item.hypothesis and item.result == "refuted"
        )
        question = "Could higher traffic explain the spend?"
        answer = "The traffic check ruled out higher sessions. The pacing rollout explains the spend increase."
    else:
        alternative = next(
            item
            for item in incident.findings.ruled_out
            if item.evidence and item.evidence.ref == "dep_android-app_8.3.0" and item.result == "refuted"
        )
        question = "Did the Android release cause the checkout incident?"
        answer = "The independent holdout ruled out the Android release. The evidence identified the PayCo degradation."
    (run,) = journal.runs.values()
    ids = list(dict.fromkeys([*alternative.receipts, *supporting_receipts(incident)]))
    assert alternative.receipts and ids, "the Ask answer requires the original alternative and cause receipts"
    cut.asks.append(
        {
            "question": question,
            "through_seq": cut.events[-1]["seq"],
            "response": {
                "status": "answered",
                "answer": answer,
                "claims": [],
                "receipt_links": [
                    ReceiptLink(run_id=run.run_id, world_revision="factual", receipt_id=receipt_id).model_dump()
                    for receipt_id in ids
                ],
                "activity_cursor": cut.activity[-1]["seq"],
                "reason": "Answer rendered from verified capture evidence.",
                "usd": 0,
            },
        }
    )


def _proof(runner: Runner, receipt: Receipt) -> dict[str, Any]:
    rows, checked = runner.query(receipt.sql, receipt.as_of)
    if checked.result_hash != receipt.result_hash or checked.rows != receipt.rows:
        raise CaptureMismatch("a presentation receipt did not rerun in its recorded world")
    sample = rows[:12]
    return {
        "receipt": receipt.model_dump(mode="json") | {"ms": 0.0},
        "columns": list(sample[0]) if sample else [],
        "rows": json.loads(json.dumps([list(row.values()) for row in sample], default=str)),
        "verified_at_capture": True,
    }


def _proofs(
    keys: set[str], runtime: Runtime, service: RemediationService, factual: Runner, prefix_ids: set[str]
) -> dict[str, Any]:
    proofs: dict[str, Any] = {}
    for key in sorted(keys):
        receipt_id = key.rsplit("/", 1)[-1]
        service_receipt = None
        revision = "factual"
        if "/" in key:
            run_id, revision, receipt_id = key.split("/")
            service_receipt = service.receipt(
                ReceiptLink(run_id=run_id, world_revision=revision, receipt_id=receipt_id)
            )
        if service_receipt is not None:
            runner = factual if revision == "factual" else runtime.runner
            proofs[key] = _proof(runner, service_receipt)
        else:
            # The runtime preserves the receipt IDs across a world switch.
            receipt = runtime.runner.receipts[receipt_id]
            runner = factual if receipt_id in prefix_ids else runtime.runner
            proofs[key] = _proof(runner, receipt)
    return proofs


def _trace(
    world: Path,
    source: Path,
    scenario: Literal["s1", "s4"],
    state: Path,
    *,
    fork_deny: bool = False,
    config: ReplayConfig = V1_REPLAY,
    sealed: bool = False,
) -> Trace:
    cassette = Cassette.load(source / "turns.jsonl")
    client = _OrderedReplay(cassette)
    decide: Decide
    if fork_deny:
        decide = "deny"
    elif sealed:
        decide = "approve" if scenario == "s4" else "none"
    else:
        decide = json.loads((source / "session.json").read_bytes())["decide"]
    recorded_seconds = {
        incident["findings"]["anomaly_id"]: incident["findings"]["cost"]["seconds"]
        for incident in json.loads((source / "incidents.json").read_bytes())
    }
    journal = Journal()
    runtime: Runtime
    selector, memory = config.selector(client, journal, lambda: runtime.bus.history[-1].seq, state / "memory")
    runtime = Runtime(world, selector=selector)
    graph = runtime.graph.model_dump(mode="json")
    factual = Runner(world)
    proposer: Proposer
    service = RemediationService.for_runtime(
        runtime, publish=lambda event: proposer.publish(event), state_dir=state, background=False
    )
    proposer_options: dict[str, Any] = {}
    if memory is not None:
        proposer_options["memory"] = memory
    proposer = Proposer(journal, service, **proposer_options)
    runtime.on_incident = proposer.on_incident
    cut: Segment | None = None
    prefix_ids: set[str] = set()

    def on_tick(as_of: datetime) -> None:
        nonlocal cut, prefix_ids
        service.tick(as_of)
        pending = next((item for item in service.proposals() if item.state == "AWAIT_OPERATOR"), None)
        if cut is None and (pending is not None or (scenario == "s1" and runtime.book.incidents)):
            cut = _snapshot(runtime, journal, service, recorded_seconds)
            prefix_ids = set(runtime.runner.receipts)
            _ask_at_cut(runtime, journal, cut, scenario)
        if pending is not None and decide != "none":
            choice = Decision(decision=decide, principal=OPERATOR, at=as_of)
            service.decide(pending.id, pending.digest, choice, idempotency_key=f"record-{pending.id}")

    try:
        runtime.run(on_tick=on_tick)
        if cut is None or client.position != len(client.expected) or not journal.runs:
            raise CaptureMismatch(f"strict replay did not complete through turn {client.position + 1}")
        if any(run.status != "done" for run in journal.runs.values()):
            raise CaptureMismatch("a replayed investigation fell back")
        last = _snapshot(runtime, journal, service, recorded_seconds)
        if not fork_deny and not sealed:
            _compare("activity", last.activity, _read_lines(source / "activity.jsonl"))
            _compare("C5 events", last.events, _read_lines(source / "events.jsonl"))
        cut.receipts = _proofs(cut.bindings() | set(receipt_keys(graph)), runtime, service, factual, prefix_ids)
        if scenario == "s1":
            return Trace(graph, cut, None, client.pins(config))
        tail = Segment(last.events[len(cut.events) :], last.activity[len(cut.activity) :], last.incidents, last.actions)
        tail.receipts = _proofs(tail.bindings() - cut.receipts.keys(), runtime, service, factual, prefix_ids)
        return Trace(graph, cut, tail, client.pins(config))
    finally:
        service.close()
        runtime.runner.close()
        factual.close()


def _recording_world(scenario: str, seed: int, root: Path, config: ReplayConfig) -> tuple[Path, dict[str, Any]]:
    world = generate(scenario, WorldConfig(seed=seed), root)
    public = json.loads(world.manifest.read_bytes())
    public.pop("seconds", None)
    if config.profile == "v2":
        # Proposal digests bind the manifest bytes. Generation timing is independent of the simulated world.
        world.manifest.write_bytes(canonical_json(public) + b"\n")
    return world.world, public


def stage(
    source: Path,
    output: Path,
    scenario: Literal["s1", "s4"],
    seed: int,
    source_commit: str,
    denial: Path | None,
    *,
    config: ReplayConfig = V1_REPLAY,
) -> Bundle:
    if scenario == "s4" and denial is None:
        raise ValueError("S4 needs an independently recorded denial")
    config.check_session(source)
    if denial is not None:
        config.check_session(denial)
    summaries = [RunSummary.model_validate(row) for row in json.loads((source / "runs.json").read_bytes())]
    if not summaries or any(run.mode != "record" or run.status != "done" or run.llm_calls < 2 for run in summaries):
        raise CaptureMismatch("the genuine capture must contain a complete model investigation")
    with tempfile.TemporaryDirectory(prefix="argus-presentation-") as work:
        root = Path(work)
        world, public_world = _recording_world(scenario, seed, root / "world", config)
        live = _trace(world, source, scenario, root / "approved", config=config)
        alternate = None
        if denial is not None:
            _trace(world, denial, scenario, root / "independent-denial", config=config)
            alternate = _trace(world, source, scenario, root / "common-prefix-denial", fork_deny=True, config=config)
            _check_shared_prefix(live.prefix, alternate.prefix)
            if alternate.continuation is None:
                raise CaptureMismatch("the denial did not continue past the shared proposal")
    output.mkdir(parents=True, exist_ok=False)
    live.prefix.write(output)
    if live.continuation is not None and alternate is not None and alternate.continuation is not None:
        live.continuation.write(output / "approve")
        alternate.continuation.write(output / "deny")
    turns = Cassette.load(source / "turns.jsonl")
    turns.write(output / "turns.jsonl")
    manifest = {
        "schema_version": 1,
        "provenance": "live_capture",
        "source_commit": source_commit,
        "scenario": scenario,
        "seed": seed,
        "interface_version": INTERFACE_VERSION,
        "prompt_sha": live.pins[0],
        "tools_sha": live.pins[1],
        "models": sorted({turn["response"]["model"] for turn in turns.lines}),
        "world": public_world,
        **config.metadata(output),
    }
    (output / "graph.json").write_bytes(canonical_json(live.graph) + b"\n")
    (output / "manifest.json").write_bytes(canonical_json(manifest) + b"\n")
    return seal(output)


def _verify_segment(segment: Segment, bundle: Bundle, prefix: str = "") -> None:
    exported = bundle.documents
    for filename, rows in (
        ("activity.jsonl", segment.activity),
        ("events.jsonl", segment.events),
        ("incidents.json", segment.incidents),
        ("actions.json", segment.actions),
        ("ask.jsonl", segment.asks),
    ):
        _compare(prefix + filename, rows, exported.get(prefix + filename, []))
    sealed_receipts = exported.get(prefix + "receipts.json", {})
    if {k: v["receipt"] for k, v in segment.receipts.items()} != {k: v["receipt"] for k, v in sealed_receipts.items()}:
        raise CaptureMismatch(f"{prefix} receipt proofs differ from the seal")


def verify_presentation(directory: Path, digest: str) -> Bundle:
    """Cold strict replay of a pinned v2 stage bundle, including both operator continuations."""
    bundle = read_bundle(directory, expected_digest=digest)
    manifest = bundle.manifest
    if manifest.profile != "v2":
        raise CaptureMismatch("cold presentation reconstruction requires a v2 seal")
    config = ReplayConfig.from_manifest(manifest, directory)
    scenario: Literal["s1", "s4"] = "s4" if manifest.scenario == "s4" else "s1"
    with tempfile.TemporaryDirectory(prefix="argus-presentation-replay-") as work:
        root = Path(work)
        world, public_world = _recording_world(scenario, manifest.seed, root / "world", config)
        if public_world != manifest.world:
            raise CaptureMismatch("generated world settings differ from the seal")
        replay = _trace(world, directory, scenario, root / "approve", config=config, sealed=True)
        if replay.pins != (manifest.prompt_sha, manifest.tools_sha):
            raise CaptureMismatch("detective prompt or tools do not match the seal")
        if canonical_json(replay.graph) != canonical_json(bundle.documents["graph.json"]):
            raise CaptureMismatch("graph differs from the seal")
        _verify_segment(replay.prefix, bundle)
        if scenario == "s4":
            denied = _trace(world, directory, scenario, root / "deny", config=config, sealed=True, fork_deny=True)
            _check_shared_prefix(replay.prefix, denied.prefix)
            if replay.continuation is None or denied.continuation is None:
                raise CaptureMismatch("an S4 continuation did not complete")
            _verify_segment(replay.continuation, bundle, "approve/")
            _verify_segment(denied.continuation, bundle, "deny/")
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--scenario", choices=("s1", "s4"), required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--denial", type=Path)
    add_profile_options(parser)
    args = parser.parse_args()
    try:
        bundle = stage(
            args.source,
            args.output,
            args.scenario,
            args.seed,
            args.source_commit,
            args.denial,
            config=profile_options(args),
        )
    except CaptureMismatch as exc:
        parser.exit(1, f"Presentation replay failed: {exc}\n")
    except (AssertionError, KeyError, OSError, StopIteration, TypeError, ValueError):
        parser.exit(1, "Presentation staging failed while validating its branches and receipt proofs.\n")
    print(f"{bundle.manifest.scenario}: sealed presentation bundle {bundle.manifest.bundle_sha}")


if __name__ == "__main__":
    main()
