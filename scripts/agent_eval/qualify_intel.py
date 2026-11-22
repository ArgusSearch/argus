"""Score the six retained v2 live trials against the stage qualification thresholds."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.agent_eval.bundle import Bundle, read_bundle
from scripts.agent_eval.qualify import TRIALS, Trial, assess_trial

from argus.agent.types import ActivityRecord
from argus.contracts.findings import Findings, Incident

STAGE = ("s1", "s4")
CAUSAL_CHECKS = {"holdout_check", "placebo_test", "counterfactual_impact", "sql_check"}
BASELINES = Path(__file__).resolve().parents[2] / "fixtures" / "agent" / "v1"


def _admitted(bundle: Bundle) -> tuple[str, str | None]:
    (raw,) = bundle.documents["incidents.json"]
    findings: Findings = Incident.model_validate(raw).findings
    evidence = findings.root.evidence if findings.root else None
    return findings.verdict, evidence.ref if evidence else None


def _checks(bundle: Bundle) -> tuple[list[str], int, int, bool]:
    """Read host-accepted declarations/outcomes, accounting for the first attempted tool for each card."""
    issues: list[str] = []
    records = [ActivityRecord.model_validate(row) for row in bundle.documents["activity.jsonl"]]
    decisive_tools: dict[str, str] = {}
    for record in records:
        if record.kind == "hypothesis":
            for card in (record.args or {}).get("declared", []):
                decisive_tools[card["id"]] = card["decisive_check"]
    if not 2 <= len(decisive_tools) <= 5:
        issues.append("expected two to five declared competing hypotheses")
    calls = [
        (block["name"], block["input"])
        for turn in bundle.documents["turns.jsonl"]
        if turn["key"].startswith("investigate:")
        for block in turn["response"]["content"]
        if block["type"] == "tool_use"
    ]
    declaration = next((i for i, (tool, _) in enumerate(calls) if tool == "propose_hypotheses"), None)
    causal = next((i for i, (tool, _) in enumerate(calls) if tool in CAUSAL_CHECKS), None)
    if causal is None:
        issues.append("no detective causal check")
    elif declaration is None or declaration >= causal:
        issues.append("causal check before declaration")
    first_checks: dict[str, str] = {}
    for tool, args in calls:
        if hypothesis := args.get("hypothesis_id"):
            first_checks.setdefault(hypothesis, tool)
    if not first_checks:
        issues.append("no first hypothesis check")
    accepted_sql = any(
        record.kind == "tool_result"
        and (observation := record.observation) is not None
        and observation.availability == "ok"
        and observation.tool == "sql_check"
        and bool(observation.receipt_refs)
        for record in records
    )
    (raw,) = bundle.documents["incidents.json"]
    skeptic = Incident.model_validate(raw).findings.skeptic
    if skeptic is None or skeptic.verdict != "upheld" or not skeptic.checks:
        issues.append("the supported cause lacks a completed upheld critic pass")
    decisive = sum(decisive_tools.get(key) == tool for key, tool in first_checks.items())
    return issues, decisive, len(first_checks), accepted_sql


def score_intelligence(directory: Path, source_commit: str) -> dict[str, object]:
    pins = json.loads((BASELINES / "accepted.json").read_bytes())
    expected = {s: _admitted(read_bundle(BASELINES / s, expected_digest=pins[s])) for s in STAGE}
    trials: list[dict[str, Any]] = []
    passes: Counter[str] = Counter()
    seen_requests: set[str] = set()
    costs: list[float] = []
    times: list[float] = []
    s1_sql = decisive = first_checks = 0
    for scenario in STAGE:
        for index in range(1, TRIALS + 1):
            slot = directory / f"{scenario}-1-{index}"
            result: dict[str, Any] = {"scenario": scenario, "seed": 1, "trial": index}
            trials.append(result)
            try:
                trial = Trial.model_validate_json((slot / "trial.json").read_bytes())
                if (trial.scenario, trial.seed, trial.trial) != (scenario, 1, index):
                    raise ValueError("trial identity mismatch")
                failures, _ = assess_trial(trial, slot, source_commit, profile="v2")
                ids = [item.request_id for item in trial.usage if item.request_id is not None]
                if len(set(ids)) != len(ids) or set(ids) & seen_requests:
                    failures.append("provider exchange reused across trials")
                seen_requests.update(ids)
                run_ids = {run.run_id for run in trial.runs if run.kind == "investigate"}
                spend = sum(item.usd or 0 for item in trial.usage if item.run_id in run_ids)
                costs.append(spend)
                times.append(trial.elapsed_seconds)
                result.update(usd=spend, seconds=trial.elapsed_seconds, capture=trial.bundle_sha, failures=failures)
                if failures:
                    continue
                bundle = read_bundle(slot / "bundle", expected_digest=trial.bundle_sha or "")
                if _admitted(bundle) != expected[scenario]:
                    failures.append("admitted cause or verdict differs from the pinned v1 presentation")
                issues, n_decisive, n_first, accepted_sql = _checks(bundle)
                failures.extend(issues)
                decisive += n_decisive
                first_checks += n_first
                if not failures:
                    passes[scenario] += 1
                    s1_sql += scenario == "s1" and accepted_sql
            except (KeyError, OSError, TypeError, ValueError):
                result["failures"] = ["missing or invalid retained trial"]
    rate = decisive / first_checks if first_checks else 0.0
    pass_power_3 = {scenario: passes[scenario] == TRIALS for scenario in STAGE}
    median_cost = statistics.median(costs) if costs else None
    max_cost = max(costs, default=None)
    median_seconds = statistics.median(times) if times else None
    caps = (
        len(costs) == len(STAGE) * TRIALS
        and median_cost is not None
        and median_cost <= 0.40
        and max_cost is not None
        and max_cost <= 0.70
        and median_seconds is not None
        and median_seconds <= 90
    )
    return {
        "commit": source_commit,
        "profile": "v2",
        "live_eligible": all(pass_power_3.values()) and caps and s1_sql >= 2 and rate >= 0.8,
        "pass_power_3": pass_power_3,
        "cost_and_latency_passed": caps,
        "s1_accepted_sql_trials": s1_sql,
        "decisive_first_rate": rate,
        "decisive_first_checks": decisive,
        "first_checks": first_checks,
        "median_usd": median_cost,
        "maximum_usd": max_cost,
        "median_seconds": median_seconds,
        "trials": trials,
    }
