"""Seal and verify the files that feed the three offline replay modes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from argus.agent.types import INTERFACE_VERSION, ActivityRecord, LlmResponse, ProposalView
from argus.contracts.events import Event
from argus.contracts.findings import Receipt
from argus.contracts.graph import Graph
from argus.semantic.runner import canonical_hash

SHA256 = re.compile(r"[a-f0-9]{64}")
GIT_SHA = re.compile(r"[a-f0-9]{40}")
REQUIRED = {"turns.jsonl", "events.jsonl", "activity.jsonl", "actions.json", "receipts.json", "graph.json", "ask.jsonl"}
OPTIONAL = {"incidents.json", "notes.json"}
CASSETTE_FILES = {"turns.jsonl", "events.jsonl", "activity.jsonl", "receipts.json", "graph.json", "incidents.json"}
BRANCH_REQUIRED = {"events.jsonl", "activity.jsonl", "actions.json"}
BRANCH_OPTIONAL = {"receipts.json", "ask.jsonl"} | OPTIONAL
BRANCHES = ("approve", "deny")
FEATURES = frozenset({"critic", "sql", "hypotheses", "memory", "second_opinion"})
FORBIDDEN_KEYS = {
    "api_key",
    "authorization",
    "headers",
    "nonce",
    "private_reasoning",
    "sealed_truth",
    "truth",
    "x_api_key",
}
SECRET_PATTERN = re.compile(r"\b(?:sk-(?:ant-|proj-)?[\w-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key in recording JSON")
        result[key] = value
    return result


def _invalid_constant(_: str) -> Any:
    raise ValueError("non-finite number in recording JSON")


def _json(data: bytes) -> Any:
    return json.loads(data, object_pairs_hook=_unique_keys, parse_constant=_invalid_constant)


def _decode(path: str, data: bytes) -> Any:
    try:
        if path.endswith(".jsonl"):
            return [_json(line) for line in data.splitlines() if line.strip()]
        return _json(data)
    except (ValueError, UnicodeError):
        raise ValueError(f"{path}: invalid recording JSON") from None


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: int
    provenance: str
    source_commit: str
    scenario: str
    seed: int = Field(ge=1)
    interface_version: str = Field(min_length=1)
    prompt_sha: str
    tools_sha: str
    models: list[str] = Field(min_length=1)
    world: dict[str, Any] = Field(min_length=1)
    graph_sha: str
    artifacts: dict[str, str]
    bundle_sha: str
    profile: Literal["v2"] | None = None
    features: list[str] | None = None
    memory_sha: str | None = None


class ReceiptProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt: Receipt
    columns: list[str]
    rows: list[list[Any]]
    verified_at_capture: bool


@dataclass(frozen=True)
class Bundle:
    manifest: Manifest
    documents: dict[str, Any]


def _scan(value: Any, path: str, secrets: tuple[str, ...]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower().replace("-", "_") in FORBIDDEN_KEYS:
                raise ValueError(f"{path}: contains forbidden capture data")
            _scan(key, path, secrets)
            _scan(item, path, secrets)
    elif isinstance(value, list):
        for item in value:
            _scan(item, path, secrets)
    elif isinstance(value, str) and (SECRET_PATTERN.search(value) or any(secret in value for secret in secrets)):
        raise ValueError(f"{path}: contains credential-like data")


def _files(directory: Path, scenario: str, presentation: bool, *, seeded: bool = False) -> dict[str, bytes]:
    required = set(REQUIRED if presentation else CASSETTE_FILES)
    if seeded:
        required.add("memory.jsonl")
    allowed = required | OPTIONAL
    branches = presentation and scenario == "s4"
    if branches:
        for branch in BRANCHES:
            required.update(f"{branch}/{file}" for file in BRANCH_REQUIRED)
            allowed.update(f"{branch}/{file}" for file in BRANCH_REQUIRED | BRANCH_OPTIONAL)
    found: dict[str, bytes] = {}
    for path in directory.rglob("*"):
        name = path.relative_to(directory).as_posix()
        if path.is_symlink():
            raise ValueError(f"{name}: symlink in recording directory")
        if path.is_dir() and branches and name in BRANCHES:
            continue
        if name == "manifest.json":
            continue
        if name not in allowed or not path.is_file():
            raise ValueError(f"{name}: undeclared recording artifact")
        found[name] = path.read_bytes()
    if missing := required - found.keys():
        raise ValueError(f"missing recording artifacts: {', '.join(sorted(missing))}")
    return found


def _turns(turns: list[dict[str, Any]], manifest: Manifest) -> None:
    seen: set[str] = set()
    returned_models: set[str] = set()
    if not turns:
        raise ValueError("turns.jsonl: empty provider exchange")
    turn_kinds = "investigate|ask|morning|verify_effect"
    if manifest.profile == "v2" and "critic" in (manifest.features or []):
        turn_kinds += "|critic"
    for index, turn in enumerate(turns, 1):
        try:
            key = turn["key"]
            response = LlmResponse.model_validate(turn["response"])
            usage = response.usage
            if (
                not isinstance(key, str)
                or not re.fullmatch(rf"(?:{turn_kinds}):.+:[1-9]\d*", key)
                or key in seen
                or not re.fullmatch(r"sha256:[a-f0-9]{64}", turn["request_sha"])
                or not response.stop_reason
                or response.request_id is not None
                or any(block["type"] not in {"text", "tool_use"} for block in response.content)
                or not {"input_tokens", "output_tokens"} <= usage.keys()
                or any(type(count) is not int or count < 0 for count in turn["response"]["usage"].values())
            ):
                raise ValueError
            seen.add(key)
            returned_models.add(response.model)
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"turns.jsonl: invalid exchange at turn {index}") from None
    if len(manifest.models) != len(returned_models) or set(manifest.models) != returned_models:
        raise ValueError("turns.jsonl: returned models do not match manifest")


def receipt_keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        if {"run_id", "world_revision", "receipt_id"} <= value.keys():
            yield "/".join(value[field] for field in ("run_id", "world_revision", "receipt_id"))
        for field, child in value.items():
            if field == "receipt" and isinstance(child, str):
                yield child
            elif field == "receipts" and isinstance(child, list):
                yield from (item for item in child if isinstance(item, str))
            yield from receipt_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from receipt_keys(child)


def _links(value: Any, receipts: dict[str, ReceiptProof], visible_at: datetime | None = None) -> None:
    for key in receipt_keys(value):
        label = "qualified" if "/" in key else "C4"
        if key not in receipts:
            raise ValueError(f"missing {label} receipt {key}")
        if visible_at is not None and receipts[key].receipt.as_of > visible_at:
            raise ValueError(f"future {label} receipt {key}")


def _receipts(raw: dict[str, Any], require_verified: bool) -> dict[str, ReceiptProof]:
    proofs = {key: ReceiptProof.model_validate(entry) for key, entry in raw.items()}
    for key, proof in proofs.items():
        receipt = proof.receipt
        if (
            key.split("/")[-1] != receipt.id
            or (require_verified and not proof.verified_at_capture)
            or len(proof.rows) > receipt.rows
            or any(len(row) != len(proof.columns) for row in proof.rows)
        ):
            raise ValueError(f"invalid capture proof for receipt {key}")
        if (
            len(proof.rows) == receipt.rows
            and canonical_hash([tuple(row) for row in proof.rows]) != receipt.result_hash
        ):
            raise ValueError(f"rows do not match result hash for receipt {key}")
    return proofs


def _ordered(records: list[dict[str, Any]], filename: str, after: int) -> int:
    for record in records:
        seq = record["seq"]
        if type(seq) is not int or seq <= after:
            raise ValueError(f"{filename}: sequence did not increase after {after}")
        after = seq
    return after


def _cut(documents: dict[str, Any]) -> None:
    root = documents["actions.json"]
    if len(root) != 1 or root[0]["state"] != "AWAIT_OPERATOR" or root[0].get("decision") is not None:
        raise ValueError("S4 recording must stop its prefix at the pending rollback")
    action = root[0]
    prefix = documents["activity.jsonl"]
    if (
        not prefix
        or prefix[-1]["kind"] != "action_proposed"
        or prefix[-1].get("action_id") != action["id"]
        or any(item["kind"] in {"action_decided", "action_applied", "effect_checked"} for item in prefix)
    ):
        raise ValueError("S4 recording must cut activity at action_proposed")
    for branch, state in (("approve", "VERIFIED"), ("deny", "DENIED")):
        activity = documents[f"{branch}/activity.jsonl"]
        actions = documents[f"{branch}/actions.json"]
        if (
            not activity
            or activity[0]["kind"] != "action_decided"
            or activity[0]["actor"] != "operator"
            or activity[0].get("action_id") != action["id"]
            or len(actions) != 1
            or actions[0]["id"] != action["id"]
            or actions[0]["digest"] != action["digest"]
            or actions[0]["state"] != state
            or actions[0]["decision"]["decision"] != branch
        ):
            raise ValueError(f"S4 {branch} continuation must begin at the matching operator decision")
        applied = [item for item in activity if item["kind"] == "action_applied"]
        if branch == "approve":
            effect = actions[0]["effect"]
            checked = [item for item in activity if item["kind"] == "effect_checked"]
            if (
                len(applied) != 1
                or applied[0].get("action_id") != action["id"]
                or effect["state"] != "VERIFIED"
                or len(effect["receipt_refs"]) < 2
                or not any(
                    item["seq"] > applied[0]["seq"] and item.get("action_id") == action["id"] for item in checked
                )
            ):
                raise ValueError("S4 approval requires one application and receipted treated/twin effect")
        elif applied or any(item["kind"] == "effect_checked" for item in activity):
            raise ValueError("S4 denial contains application or effect activity")


def _validate_documents(documents: dict[str, Any], manifest: Manifest, presentation: bool) -> None:
    if sha256(canonical_json(documents["graph.json"])) != manifest.graph_sha:
        raise ValueError("graph identity does not match manifest")
    Graph.model_validate(documents["graph.json"])
    _turns(documents["turns.jsonl"], manifest)
    latest_event = _ordered(documents["events.jsonl"], "events.jsonl", 0)
    latest_activity = _ordered(documents["activity.jsonl"], "activity.jsonl", 0)
    if not latest_event or not latest_activity:
        raise ValueError("empty presentation stream")
    base_receipts = _receipts(documents["receipts.json"], manifest.provenance == "live_capture")
    prefix_clock = {
        event.seq: event.sim_ts for event in (Event.model_validate(raw) for raw in documents["events.jsonl"])
    }
    branches = BRANCHES if presentation and manifest.scenario == "s4" else ()
    for prefix in ("", *(f"{branch}/" for branch in branches)):
        receipts = base_receipts
        through_seq = latest_event
        if prefix:
            extra_receipts = _receipts(
                documents.get(f"{prefix}receipts.json", {}), manifest.provenance == "live_capture"
            )
            if receipts.keys() & extra_receipts.keys():
                raise ValueError(f"{prefix}receipt replaces a pre-decision binding")
            receipts = receipts | extra_receipts
            through_seq = _ordered(documents[f"{prefix}events.jsonl"], f"{prefix}events.jsonl", latest_event)
            _ordered(documents[f"{prefix}activity.jsonl"], f"{prefix}activity.jsonl", latest_activity)
        clock = prefix_clock.copy()
        for raw in documents[f"{prefix}events.jsonl"]:
            event = Event.model_validate(raw)
            clock[event.seq] = event.sim_ts
            _links(event.payload, receipts, event.sim_ts)
        for raw in documents[f"{prefix}activity.jsonl"]:
            activity = ActivityRecord.model_validate(raw)
            _links(raw, receipts, activity.sim_ts)
        for action in documents.get(f"{prefix}actions.json", []):
            ProposalView.model_validate(action)
        for answer in documents.get(f"{prefix}ask.jsonl", []):
            if not answer["question"].strip() or answer["through_seq"] not in clock:
                raise ValueError(f"{prefix}ask.jsonl: answer outside visible event prefix")
            _links(answer["response"], receipts, clock[answer["through_seq"]])
        for filename in (*OPTIONAL, "actions.json"):
            _links(documents.get(f"{prefix}{filename}"), receipts, clock[through_seq])
    if branches:
        _cut(documents)


def _validate_bundle(directory: Path, raw: Any, expected_digest: str, require_live: bool, presentation: bool) -> Bundle:
    manifest = Manifest.model_validate(raw)
    body = manifest.model_dump(exclude={"bundle_sha"}, exclude_unset=True)
    if not SHA256.fullmatch(expected_digest) or manifest.bundle_sha != expected_digest:
        raise ValueError("bundle digest does not match the expected pin")
    if sha256(canonical_json(body)) != expected_digest:
        raise ValueError("manifest contents do not match the pinned bundle digest")
    if (
        manifest.schema_version != 1
        or manifest.scenario not in {"s1", "s4"}
        or manifest.interface_version != INTERFACE_VERSION
        or manifest.provenance not in {"live_capture", "synthetic_test"}
        or (require_live and manifest.provenance != "live_capture")
        or not GIT_SHA.fullmatch(manifest.source_commit)
        or any(not SHA256.fullmatch(value) for value in (manifest.prompt_sha, manifest.tools_sha, manifest.graph_sha))
    ):
        raise ValueError("unsupported recording manifest metadata or provenance")
    if manifest.profile == "v2":
        features = manifest.features
        if (
            features is None
            or features != sorted(set(features))
            or set(features) - {"critic", "sql", "hypotheses", "memory", "second_opinion"}
        ):
            raise ValueError("unsupported or noncanonical v2 feature list")
        if "memory_sha" in body and (
            "memory" not in features or manifest.memory_sha is None or not SHA256.fullmatch(manifest.memory_sha)
        ):
            raise ValueError("invalid v2 memory pin")
    elif {"profile", "features", "memory_sha"} & body.keys():
        raise ValueError("v2 recording metadata requires profile v2")
    artifacts = _files(directory, manifest.scenario, presentation, seeded=manifest.memory_sha is not None)
    if {key: sha256(content) for key, content in artifacts.items()} != manifest.artifacts:
        raise ValueError("recording artifacts do not match the pinned manifest")
    if manifest.memory_sha is not None and manifest.artifacts["memory.jsonl"] != manifest.memory_sha:
        raise ValueError("memory seed does not match its pin")
    secrets = tuple(
        value for key, value in os.environ.items() if key.endswith(("_API_KEY", "_AUTH_TOKEN")) and len(value) >= 8
    )
    _scan(body, "manifest.json", secrets)
    documents = {name: _decode(name, content) for name, content in artifacts.items()}
    for name, document in documents.items():
        _scan(document, name, secrets)
    _validate_documents(documents, manifest, presentation)
    return Bundle(manifest, documents)


def read_bundle(
    directory: Path, *, expected_digest: str, require_live: bool = True, presentation: bool = True
) -> Bundle:
    """Check a separately pinned digest before parsing and trusting any payload."""
    path = directory / "manifest.json"
    if path.is_symlink():
        raise ValueError("manifest.json: symlink in recording directory")
    return _validate_bundle(directory, _json(path.read_bytes()), expected_digest, require_live, presentation)


def seal(directory: Path, *, presentation: bool = True) -> Bundle:
    """Fill hashes in a staged capture manifest and verify the complete bundle."""
    path = directory / "manifest.json"
    if path.is_symlink():
        raise ValueError("manifest.json: symlink in recording directory")
    metadata = _json(path.read_bytes())
    artifacts = _files(directory, metadata["scenario"], presentation, seeded=metadata.get("memory_sha") is not None)
    metadata.update(
        graph_sha=sha256(canonical_json(_decode("graph.json", artifacts["graph.json"]))),
        artifacts={name: sha256(content) for name, content in artifacts.items()},
    )
    metadata.pop("bundle_sha", None)
    digest = sha256(canonical_json(metadata))
    sealed = metadata | {"bundle_sha": digest}
    bundle = _validate_bundle(directory, sealed, digest, False, presentation)
    file_descriptor, temporary = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(canonical_json(sealed) + b"\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seal", action="store_true", help="seal a staged capture")
    group.add_argument("--digest", help="check a live capture against an external pin")
    parser.add_argument("--cassette", action="store_true", help="verify an investigation cassette")
    args = parser.parse_args()
    try:
        if args.seal:
            bundle = seal(args.capture, presentation=not args.cassette)
        else:
            bundle = read_bundle(args.capture, expected_digest=args.digest, presentation=not args.cassette)
    except (KeyError, OSError, TypeError, ValueError):
        parser.exit(1, "Recording verification failed. Inspect the staged capture for invalid or forbidden data.\n")
    print(f"{bundle.manifest.scenario}: {bundle.manifest.bundle_sha} ({bundle.manifest.provenance})")


if __name__ == "__main__":
    main()
