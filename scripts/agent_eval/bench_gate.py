"""Fail the release gate if Argus regresses on any of the 18 sealed Stage 2 cases."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from bench.scorecard import Scorecard, scenario_rows, summarise
from bench.sealed import bench_commitment, verify

SCENARIOS = ("quiet", "s1", "s2", "s3", "s4", "s5")
SEEDS = (1, 2, 3)
CASES = {(scenario, seed) for scenario in SCENARIOS for seed in SEEDS}


def validate_scorecard(card: Scorecard) -> None:
    """Check the run outcomes before comparing the printed rollups."""
    if sorted(card.scenarios) != sorted(SCENARIOS) or sorted(card.seeds) != list(SEEDS):
        raise ValueError("bench must cover all six scenarios on seeds 1, 2, and 3")
    if card.agents.count("argus") != 1 or "argus" in card.unavailable:
        raise ValueError("Stage 2 Argus was unavailable or absent")
    runs = [run for run in card.runs if run.agent == "argus"]
    if len(runs) != len(CASES) or {(run.scenario, run.seed) for run in runs} != CASES:
        raise ValueError("expected one Argus run per scenario and seed")
    for run in runs:
        if run.case != f"{run.scenario}-{run.seed}" or not run.passed:
            raise ValueError(f"{run.case}: failed grade, commitment, agent execution or false alarm")
        if run.scenario == "quiet" and (run.pages or run.claims or run.events):
            raise ValueError(f"{run.case}: quiet world was not silent")
        if run.scenario != "quiet" and not run.events:
            raise ValueError(f"{run.case}: missing grades for injected events")

    commitments = {run.case: run.commitment for run in runs}
    if bench_commitment(commitments) != card.bench_commitment:
        raise ValueError("bench commitment does not match the Argus case commitments")
    rows = sorted((row for row in card.rows if row.agent == "argus"), key=lambda row: row.scenario)
    if rows != sorted(scenario_rows("argus", runs, len(SEEDS)), key=lambda row: row.scenario):
        raise ValueError("Argus scenario rows do not match the sealed grades")
    if [summary for summary in card.summaries if summary.agent == "argus"] != [summarise("argus", runs)]:
        raise ValueError("Argus summary does not match the sealed grades")


def validate_seals(directory: Path, card: Scorecard) -> None:
    precommit = json.loads((directory / "commitment.json").read_text())
    commitments = {run.case: run.commitment for run in card.runs if run.agent == "argus"}
    if precommit["cases"] != commitments or precommit["bench_commitment"] != card.bench_commitment:
        raise ValueError("pre-run commitment does not match the scorecard")
    for case, expected in commitments.items():
        sealed = json.loads((directory / case / "commitment.json").read_text())
        revealed = json.loads((directory / case / "reveal.json").read_text())
        if (
            sealed["case"] != case
            or sealed["commitment"] != expected
            or revealed["commitment"] != expected
            or not verify(expected, revealed["nonce"], revealed["payload"])
        ):
            raise ValueError(f"{case}: sealed truth does not match its reveal")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="the output directory of argus-bench")
    args = parser.parse_args()
    try:
        card = Scorecard.model_validate_json((args.directory / "scorecard.json").read_bytes())
        head = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        if card.git_commit != head:
            raise ValueError(f"expected a clean scorecard from {head}, got {card.git_commit}")
        validate_scorecard(card)
        validate_seals(args.directory, card)
    except (KeyError, OSError, ValueError) as exc:
        parser.exit(1, f"Bench gate failed: {exc}\n")
    print(f"Stage 2 bench {head}: 18/18, zero false alarms, 18 verified commitments")


if __name__ == "__main__":
    main()
