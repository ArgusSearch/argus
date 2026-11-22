"""Score independent paid trials. Run only after the trials have been captured."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from scripts.agent_eval.bundle import Bundle, read_bundle

from argus.agent.provider import TARIFF, price
from argus.agent.types import ActivityRecord, LlmResponse, Observation, RunSummary, UsageRecord
from bench.grade import RunGrade
from bench.sealed import verify

CASES = tuple((scenario, seed) for scenario in ("s1", "s4") for seed in (1, 3, 7))
TRIALS = 3


class Trial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Literal["s1", "s4"]
    seed: int
    trial: int
    source_commit: str
    elapsed_seconds: float = Field(ge=0, allow_inf_nan=False)
    bundle_sha: str | None = None
    grade: RunGrade | None = None
    runs: list[RunSummary] = Field(default_factory=list)
    usage: list[UsageRecord] = Field(default_factory=list)
    failure: str | None = None


class TextReview(BaseModel):
    """The judge only sees redacted text; its scores never count as behavioral passes."""

    model_config = ConfigDict(extra="forbid")

    sample: str
    what_happened: int = Field(ge=1, le=5)
    why: int = Field(ge=1, le=5)
    alternative: int = Field(ge=1, le=5)
    next_action: int = Field(ge=1, le=5)


class Counterexample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_commit: str
    original_observation: Observation
    changed_observation: Observation
    original_response: LlmResponse
    changed_response: LlmResponse

    def passed(self, source_commit: str) -> bool:
        first = self.original_observation
        second = self.changed_observation
        original = self.original_response
        changed = self.changed_response

        def choices(response: LlmResponse) -> list[tuple[str, object]]:
            return [(part["name"], part["input"]) for part in response.content if part["type"] == "tool_use"]

        return bool(
            self.source_commit == source_commit
            and first.receipt_refs
            and first.tool == second.tool
            and first.args == second.args
            and first.outcome != second.outcome
            and original.request_id
            and changed.request_id
            and original.request_id != changed.request_id
            and original.model == changed.model
            and choices(original)
            and (choices(changed) or changed.stop_reason == "end_turn")
            and choices(original) != choices(changed)
        )


def check_usage(trial: Trial) -> list[str]:
    issues: list[str] = []
    usage_keys = {(entry.run_id, entry.call_index) for entry in trial.usage}
    if len(usage_keys) != len(trial.usage):
        issues.append("duplicated provider call")
    if any(item.usd is None or not math.isfinite(item.usd) or item.usd < 0 for item in trial.usage):
        issues.append("missing or invalid priced usage")
    for item in trial.usage:
        expected = price(
            item.model,
            {
                "input_tokens": item.input_tokens,
                "output_tokens": item.output_tokens,
                "cache_read_input_tokens": item.cache_read_tokens,
                "cache_creation_input_tokens": item.cache_write_tokens,
            },
        )
        if item.tariff != TARIFF or expected is None or item.usd != expected:
            issues.append("provider usage does not match the pinned tariff")
            break
    if not trial.usage or any(not item.request_id for item in trial.usage):
        issues.append("missing independent provider request identifiers")
    keys = {run.run_id for run in trial.runs}
    if any(entry.run_id not in keys for entry in trial.usage) or len(keys) != len(trial.runs):
        issues.append("usage has an unknown or duplicated run")
    for run in trial.runs:
        entries = [entry for entry in trial.usage if entry.run_id == run.run_id]
        if len(entries) != run.llm_calls or round(sum(entry.usd or 0 for entry in entries), 6) != run.usd:
            issues.append(f"usage differs from run {run.run_id}")
    return issues


def check_adaptive(bundle: Bundle, investigation_ids: set[str]) -> bool:
    """Find two provider-selected tools with a real, receipted observation between them."""
    records = [ActivityRecord.model_validate(item) for item in bundle.documents["activity.jsonl"]]
    for run_id in investigation_ids:
        history = [record for record in records if record.run_id == run_id]
        anomaly_id = next((record.anomaly_id for record in history if record.anomaly_id), None)
        if not anomaly_id:
            continue
        rounds = [
            [
                block["name"]
                for block in turn["response"]["content"]
                if block["type"] == "tool_use" and block["name"] != "submit_findings"
            ]
            for turn in bundle.documents["turns.jsonl"]
            if turn["key"].startswith(f"investigate:{anomaly_id}:")
        ]
        results = [
            record.observation for record in history if record.kind == "tool_result" and record.observation is not None
        ]
        if [name for names in rounds for name in names] != [item.tool for item in results]:
            continue
        received_evidence = False
        index = 0
        for names in rounds:
            evidence = [
                item for item in results[index : index + len(names)] if item.receipt_refs and item.availability == "ok"
            ]
            if received_evidence and any(
                item.tool in {"holdout_check", "placebo_test", "market_control", "decompose_formula", "mix_rate_split"}
                for item in evidence
            ):
                return True
            received_evidence |= bool(evidence)
            index += len(names)
    return False


def assess_trial(trial: Trial, directory: Path, source_commit: str) -> tuple[list[str], float]:
    failures = check_usage(trial)
    if trial.source_commit != source_commit:
        failures.append("trial came from a different source commit")
    if trial.failure:
        failures.append("trial reported an execution failure")
    grade = trial.grade
    if grade is None or (
        grade.agent != "argus-stage3"
        or grade.scenario != trial.scenario
        or grade.seed != trial.seed
        or not grade.events
        or not grade.passed
    ):
        failures.append("sealed Stage 3 grade did not pass")
    elif not _verified_grade(directory, grade):
        failures.append("grade does not match the pre-run truth commitment")
    investigations = [run for run in trial.runs if run.kind == "investigate"]
    if not investigations or any(
        run.mode not in {"live", "record"} or run.status != "done" or run.fallback or run.llm_calls < 2
        for run in investigations
    ):
        failures.append("a live investigation fell back or did not complete")
    try:
        bundle = read_bundle(directory / "bundle", expected_digest=trial.bundle_sha or "")
        if (bundle.manifest.scenario, bundle.manifest.seed, bundle.manifest.source_commit) != (
            trial.scenario,
            trial.seed,
            trial.source_commit,
        ):
            failures.append("capture metadata differs from trial")
        if not check_adaptive(bundle, {run.run_id for run in investigations}):
            failures.append("no model tool choice after a receipted observation")
        if trial.scenario == "s1" and any(
            item["kind"] == "action_applied" for item in bundle.documents["activity.jsonl"]
        ):
            failures.append("S1 executed a business action")
    except (KeyError, OSError, TypeError, ValueError):
        failures.append("missing or unverified recording, approval or effect")
    return failures, sum(entry.usd or 0 for entry in trial.usage)


def _verified_grade(directory: Path, grade: RunGrade) -> bool:
    try:
        before = json.loads((directory / "commitment.json").read_bytes())
        after = json.loads((directory / "reveal.json").read_bytes())
        return (
            before["case"] == grade.case == directory.name
            and before["commitment"] == after["commitment"] == grade.commitment
            and verify(grade.commitment, after["nonce"], after["payload"])
        )
    except (KeyError, OSError, ValueError, TypeError):
        return False


def score(directory: Path, source_commit: str) -> dict[str, object]:
    results = []
    costs: list[float] = []
    seconds: list[float] = []
    passed: Counter[tuple[str, int]] = Counter()
    request_ids: set[str] = set()
    all_usage_verified = True
    for scenario, seed in CASES:
        for index in range(1, TRIALS + 1):
            path = directory / f"{scenario}-{seed}-{index}"
            try:
                trial = Trial.model_validate_json((path / "trial.json").read_bytes())
                if (trial.scenario, trial.seed, trial.trial) != (scenario, seed, index):
                    raise ValueError("trial identity mismatch")
                failures, usd = assess_trial(trial, path, source_commit)
                all_usage_verified &= not check_usage(trial)
                ids = [entry.request_id for entry in trial.usage if entry.request_id]
                if set(ids) & request_ids or len(set(ids)) != len(ids):
                    failures.append("provider exchange reused across trials")
                request_ids.update(ids)
            except (OSError, ValueError):
                results.append(
                    {"scenario": scenario, "seed": seed, "trial": index, "failures": ["missing or invalid trial"]}
                )
                continue
            if not failures:
                passed[(scenario, seed)] += 1
            costs.append(usd)
            seconds.append(trial.elapsed_seconds)
            results.append(
                {
                    "scenario": scenario,
                    "seed": seed,
                    "trial": index,
                    "artifact": str(path),
                    "capture": trial.bundle_sha,
                    "usd": usd,
                    "seconds": trial.elapsed_seconds,
                    "failures": failures,
                }
            )

    reliability = sum(passed[case] == TRIALS for case in CASES) >= 5 and passed[("s4", 1)] == TRIALS
    costs_ok = (
        len(costs) == len(CASES) * TRIALS
        and all_usage_verified
        and statistics.median(costs) <= 0.25
        and max(costs) <= 0.50
        and statistics.median(seconds) <= 60
    )
    try:
        proof = Counterexample.model_validate_json((directory / "counterexample.json").read_bytes())
        paired_observations = proof.passed(source_commit)
    except (OSError, ValueError, KeyError):
        paired_observations = False
    return {
        "commit": source_commit,
        "live_eligible": reliability and costs_ok and paired_observations,
        "reliability_passed": reliability,
        "cost_and_latency_passed": costs_ok,
        "changed_observation_passed": paired_observations,
        "pass_power_3": {f"{scenario}-{seed}": passed[(scenario, seed)] == TRIALS for scenario, seed in CASES},
        "trials": results,
    }


def show_quality(path: Path) -> dict[str, object]:
    reviews = [TextReview.model_validate(item) for item in json.loads(path.read_bytes())]
    criteria = [grade for review in reviews for grade in review.model_dump(exclude={"sample"}).values()]
    return {
        "reviewed": len(reviews),
        "mean": statistics.mean(criteria) if criteria else None,
        "rubric_passed": bool(criteria and statistics.mean(criteria) >= 4 and min(criteria) >= 3),
        "below_three": [review.sample for review in reviews if min(review.model_dump(exclude={"sample"}).values()) < 3],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trials", type=Path, help="the retained trial directories, including failures")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--text-review", type=Path, help="optional text-quality judge results")
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    report = score(args.trials, head)
    if args.text_review:
        report["text_quality"] = show_quality(args.text_review)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    if not report["live_eligible"]:
        parser.exit(1, f"Live qualification failed; results: {args.out}\n")
    print(f"Live qualification passed; results: {args.out}")


if __name__ == "__main__":
    main()
