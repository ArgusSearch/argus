"""Bind numeric fields to their actual subjects, scopes, intervals and units."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from argus.agent.types import ClaimKind
from argus.contracts.findings import Segment, Window
from argus.contracts.graph import Graph
from argus.contracts.tools import HoldoutCheckInput
from argus.counterfactual.models import CounterfactualResult
from argus.investigate.tools import IMPACT_NODE
from argus.market.control import MarketAssessment


@dataclass(frozen=True)
class Fact:
    kind: ClaimKind
    subject: str
    segment: Segment
    window: Window
    label: str
    value: float
    unit: str

    def coordinate(self) -> str:
        label = " ".join(self.label.split())
        segment = ", ".join(f"{dim}={value}" for dim, value in sorted(self.segment.items())) or "all segments"
        start, end = self.window.start, self.window.end
        interval = f"{start:%Y-%m-%d %H:%M}"
        if start != end:
            interval += f" to {end:%Y-%m-%d %H:%M}"
        return f"{label} ({segment}, {interval} UTC)"

    def render(self) -> str:
        if self.unit == "share":
            value = f"{self.value:.2%}"
        elif self.unit == "pct":
            value = f"{self.value:+.2f}%"
        elif self.unit == "count":
            value = f"{self.value:,.6g}"
        else:
            unit = self.unit.replace("eur", "EUR")
            value = f"{self.value:,.6g} {unit}"
        return f"{self.coordinate()} = {value}"


def has_comparison(rows: list[dict[str, Any]], *, needs_relative: bool = False) -> bool:
    """Stage 2's missing-data zeroes cannot be used as measured values."""
    return any(
        (
            row.get("cur_den", 0)
            and row.get("base_den", 0)
            and row.get("cur_num") is not None
            and row.get("base_num") is not None
            and (not needs_relative or row["base_num"] != 0)
        )
        if "cur_den" in row
        else (
            row.get("cur_value") is not None
            and row.get("base_value") is not None
            and (not needs_relative or row["base_value"] != 0)
        )
        for row in rows
    )


