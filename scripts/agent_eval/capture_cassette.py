"""Verify A's live investigation export and seal it with reproducible graph and receipt proofs."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from scripts.agent_eval.bundle import Bundle, canonical_json, read_bundle, receipt_keys, seal, sha256
from scripts.agent_eval.replay_config import V1_REPLAY, ReplayConfig, add_profile_options, profile_options

from argus.agent.investigate import tool_specs
from argus.agent.journal import Journal
from argus.agent.prompts import SELECT
from argus.agent.provider import Cassette, ReplayClient
from argus.agent.types import INTERFACE_VERSION, LlmRequest, LlmResponse, RunSummary
from argus.runtime.loop import Runtime
from mockmart.sim import WorldConfig
from mockmart.world import generate


class CaptureMismatch(ValueError):
    """A replay comparison failed without exposing provider content."""


def _read_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()]


def _compare(name: str, actual: list[dict[str, Any]], recorded: list[dict[str, Any]]) -> None:
    for index, (received, expected) in enumerate(zip(actual, recorded, strict=False), 1):
        if received != expected:
            raise CaptureMismatch(f"{name} differs from the live export at record {index}")
    if len(actual) != len(recorded):
        raise CaptureMismatch(f"{name} has {len(actual)} records, expected {len(recorded)}")


class _OrderedReplay(ReplayClient):
    def __init__(self, cassette: Cassette) -> None:
        super().__init__(cassette)
        self.expected = [line["key"] for line in cassette.lines]
        self.position = 0
        self.investigation_pins: tuple[str, str] | None = None

    def create(self, request: LlmRequest) -> LlmResponse:
        if self.position >= len(self.expected) or request.key != self.expected[self.position]:
            raise ValueError(f"unexpected cassette request at turn {self.position + 1}")
        response = super().create(request)
        self.position += 1
        if request.key.startswith("investigate:"):
            pins = sha256(request.system.encode()), sha256(canonical_json(request.tools))
            if self.investigation_pins is not None and self.investigation_pins != pins:
                raise CaptureMismatch("detective prompt or tools changed within the capture")
            self.investigation_pins = pins
        return response

    def pins(self, config: ReplayConfig) -> tuple[str, str]:
        if config.profile == "v1":
            return sha256(SELECT.encode()), sha256(canonical_json(tool_specs()))
        if self.investigation_pins is None:
            raise CaptureMismatch("capture has no investigative prompt and tool pins")
        return self.investigation_pins


@contextmanager
def _replay_cassette(
    source: Path, world: Path, config: ReplayConfig, state: Path
) -> Iterator[tuple[Runtime, _OrderedReplay]]:
    replayer = _OrderedReplay(Cassette.load(source / "turns.jsonl"))
    journal = Journal()
    runtime: Runtime
    selector = config.selector(replayer, journal, lambda: runtime.bus.history[-1].seq, state)
    runtime = Runtime(world, selector=selector)
    try:
        runtime.run()
        if (
            runtime.fallbacks
            or replayer.position != len(replayer.expected)
            or any(run.status != "done" for run in journal.runs.values())
        ):
            raise CaptureMismatch(f"model exchange did not replay through turn {replayer.position + 1}")
        for name, actual in (
            ("activity.jsonl", [record.model_dump(mode="json") for record in journal.records]),
            ("events.jsonl", [event.model_dump(mode="json") for event in runtime.bus.history]),
        ):
            _compare(name, actual, _read_lines(source / name))
        yield runtime, replayer
    finally:
        runtime.runner.close()


def verify_cassette(directory: Path, digest: str, world: Path) -> Bundle:
    bundle = read_bundle(directory, expected_digest=digest, presentation=False)
    config = ReplayConfig.from_manifest(bundle.manifest, directory)
    with (
        tempfile.TemporaryDirectory(prefix="argus-cassette-replay-") as state,
        _replay_cassette(directory, world, config, Path(state)) as (runtime, replayer),
    ):
        if replayer.pins(config) != (bundle.manifest.prompt_sha, bundle.manifest.tools_sha):
            raise CaptureMismatch("detective prompt or tools do not match the seal")
        if sha256(canonical_json(runtime.graph.model_dump(mode="json"))) != bundle.manifest.graph_sha:
            raise CaptureMismatch("graph differs from the seal")
        for receipt_id, result_hash in {
            value["receipt"]["id"]: value["receipt"]["result_hash"]
            for value in bundle.documents["receipts.json"].values()
        }.items():
            if runtime.runner.rerun(receipt_id) != (result_hash, True):
                raise CaptureMismatch(f"receipt {receipt_id} differs from the seal")
    return bundle


def stage_recording(
    source: Path,
    output: Path,
    scenario: str,
    seed: int,
    source_commit: str,
    *,
    config: ReplayConfig = V1_REPLAY,
) -> Bundle:
    summaries = [RunSummary.model_validate(row) for row in json.loads((source / "runs.json").read_bytes())]
    if not summaries or any(
        run.mode != "record" or run.status != "done" or run.fallback or run.llm_calls < 2 for run in summaries
    ):
        raise CaptureMismatch("the live export has an incomplete or fallback investigation")

    recorded_incidents = json.loads((source / "incidents.json").read_bytes())
    with tempfile.TemporaryDirectory(prefix="argus-cassette-world-") as work:
        world = generate(scenario, WorldConfig(seed=seed), Path(work))
        with _replay_cassette(source, world.world, config, Path(work) / "memory") as (runtime, replayer):
            graph = runtime.graph.model_dump(mode="json")
            keys = set(
                receipt_keys(
                    [
                        _read_lines(source / "activity.jsonl"),
                        _read_lines(source / "events.jsonl"),
                        recorded_incidents,
                        graph,
                    ]
                )
            )
            proofs_by_id: dict[str, Any] = {}
            receipts = {}
            for key in sorted(keys):
                receipt_id = key.rsplit("/", 1)[-1]
                if receipt_id not in proofs_by_id:
                    receipt = runtime.runner.receipts[receipt_id]
                    if not runtime.runner.rerun(receipt_id)[1]:
                        raise CaptureMismatch("a receipt did not rerun at its recorded clock")
                    rows = runtime.runner.fetch(receipt.sql, receipt.as_of)[:12]
                    columns = list(rows[0]) if rows else []
                    # Timestamps are canonical UTF-8 values in the stored row sample.
                    serializable = json.loads(json.dumps([list(row.values()) for row in rows], default=str))
                    proofs_by_id[receipt_id] = {
                        "receipt": receipt.model_dump(mode="json"),
                        "columns": columns,
                        "rows": serializable,
                        "verified_at_capture": True,
                    }
                receipts[key] = proofs_by_id[receipt_id]
            world_manifest = json.loads(world.manifest.read_bytes())
            world_manifest.pop("seconds", None)

    output.mkdir(parents=True, exist_ok=False)
    prompt_sha, tools_sha = replayer.pins(config)
    documents = {
        "manifest.json": {
            "schema_version": 1,
            "provenance": "live_capture",
            "source_commit": source_commit,
            "scenario": scenario,
            "seed": seed,
            "interface_version": INTERFACE_VERSION,
            "prompt_sha": prompt_sha,
            "tools_sha": tools_sha,
            "models": sorted({turn["response"]["model"] for turn in _read_lines(source / "turns.jsonl")}),
            "world": world_manifest,
            **config.metadata(output),
        },
        "graph.json": graph,
        "receipts.json": receipts,
    }
    for name, document in documents.items():
        (output / name).write_bytes(canonical_json(document) + b"\n")
    for name in ("turns.jsonl", "activity.jsonl", "events.jsonl", "incidents.json"):
        (output / name).write_bytes((source / name).read_bytes())
    return seal(output, presentation=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--scenario", choices=("s1", "s4"), required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--source-commit", required=True)
    add_profile_options(parser)
    args = parser.parse_args()
    try:
        bundle = stage_recording(
            args.source, args.output, args.scenario, args.seed, args.source_commit, config=profile_options(args)
        )
    except CaptureMismatch as exc:
        parser.exit(1, f"Cassette staging failed: {exc}\n")
    except (KeyError, OSError, TypeError, ValueError):
        parser.exit(1, "Cassette staging failed while validating the export or its receipt proofs.\n")
    print(f"{bundle.manifest.scenario}: sealed investigation cassette {bundle.manifest.bundle_sha}")


if __name__ == "__main__":
    main()
