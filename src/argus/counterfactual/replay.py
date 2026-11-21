"""Turn off a supported fault in a matched, independently generated MockMart world."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from argus.contracts.findings import Incident, Receipt, Verdict, Window
from argus.counterfactual.models import (
    CounterfactualResult,
    Gap,
    Metric,
    Point,
    QueryProof,
    ReplayPlan,
    ReplayReceipt,
    Scenario,
    WorldConfig,
)
from argus.graph.store import load_seed_graph
from argus.semantic.compile import BASELINE_WEEKS, WEEK, baseline_condition, hourly_sql, quote, window_condition
from argus.semantic.runner import Runner

HOUR = timedelta(hours=1)
DELIVERY_LAG = 2 * HOUR
PAYCO = ("log_provider_status", "ps_payco_degraded")
PACER = ("log_deploys", "dep_ad-pacer_1.7.0")
PACER_BATCH = ("log_ad_budgets", "pacer_change")
PAYCO_SEGMENT = {"country": "DE", "platform": "android", "provider": "PayCo"}
RECORDING_CONFIG = WorldConfig(seed=1)


class ReplayUnavailable(ValueError):
    """The incident or its world does not provide a verifiable intervention."""


def make_plan(incident: Incident, config: WorldConfig, as_of: datetime | None) -> ReplayPlan:
    findings = incident.findings
    root = findings.root
    if findings.verdict is not Verdict.SUPPORTED_CAUSE or root is None or root.evidence is None:
        raise ReplayUnavailable("A supported fault with a named cause is required for replay.")
    evidence = root.evidence
    scenario: Scenario
    metric: Metric
    if (evidence.log, evidence.ref) == PAYCO and root.node == "payment_success_rate" and root.segment == PAYCO_SEGMENT:
        scenario, metric, hours = "s1", "payment_success_rate", 12
    elif root.node in {"pacing_ratio", "ad_spend"} and (
        (evidence.log, evidence.ref) == PACER
        or ((evidence.log, evidence.kind) == PACER_BATCH and evidence.ref.endswith("_1.7"))
    ):
        if root.segment.keys() - {"country", "advertiser_id"}:
            raise ReplayUnavailable("The pacing plan has no data at this segment's grain.")
        scenario, metric, hours = "s4", "pacing_ratio", 24
    else:
        raise ReplayUnavailable("There is no MockMart intervention for this cause.")

    # MockMart's fault changes begin at the hour following the provider notice or deployment.
    hour = evidence.ts.replace(minute=0, second=0, microsecond=0)
    onset = hour + HOUR if evidence.ts > hour else hour
    start = onset - 6 * HOUR
    full_window_as_of = onset + (hours - 1) * HOUR + DELIVERY_LAG
    cutoff = min(as_of, full_window_as_of) if as_of is not None else full_window_as_of
    end = cutoff.replace(minute=0, second=0, microsecond=0) - DELIVERY_LAG
    if end < onset:
        raise ReplayUnavailable("The first hour after the change has yet to arrive.")
    return ReplayPlan(
        scenario=scenario,
        config=config,
        intervention=evidence,
        metric=metric,
        segment=root.segment,
        onset=onset,
        window=Window(start=start, end=end),
        as_of=cutoff,
    )


def generate_world(scenario: str, config: WorldConfig, directory: Path) -> Path:
    """Call the public generator across the simulator boundary and use only its world output."""
    command = [
        sys.executable,
        "-m",
        "mockmart.cli",
        "generate",
        "--scenario",
        scenario,
        "--seed",
        str(config.seed),
        "--days",
        str(config.days),
        "--live-days",
        str(config.live_days),
        "--out",
        str(directory),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ReplayUnavailable("MockMart could not regenerate the replay world.") from exc
    return directory / "world.duckdb"


def _assert_factual_world(runner: Runner, plan: ReplayPlan, reference: Receipt | None) -> None:
    event = plan.intervention
    canonical = PAYCO if plan.scenario == "s1" else PACER
    cited = (event.log, event.ref)
    if cited == canonical:
        entries = [canonical]
    elif plan.scenario == "s4" and (event.log, event.kind) == PACER_BATCH:
        # Stage 2 can cite the grouped budget changes using their first member's ID.
        entries = [canonical, cited]
    else:
        raise ReplayUnavailable("The replay plan does not name a supported event.")
    for log, event_id in entries:
        logs = runner.fetch(f"SELECT ts FROM {log} WHERE id = {quote(event_id)}", plan.as_of)
        if [row["ts"] for row in logs] != [event.ts]:
            raise ReplayUnavailable("The generated world does not reproduce the incident's named event.")
    if reference is not None:
        _, actual = runner.query(reference.sql, reference.as_of)
        if actual.result_hash != reference.result_hash:
            raise ReplayUnavailable("The generated world does not reproduce the incident's factual receipt.")


def _query(
    world: Path, plan: ReplayPlan, sql: str, *, factual: bool, reference: Receipt | None = None
) -> tuple[dict[datetime, dict[str, Any]], QueryProof]:
    runner = Runner(world)
    try:
        if factual:
            _assert_factual_world(runner, plan, reference)
        rows, receipt = runner.query(sql, plan.as_of)
        return {row["ts"]: row for row in rows}, QueryProof(
            sql=receipt.sql, result_hash=receipt.result_hash, rows=receipt.rows
        )
    finally:
        runner.close()


def _points(
    plan: ReplayPlan, factual: dict[datetime, dict[str, Any]], counterfactual: dict[datetime, dict[str, Any]]
) -> tuple[list[Point], list[Point]]:
    factual_points, replay_points = [], []
    point_count = (plan.window.end - plan.window.start) // HOUR + 1
    for offset in range(point_count):
        hour = plan.window.start + offset * HOUR
        observed, replay = factual.get(hour), counterfactual.get(hour)
        if not observed or not observed["den"] or not replay or not replay["den"]:
            raise ReplayUnavailable("One of the replay worlds is missing an hourly metric value.")
        expected = 1.0
        if plan.metric == "payment_success_rate":
            history = [factual.get(hour - week * WEEK) for week in range(1, BASELINE_WEEKS + 1)]
            past = [row for row in history if row is not None and row["den"]]
            if len(past) != BASELINE_WEEKS:
                raise ReplayUnavailable("Four matching weeks of payment history are required for replay.")
            expected = sum(row["num"] for row in past) / sum(row["den"] for row in past)
        expected = round(expected, 10)
        factual_points.append(Point(hour=hour, value=round(observed["num"] / observed["den"], 10), expected=expected))
        replay_points.append(Point(hour=hour, value=round(replay["num"] / replay["den"], 10), expected=expected))
    return factual_points, replay_points


def run_plan(plan: ReplayPlan, reference: Receipt | None = None) -> CounterfactualResult:
    graph = load_seed_graph()
    condition = window_condition(plan.window)
    replay_sql = hourly_sql(graph, plan.metric, condition, plan.segment)
    factual_sql = replay_sql
    if plan.metric == "payment_success_rate":
        factual_sql = hourly_sql(graph, plan.metric, f"{condition} OR {baseline_condition(plan.window)}", plan.segment)
    with TemporaryDirectory(prefix="argus-counterfactual-") as directory:
        root = Path(directory)
        factual_world = generate_world(plan.scenario, plan.config, root / "factual")
        factual_rows, factual_proof = _query(factual_world, plan, factual_sql, factual=True, reference=reference)
        # S1 and S4 each have one metric-changing intervention. Quiet leaves the base parameters and
        # the seeded background in place, with neither that intervention nor its scenario-specific log entries.
        quiet_world = generate_world("quiet", plan.config, root / "cause-off")
        replay_rows, replay_proof = _query(quiet_world, plan, replay_sql, factual=False)
    factual, replay = _points(plan, factual_rows, replay_rows)
    factual_gap = sum(abs(p.value - p.expected) for p in factual if p.hour >= plan.onset)
    replay_gap = sum(abs(p.value - p.expected) for p in replay if p.hour >= plan.onset)
    if factual_gap <= 1e-12:
        raise ReplayUnavailable("The factual metric has no measurable gap from its expectation.")
    removed = factual_gap - replay_gap
    return CounterfactualResult(
        factual_series=factual,
        counterfactual_series=replay,
        explained_share=max(0.0, removed / factual_gap),
        gap=Gap(factual=factual_gap, counterfactual=replay_gap, removed=removed),
        receipt=ReplayReceipt(plan=plan, factual=factual_proof, counterfactual=replay_proof),
    )


def counterfactual(
    incident: Incident,
    *,
    config: WorldConfig = RECORDING_CONFIG,
    as_of: datetime | None = None,
    reference: Receipt | None = None,
) -> CounterfactualResult:
    """Replay the cause named in an incident. The shipped recordings use seed 1."""
    return run_plan(make_plan(incident, config, as_of), reference=reference)