def tool_facts(
    name: str, data: dict[str, Any], args: BaseModel, graph: Graph, reads: dict[str, list[dict[str, Any]]]
) -> list[Fact]:
    """Select only defined fields of the trusted tool result and assign their display semantics."""
    request = args.model_dump()
    node = request.get("node", "")
    segment = request.get("segment", {})
    window = Window.model_validate(request["window"]) if "window" in request else None
    facts: list[Fact] = []

    def add(
        kind: ClaimKind,
        label: str,
        value: float | None,
        unit: str,
        *,
        subject: str = node,
        scope: Segment = segment,
        when: Window | None = window,
    ) -> None:
        if value is not None and when is not None:
            facts.append(Fact(kind, subject, scope, when, label, value, unit))

    match name:
        case "get_series":
            for point in data["points"]:
                when = Window(start=point["hour"], end=point["hour"])
                unit: str = graph.node(node).unit
                observed, expected = point["value"], point["expected"]
                add("observed", f"Observed {node}", observed, unit, when=when)
                add("observed", f"Expected {node} (weekly baseline)", expected, unit, when=when)
                if observed is not None and expected:
                    add(
                        "change",
                        f"{node} change versus weekly baseline",
                        100 * (observed / expected - 1),
                        "pct",
                        when=when,
                    )
        case "check_freshness":
            for entry in data["tables"]:
                table = entry["table"]
                add("share", f"{table} minimum hourly delivery", entry["completeness"], "share", subject=table)
        case "check_identities":
            for check in data["identities"]:
                add(
                    "share",
                    f"{check['expr']} relative residual",
                    check["max_rel_residual"],
                    "share",
                    subject=check["edge"],
                )
        case "decompose_formula":
            parent = graph.node(node)
            unit = f"{parent.unit}/hour" if parent.kind == "additive" else parent.unit
            for contribution in data["contributions"]:
                factor = contribution["node"]
                add("share", f"{factor} share of {node} change", contribution["share"], "share", subject=factor)
                add("impact", f"{factor} contribution to {node}", contribution["value"], unit, subject=factor)
            add("impact", f"{node} decomposition residual", data["residual"], unit)
        case "mix_rate_split":
            for field in ("change", "mix", "rate"):
                add("change", f"{node} {field} by {request['dim']}", data[field], graph.node(node).unit)
        case "segment_search":
            for cell in data["path"]:
                add("share", f"{node} share of deviation", cell["ep"], "share", scope=cell["segment"])
                add("share", f"{node} share of volume", cell["volume_share"], "share", scope=cell["segment"])
                add(
                    "change",
                    f"{node} change versus weekly baseline",
                    100 * cell["rel_change"],
                    "pct",
                    scope=cell["segment"],
                )
        case "list_events":
            when = Window(start=request["start"], end=request["end"])
            add(
                "count",
                "Matching log entries",
                len(data["events"]),
                "count",
                subject="log_events",
                scope=request["covering"] or {},
                when=when,
            )
        case "holdout_check":
            assert isinstance(args, HoldoutCheckInput)
            event = args.event.ref
            qualifier = "Neighbouring control" if data["holdout"].get("kind") == "control" else "Held-out slice"
            relative = data["rel_change"]
            label = f"{qualifier} {node} change versus baseline for {event}"
            add("change", label, 100 * relative if relative is not None else None, "pct")
            add("change", f"{qualifier} {node} z-score for {event}", data["z"], "z")
            if data["result"] == "refuted" and relative is not None:
                add(
                    "ruled_out",
                    f"{event} failed its {node} holdout prediction (holdout change)",
                    100 * relative,
                    "pct",
                    subject=event,
                )
        case "placebo_test":
            add("count", f"{node} earlier weeks with a comparable move", data["hits"], "count")
            add("count", f"{node} earlier weeks tested", data["weeks"], "count")
        case "counterfactual_impact":
            graph_node = graph.node(node)
            counted = graph.node(graph_node.numerator) if graph_node.numerator else graph_node
            label = f"Estimated {counted.id} change versus baseline from {node}"
            add("impact", f"{label} per hour", data["per_hour"], f"{counted.unit}/hour")
            add("impact", label, data["so_far"], counted.unit)
            if counted.id in (IMPACT_NODE, "payment_successes") and any(
                row.get("base_orders") and row.get("base_gmv") is not None for rows in reads.values() for row in rows
            ):
                add("impact", f"Estimated GMV change per hour from {node}", data["gmv_eur_per_hour"], "eur/hour")
    return facts


def market_facts(result: MarketAssessment, graph: Graph) -> list[Fact]:
    unit = graph.node(result.node).unit
    facts: list[Fact] = []
    for point in result.series:
        window = Window(start=point.ts, end=point.ts)
        fields: tuple[tuple[ClaimKind, str, float, str], ...] = (
            ("observed", f"Observed {result.node}", point.metric_value, unit),
            ("observed", f"Expected {result.node}", point.metric_expected, unit),
            ("observed", f"Market-adjusted expectation for {result.node}", point.adjusted_expected, unit),
            ("change", f"{result.node} change", point.metric_change_pct, "pct"),
            ("change", f"{result.node} residual change against market", point.residual_pct, "pct"),
            ("count", f"Matched baseline weeks for {result.node}", point.baseline_weeks, "count"),
        )
        facts.extend(
            Fact(kind, result.node, result.segment, window, label, value, display_unit)
            for kind, label, value, display_unit in fields
        )
        facts.append(
            Fact(
                "change",
                result.control,
                {},
                window,
                "Independent market demand change",
                point.control_change_pct,
                "pct",
            )
        )
    return facts


def replay_facts(result: CounterfactualResult, graph: Graph) -> list[Fact]:
    plan = result.receipt.plan
    window = Window(start=plan.onset, end=plan.window.end)
    unit = graph.node(plan.metric).unit
    label = f"{plan.metric} gap summed per hour"
    return [
        Fact(
            "share",
            plan.metric,
            plan.segment,
            window,
            f"{plan.metric} gap explained by simulator replay",
            result.explained_share,
            "share",
        ),
        Fact("impact", plan.metric, plan.segment, window, f"Factual {label}", result.gap.factual, unit),
        Fact("impact", plan.metric, plan.segment, window, f"Counterfactual {label}", result.gap.counterfactual, unit),
        Fact("impact", plan.metric, plan.segment, window, f"Simulated reduction in {label}", result.gap.removed, unit),
    ]
