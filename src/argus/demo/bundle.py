"""Load a pinned presentation recording without opening a world or constructing a provider."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from argus.agent.types import INTERFACE_VERSION, ActivityRecord, ProposalView, ReceiptLink, VerifiedClaim
from argus.contracts.events import Event
from argus.contracts.findings import Incident, Receipt
from argus.contracts.graph import Graph
from argus.demo.contracts import AgentScenario, Decision
from argus.semantic.runner import canonical_hash

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Manifest(_Strict):
    schema_version: Literal[1]
    provenance: Literal["live_capture", "synthetic_test"]
    source_commit: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    scenario: AgentScenario
    seed: int
    interface_version: str
    prompt_sha: Sha256
    tools_sha: Sha256
    models: list[str]
    world: dict[str, Any]
    graph_sha: Sha256
    artifacts: dict[str, Sha256]
    bundle_sha: Sha256


class ReceiptProof(_Strict):
    receipt: Receipt
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    verified_at_capture: bool


class AskAnswer(_Strict):
    status: str
    answer: str
    claims: list[VerifiedClaim]
    receipt_links: list[ReceiptLink]
    activity_cursor: int | None
    run_id: str | None = None
    reason: str | None = None
    usd: float = Field(default=0, ge=0, allow_inf_nan=False)


class RecordedAsk(_Strict):
    question: str
    through_seq: int = Field(ge=0)
    response: AskAnswer


@dataclass(frozen=True)
class Segment:
    events: tuple[Event, ...]
    activity: tuple[ActivityRecord, ...]
    actions: dict[str, ProposalView]
    receipts: dict[str, ReceiptProof]
    questions: tuple[RecordedAsk, ...]
    incidents: tuple[Incident, ...]


@dataclass(frozen=True)
class AgentBundle:
    manifest: Manifest
    graph: Graph
    prefix: Segment
    approve: Segment | None
    deny: Segment | None

    def continuation(self, decision: Decision | None) -> Segment | None:
        if decision == "approve":
            return self.approve
        if decision == "deny":
            return self.deny
        return None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _lines[T: BaseModel](data: bytes, model: type[T]) -> tuple[T, ...]:
    return tuple(model.model_validate_json(line) for line in data.splitlines() if line.strip())


def _strict_order(records: Sequence[Event | ActivityRecord]) -> None:
    if any(r.sim_ts.tzinfo is not None for r in records):
        raise ValueError("presentation timestamps must be naive UTC")
    if (records and records[0].seq < 1) or any(a.seq >= b.seq or a.sim_ts > b.sim_ts for a, b in pairwise(records)):
        raise ValueError("presentation records must be ordered by increasing sequence and simulated time")


def receipt_keys(data: Any) -> Iterator[str]:
    """Find qualified agent links and unqualified C4/C5 references in a wire model."""
    if isinstance(data, dict):
        if all(isinstance(data.get(key), str) for key in ("run_id", "world_revision", "receipt_id")):
            yield f"{data['run_id']}/{data['world_revision']}/{data['receipt_id']}"
        for key, value in data.items():
            if key == "receipt" and isinstance(value, str):
                yield value
            elif key == "receipts" and isinstance(value, list):
                yield from (item for item in value if isinstance(item, str))
            yield from receipt_keys(value)
    elif isinstance(data, list):
        for value in data:
            yield from receipt_keys(value)


def read_bundle(
    path: Path,
    scenario: AgentScenario,
    expected_sha: str,
    *,
    allow_synthetic: bool = False,
) -> AgentBundle:
    """Check the external digest pin and every listed file before parsing the visible data."""
    manifest_path = path / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("presentation manifest must be a regular file")
    raw = json.loads(manifest_path.read_bytes())
    manifest = Manifest.model_validate(raw)
    del raw["bundle_sha"]
    if _sha(_canonical(raw)) != expected_sha or manifest.bundle_sha != expected_sha:
        raise ValueError("presentation bundle does not match the configured digest")
    if manifest.scenario != scenario or manifest.interface_version != INTERFACE_VERSION:
        raise ValueError("presentation bundle scenario or agent interface does not match")
    if not allow_synthetic and manifest.provenance != "live_capture":
        raise ValueError("presentation bundle has no live capture provenance")
    if not manifest.models:
        raise ValueError("presentation bundle has no returned model identifiers")

    artifacts: dict[str, bytes] = {}
    root = path.resolve()
    for name, sha in manifest.artifacts.items():
        relative = Path(name)
        artifact = root / relative
        if (
            not artifact.resolve().is_relative_to(root)
            or ".." in relative.parts
            or str(relative) != name
            or relative.is_absolute()
            or artifact.is_symlink()
        ):
            raise ValueError("presentation manifest contains an invalid artifact path")
        data = artifact.read_bytes()
        if _sha(data) != sha:
            raise ValueError(f"presentation artifact digest mismatch: {name}")
        artifacts[name] = data

    def require(name: str) -> bytes:
        if name not in artifacts:
            raise ValueError(f"presentation manifest omits {name}")
        return artifacts[name]

    def segment(directory: str) -> Segment:
        actions = TypeAdapter(list[ProposalView]).validate_json(require(f"{directory}actions.json"))
        by_id = {action.id: action for action in actions}
        if len(by_id) != len(actions):
            raise ValueError("presentation contains duplicate action identifiers")
        receipts_name = f"{directory}receipts.json"
        receipt_bytes = artifacts.get(receipts_name, b"{}") if directory else require(receipts_name)
        receipts = TypeAdapter(dict[str, ReceiptProof]).validate_json(receipt_bytes)
        for key, proof in receipts.items():
            receipt = proof.receipt
            if (
                key.rsplit("/", 1)[-1] != receipt.id
                or (manifest.provenance == "live_capture" and not proof.verified_at_capture)
                or len(proof.rows) > receipt.rows
                or any(len(row) != len(proof.columns) for row in proof.rows)
                or (
                    len(proof.rows) == receipt.rows
                    and canonical_hash([tuple(row) for row in proof.rows]) != receipt.result_hash
                )
            ):
                raise ValueError(f"invalid proof for presentation receipt {key}")
        return Segment(
            _lines(require(f"{directory}events.jsonl"), Event),
            _lines(require(f"{directory}activity.jsonl"), ActivityRecord),
            by_id,
            receipts,
            _lines(artifacts.get(f"{directory}ask.jsonl", b""), RecordedAsk),
            tuple(TypeAdapter(list[Incident]).validate_json(artifacts.get(f"{directory}incidents.json", b"[]"))),
        )

    if not require("turns.jsonl").strip():
        raise ValueError("presentation bundle has no recorded provider exchange")
    require("ask.jsonl")
    graph_document = json.loads(require("graph.json"))
    if _sha(_canonical(graph_document)) != manifest.graph_sha:
        raise ValueError("presentation graph does not match the captured graph digest")
    graph = Graph.model_validate(graph_document)
    prefix = segment("")
    approve = segment("approve/") if scenario == "s4" else None
    deny = segment("deny/") if scenario == "s4" else None
    _validate_branch(graph, prefix)
    for branch in (approve, deny):
        if branch is not None:
            _validate_branch(graph, prefix, branch)
    return AgentBundle(manifest, graph, prefix, approve, deny)


def _validate_branch(graph: Graph, prefix: Segment, branch: Segment | None = None) -> None:
    events = prefix.events + (branch.events if branch else ())
    activity = prefix.activity + (branch.activity if branch else ())
    _strict_order(events)
    _strict_order(activity)
    if not events or not activity:
        raise ValueError("presentation has an empty recording prefix")
    clock = {event.seq: event.sim_ts for event in events}
    receipts = dict(prefix.receipts)
    parts = (prefix, branch) if branch else (prefix,)
    for part in parts:
        for key, proof in part.receipts.items():
            if proof.receipt.as_of.tzinfo is not None:
                raise ValueError("presentation receipt timestamps must be naive UTC")
            if key in receipts and receipts[key] != proof:
                raise ValueError(f"presentation continuation replaces receipt {key}")
            receipts[key] = proof
        if any(question.through_seq not in clock or not question.question.strip() for question in part.questions):
            raise ValueError("recorded Ask response refers to an unknown event sequence")

    def check(model: BaseModel, at: datetime) -> None:
        for key in receipt_keys(model.model_dump(mode="json")):
            proof = receipts.get(key)
            if proof is None or proof.receipt.as_of > at:
                raise ValueError(f"presentation refers to a missing or future receipt: {key}")

    check(graph, events[0].sim_ts)
    for event in events:
        check(event, event.sim_ts)
    for record in activity:
        check(record, record.sim_ts)
    for part in parts:
        for incident in part.incidents:
            check(incident, incident.updated_at)
        for question in part.questions:
            check(question, clock[question.through_seq])
        for action in part.actions.values():
            check(action, action.effect.checked_at if action.effect else activity[-1].sim_ts)
