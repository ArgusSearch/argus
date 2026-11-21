"""Seal and verify the files that feed the three offline replay modes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from argus.contracts.events import Event
from argus.contracts.findings import Receipt
from argus.contracts.graph import Graph
from argus.semantic.runner import canonical_hash

SHA256 = re.compile(r"[a-f0-9]{64}")
GIT_SHA = re.compile(r"[a-f0-9]{40}")
REQUIRED = {"turns.jsonl", "events.jsonl", "activity.jsonl", "actions.json", "receipts.json", "graph.json", "ask.jsonl"}
OPTIONAL = {"incidents.json", "notes.json"}
BRANCH_REQUIRED = {"events.jsonl", "activity.jsonl", "actions.json"}
BRANCH_OPTIONAL = {"receipts.json", "ask.jsonl"} | OPTIONAL
BRANCHES = ("approve", "deny")
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


def _files(directory: Path, scenario: str) -> dict[str, bytes]:
    required = set(REQUIRED)
    allowed = REQUIRED | OPTIONAL
    if scenario == "s4":
        for branch in BRANCHES:
            required.update(f"{branch}/{file}" for file in BRANCH_REQUIRED)
            allowed.update(f"{branch}/{file}" for file in BRANCH_REQUIRED | BRANCH_OPTIONAL)
    found: dict[str, bytes] = {}
    for path in directory.rglob("*"):
        name = path.relative_to(directory).as_posix()
        if path.is_symlink():
            raise ValueError(f"{name}: symlink in recording directory")
        if path.is_dir() and scenario == "s4" and name in BRANCHES:
            continue
        if name == "manifest.json":
            continue
        if name not in allowed or not path.is_file():
            raise ValueError(f"{name}: undeclared recording artifact")
        found[name] = path.read_bytes()
    if missing := required - found.keys():
        raise ValueError(f"missing recording artifacts: {', '.join(sorted(missing))}")
    return found


def _turns(turns: list[dict[str, Any]], models: list[str]) -> None:
    seen: set[str] = set()
    returned_models: set[str] = set()
    if not turns:
        raise ValueError("turns.jsonl: empty provider exchange")
    for index, turn in enumerate(turns, 1):
        try:
            key = turn["key"]
            response = turn["response"]
            content = response["content"]
            usage = response["usage"]
            if (
                key in seen
                or not isinstance(key, str)
                or not SHA256.fullmatch(turn["request_sha"])
                or not response["stop_reason"]
                or response.get("request_id") is not None
                or any(block["type"] not in {"text", "tool_use"} for block in content)
                or not {"input_tokens", "output_tokens"} <= usage.keys()
                or any(type(count) is not int or count < 0 for count in usage.values())
            ):
                raise ValueError
            seen.add(key)
            returned_models.add(response["model"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"turns.jsonl: invalid exchange at turn {index}") from None
    if len(models) != len(returned_models) or set(models) != returned_models:
        raise ValueError("turns.jsonl: returned models do not match manifest")


def _links(value: Any, receipts: dict[str, ReceiptProof]) -> None:
    if isinstance(value, dict):
        if {"run_id", "world_revision", "receipt_id"} <= value.keys():
            key = "/".join(value[field] for field in ("run_id", "world_revision", "receipt_id"))
            if key not in receipts:
                raise ValueError(f"missing qualified receipt {key}")
        for field, child in value.items():
            ids: list[str] = []
            if field == "receipt" and isinstance(child, str):
                ids.append(child)
            elif field == "receipts" and isinstance(child, list):
                ids.extend(item for item in child if isinstance(item, str))
            for receipt_id in ids:
                if receipt_id not in receipts:
                    raise ValueError(f"missing C4 receipt {receipt_id}")
            _links(child, receipts)
    elif isinstance(value, list):
        for child in value:
            _links(child, receipts)


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
            if (
                len(applied) != 1
                or applied[0].get("action_id") != action["id"]
                or effect["state"] != "VERIFIED"
                or len(effect["receipt_refs"]) < 2
            ):
                raise ValueError("S4 approval requires one application and receipted treated/twin effect")
        elif applied or any(item["kind"] == "effect_checked" for item in activity):
            raise ValueError("S4 denial contains application or effect activity")


def _validate_documents(documents: dict[str, Any], manifest: Manifest) -> None:
    if sha256(canonical_json(documents["graph.json"])) != manifest.graph_sha:
        raise ValueError("graph identity does not match manifest")
    Graph.model_validate(documents["graph.json"])
    _turns(documents["turns.jsonl"], manifest.models)
    latest_event = _ordered(documents["events.jsonl"], "events.jsonl", 0)
    latest_activity = _ordered(documents["activity.jsonl"], "activity.jsonl", 0)
    if not latest_event or not latest_activity:
        raise ValueError("empty presentation stream")
    base_receipts = _receipts(documents["receipts.json"], manifest.provenance == "live_capture")
    for prefix in ("", *(f"{branch}/" for branch in BRANCHES if manifest.scenario == "s4")):
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
        for event in documents[f"{prefix}events.jsonl"]:
            Event.model_validate(event)
        for answer in documents.get(f"{prefix}ask.jsonl", []):
            if not answer["question"].strip() or not 0 < answer["through_seq"] <= through_seq:
                raise ValueError(f"{prefix}ask.jsonl: answer outside visible event prefix")
        for filename in REQUIRED | OPTIONAL if not prefix else BRANCH_REQUIRED | BRANCH_OPTIONAL:
            if filename not in {"turns.jsonl", "graph.json", "receipts.json"}:
                _links(documents.get(f"{prefix}{filename}"), receipts)
    if manifest.scenario == "s4":
        _cut(documents)


def read_bundle(directory: Path, *, expected_digest: str, require_live: bool = True) -> Bundle:
    """Check a separately pinned digest before parsing and trusting any payload."""
    if (directory / "manifest.json").is_symlink():
        raise ValueError("manifest.json: symlink in recording directory")
    raw = _json((directory / "manifest.json").read_bytes())
    manifest = Manifest.model_validate(raw)
    body = manifest.model_dump(exclude={"bundle_sha"})
    if not SHA256.fullmatch(expected_digest) or manifest.bundle_sha != expected_digest:
        raise ValueError("bundle digest does not match the expected pin")
    if sha256(canonical_json(body)) != expected_digest:
        raise ValueError("manifest contents do not match the pinned bundle digest")
    if (
        manifest.schema_version != 1
        or manifest.scenario not in {"s1", "s4"}
        or manifest.provenance not in {"live_capture", "synthetic_test"}
        or (require_live and manifest.provenance != "live_capture")
        or not GIT_SHA.fullmatch(manifest.source_commit)
        or any(not SHA256.fullmatch(value) for value in (manifest.prompt_sha, manifest.tools_sha, manifest.graph_sha))
    ):
        raise ValueError("unsupported recording manifest metadata or provenance")
    artifacts = _files(directory, manifest.scenario)
    if {key: sha256(content) for key, content in artifacts.items()} != manifest.artifacts:
        raise ValueError("recording artifacts do not match the pinned manifest")
    secrets = tuple(
        value for key, value in os.environ.items() if key.endswith(("_API_KEY", "_AUTH_TOKEN")) and len(value) >= 8
    )
    _scan(body, "manifest.json", secrets)
    documents = {name: _decode(name, content) for name, content in artifacts.items()}
    for name, document in documents.items():
        _scan(document, name, secrets)
    _validate_documents(documents, manifest)
    return Bundle(manifest, documents)


def seal(directory: Path) -> Bundle:
    """Fill hashes in a staged capture manifest and verify the complete bundle."""
    path = directory / "manifest.json"
    if path.is_symlink():
        raise ValueError("manifest.json: symlink in recording directory")
    original = path.read_bytes()
    metadata = _json(original)
    artifacts = _files(directory, metadata["scenario"])
    metadata.update(
        graph_sha=sha256(canonical_json(_decode("graph.json", artifacts["graph.json"]))),
        artifacts={name: sha256(content) for name, content in artifacts.items()},
    )
    metadata.pop("bundle_sha", None)
    digest = sha256(canonical_json(metadata))
    path.write_bytes(canonical_json(metadata | {"bundle_sha": digest}) + b"\n")
    try:
        return read_bundle(directory, expected_digest=digest, require_live=False)
    except Exception:
        path.write_bytes(original)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seal", action="store_true", help="seal a staged capture")
    group.add_argument("--digest", help="check a live capture against an external pin")
    args = parser.parse_args()
    try:
        bundle = seal(args.capture) if args.seal else read_bundle(args.capture, expected_digest=args.digest)
    except (KeyError, OSError, TypeError, ValueError):
        parser.exit(1, "Recording verification failed. Inspect the staged capture for invalid or forbidden data.\n")
    print(f"{bundle.manifest.scenario}: {bundle.manifest.bundle_sha} ({bundle.manifest.provenance})")


if __name__ == "__main__":
    main()
