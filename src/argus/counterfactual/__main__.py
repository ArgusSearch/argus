"""Generate a fresh incident or independently verify a saved replay receipt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from argus.contracts.findings import Verdict
from argus.counterfactual.models import CounterfactualResult, ReplayReceipt, WorldConfig
from argus.counterfactual.replay import ReplayUnavailable, counterfactual, generate_world, run_plan


def add_arguments(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--scenario", choices=("s1", "s4"), help="generate a world and run Argus first")
    source.add_argument("--receipt", help="verify a saved receipt or full JSON response; use - for stdin")
    parser.add_argument("--seed", default=7, type=int, help="seed for a fresh scenario (default: 7)")


def _fresh_replay(scenario: str, seed: int) -> CounterfactualResult:
    from argus.runtime.loop import Runtime

    config = WorldConfig(seed=seed)
    with TemporaryDirectory(prefix="argus-counterfactual-incident-") as directory:
        world = generate_world(scenario, config, Path(directory))
        runtime = Runtime(world)
        try:
            runtime.run()
            incident = next(
                (item for item in runtime.book.incidents.values() if item.verdict is Verdict.SUPPORTED_CAUSE), None
            )
            if incident is None:
                raise ReplayUnavailable("Argus did not find a supported fault in this run.")
            root = incident.findings.root
            reference = runtime.runner.receipts.get(root.change_pct.receipt or "") if root else None
            if reference is None:
                raise ReplayUnavailable("Argus did not record a factual root receipt for this incident.")
        finally:
            runtime.runner.close()
    return counterfactual(incident, config=config, reference=reference)


def run(args: argparse.Namespace) -> int:
    try:
        if args.receipt:
            raw = sys.stdin.read() if args.receipt == "-" else Path(args.receipt).read_text()
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ReplayUnavailable("The JSON input must be a replay response or receipt object.")
            receipt = ReplayReceipt.model_validate(payload.get("receipt", payload))
            result = run_plan(receipt.plan)
            if result.receipt != receipt:
                raise ReplayUnavailable("The replay does not match the saved receipt.")
        else:
            result = _fresh_replay(args.scenario, args.seed)
    except (OSError, ValueError) as exc:
        print(f"counterfactual: {exc}", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="argus counterfactual")
    add_arguments(parser)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
