"""Prepare an independent live trial and archive the result for qualification."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter
from scripts.agent_eval.bundle import Bundle, canonical_json, read_bundle
from scripts.agent_eval.qualify import CASES, TRIALS, Trial

from argus.agent.types import RunSummary, UsageRecord
from argus.contracts.events import Event, EventType
from argus.contracts.findings import Anomaly, Incident, Note
from bench.agents import AgentOutput
from bench.runner import SealedCase, grade_case, reveal
from bench.sealed import Envelope, canonical_truth, seal
from mockmart.sim import WorldConfig
from mockmart.world import generate


class PreparedTrial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Literal["s1", "s4"]
    seed: int
    trial: int
    source_commit: str
    commitment: str
    nonce: str


def _write(path: Path, value: BaseModel) -> None:
    path.write_bytes(canonical_json(value.model_dump(mode="json")) + b"\n")


def prepare(archive: Path, scenario: Literal["s1", "s4"], seed: int, trial: int, commit: str) -> Path:
    if (scenario, seed) not in CASES or not 1 <= trial <= TRIALS:
        raise ValueError("trial is outside the qualification cohort")
    slot = archive / f"{scenario}-{seed}-{trial}"
    slot.mkdir(parents=True, exist_ok=False)
    world = generate(scenario, WorldConfig(seed=seed), slot / "world")
    envelope = seal(world.truth)
    meta = PreparedTrial(
        scenario=scenario,
        seed=seed,
        trial=trial,
        source_commit=commit,
        commitment=envelope.commitment,
        nonce=envelope.nonce,
    )
    _write(slot / "prepared.json", meta)
    (slot / "commitment.json").write_bytes(
        canonical_json(
            {"case": slot.name, "commitment": envelope.commitment, "sealed_at": datetime.now(UTC).isoformat()}
        )
        + b"\n"
    )
    return world.world


def _agent_output(bundle: Bundle) -> AgentOutput:
    doc = bundle.documents
    approved = "approve/" if bundle.manifest.scenario == "s4" else ""
    events = [Event.model_validate(row) for row in doc["events.jsonl"]]
    if approved:
        events.extend(Event.model_validate(row) for row in doc[f"{approved}events.jsonl"])
    return AgentOutput(
        events=events,
        incidents=[Incident.model_validate(row) for row in doc[f"{approved}incidents.json"]],
        anomalies=[Anomaly.model_validate(event.payload) for event in events if event.type == EventType.ANOMALY_OPENED],
        notes=[Note.model_validate(event.payload) for event in events if event.type == EventType.NOTE_LOGGED],
    )


def finish(
    slot: Path,
    journal: Path,
    elapsed_seconds: float,
    *,
    capture: Path | None = None,
    digest: str | None = None,
    failure: str | None = None,
) -> Trial:
    if (slot / "trial.json").exists():
        raise ValueError("trial already archived")
    if (capture is None) != (digest is None) or (capture is None and not failure):
        raise ValueError("provide the sealed capture and digest, or the failure outcome")
    meta = PreparedTrial.model_validate_json((slot / "prepared.json").read_bytes())
    runs = journal / "runs.json"
    usage = journal / "usage.jsonl"
    trial = Trial(
        scenario=meta.scenario,
        seed=meta.seed,
        trial=meta.trial,
        source_commit=meta.source_commit,
        elapsed_seconds=elapsed_seconds,
        bundle_sha=digest,
        runs=TypeAdapter(list[RunSummary]).validate_json(runs.read_bytes()) if runs.is_file() else [],
        usage=[UsageRecord.model_validate_json(line) for line in usage.read_bytes().splitlines() if line]
        if usage.is_file()
        else [],
        failure=failure,
    )
    if capture is not None and digest is not None:
        bundle = read_bundle(capture, expected_digest=digest)
        manifest = bundle.manifest
        if (manifest.scenario, manifest.seed, manifest.source_commit) != (meta.scenario, meta.seed, meta.source_commit):
            raise ValueError("the live capture belongs to a different trial")
        world = slot / "world"
        prepared_world = json.loads((world / "manifest.json").read_bytes())
        prepared_world.pop("seconds", None)
        if any(manifest.world.get(key) != value for key, value in prepared_world.items()):
            raise ValueError("live capture world differs from the sealed trial")
        truth = world / "truth.duckdb"
        # Keep the simulator's private truth beside its world. Only this evaluator opens it directly.
        case = SealedCase(
            case=slot.name,
            scenario=meta.scenario,
            seed=meta.seed,
            dir=slot,
            world=world / "world.duckdb",
            manifest=world / "manifest.json",
            truth=truth,
            envelope=Envelope(meta.commitment, meta.nonce, canonical_truth(truth)),
        )
        trial.grade = grade_case(case, "argus-stage3", _agent_output(bundle), elapsed_seconds, reveal(case))
        destination = slot / "bundle"
        if destination.exists():
            read_bundle(destination, expected_digest=digest)
        else:
            shutil.copytree(capture, destination)
    _write(slot / "trial.json", trial)
    return trial


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("prepare", help="generate a fresh world and seal its grading truth")
    setup.add_argument("archive", type=Path)
    setup.add_argument("scenario", choices=("s1", "s4"))
    setup.add_argument("seed", type=int)
    setup.add_argument("trial", type=int)
    save = commands.add_parser("finish", help="archive the sealed capture or failure and paid usage")
    save.add_argument("slot", type=Path)
    save.add_argument("--journal", type=Path, required=True)
    save.add_argument("--elapsed-seconds", type=float, required=True)
    save.add_argument("--capture", type=Path)
    save.add_argument("--digest")
    save.add_argument("--failure")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            print(prepare(args.archive, args.scenario, args.seed, args.trial, commit))
        else:
            finish(
                args.slot,
                args.journal,
                args.elapsed_seconds,
                capture=args.capture,
                digest=args.digest,
                failure=args.failure,
            )
    except (KeyError, OSError, TypeError, ValueError):
        parser.exit(1, "Trial archive failed. Check its identity, path, capture, and metered usage.\n")


if __name__ == "__main__":
    main()
