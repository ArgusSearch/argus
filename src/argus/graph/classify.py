"""Self-classification of a new metric: where a C2 metric YAML belongs in the C3 graph, and the proof.

The contributor writes only `name`, `description` and `sql`. The classifier works out the rest:

1. Lineage (`classify_sql`, deterministic). The value expression is rewritten over node ids: every
   `SUM(measure)` maps to the additive node of that fact view and measure. The shape decides the node kind
   (`SUM(a)` additive, `SUM(a) / SUM(b)` ratio, anything else derived), dimensional analysis the unit.
2. Guards. A join whose USING keys do not cover the grain of every joined view fans out; the factor is
   measured on data and the per-table repair is attached as a diff. A WHERE must select a segment.
3. Definition check. The metric's own SQL is run per hour and compared with Argus' compiled form of the
   proposed node; they must agree before anything is placed.
4. Alias. The same definition as an existing node (lineage) or the same numbers up to a constant factor
   (data) means the metric already exists. Only breakdowns the graph lacks are added (NEW_DIMENSION).
5. Candidate edges, each moving through the lifecycle PROPOSED -> TESTED -> ACCEPTED | REJECTED:

   * lineage (definitional): `A = B * r` for a new ratio `r = A / B`, and telescoping ratio chains
     (`r = x * y`, or an existing `z = r * y`);
   * arithmetic (empirical): `new = x * y` over every pair of existing nodes;
   * breakdowns by every dimension the metric groups by;
   * an LLM or any other `EdgeProposer` (optional): typed suggestions, decided by the same tests;
   * correlation: lagged correlation against nodes with no formula or ingredient link to the new one.

   Formula and breakdown candidates run the seed tests of `edge_tests.EdgeTester` on the same hourly series.
   Empirical formulas must also explain `MIN_EXPLAINED` of the target's variance.
6. Register. The node, the accepted edges and untestable proposals (PROPOSED, zero weight) enter the
   graph; every test run and addition goes to the changelog; a `Certificate` lists what was tried, what
   passed and what is still uncertain.

| evidence for an edge                                  | status    |
|-------------------------------------------------------|-----------|
| formula or breakdown test passed                      | VALID     |
| several equally simple decompositions of the new node | PROBATION (best one; AMBIGUOUS) |
| lagged correlation only                               | PROBATION ("correlated, not causal") |
| proposer mechanism and a passed lagged correlation    | SUPPORTED |
| proposal that cannot be tested here                   | PROPOSED  |

Derived nodes (`SUM(a) - SUM(b)`, constants) are verified but not placed: the semantic layer cannot compile
them yet (`compile.parts`), so edge re-testing would fail on them. The certificate says so.

Try it: `make world`, then
`uv run python -m argus.graph.classify tests/graph_classify/metrics/*.yml --world runs/s1-7/world.duckdb`.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import combinations
from pathlib import Path
from typing import Any, Literal, Protocol

import duckdb
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from argus.contracts.graph import (
    STATUS_WEIGHT,
    Certificate,
    Edge,
    EdgeKind,
    EdgeStatus,
    EdgeTestResult,
    Graph,
    GraphChange,
    Node,
    NodeKind,
    NodeState,
    Provenance,
    Unit,
)
from argus.contracts.metric import MetricDefinition, MetricSqlError, load_metric, parse_metric
from argus.contracts.world import table
from argus.graph.classify_sql import (
    SHARE_WORDS,
    Lineage,
    Segment,
    fanout_problems,
    hourly_as_written,
    label_of,
    lineage,
    name_hint,
    repair_sql,
    segment_of,
    unified_diff,
    unit_of,
)
from argus.graph.classify_stats import (
    LagTest,
    deseasonalise,
    explained_share,
    lag_tests,
    passes_identity,
    residuals,
    with_q,
)
from argus.graph.edge_tests import EdgeTester, eval_expr
from argus.graph.store import (
    CHILDREN_SUM_TEST,
    IDENTITY_TEST,
    LAG_TEST,
    ONSET_TEST,
    Changelog,
    load_seed_graph,
    write_graph,
)
from argus.semantic.compile import hourly_sql
from argus.semantic.runner import Runner, sql_ts

MIN_EXPLAINED = 0.99
"""An empirical formula (arithmetic, alias, proposer) must explain this share of the target's hourly variance."""
MIN_ABS_CORR = 0.3
"""Besides BH significance, a lagged correlation must be at least this strong to support a cause edge."""
MAX_CAUSE_EDGES = 3
"""At most this many correlation-only cause edges per new metric, strongest first."""
DELIVERY_LAG_HOURS = 2
"""As in `EdgeTester`: only hours at least this old are complete."""
METRIC_KEY = "metric"
"""SeriesBank key of the new metric's own series (its SQL as written)."""

PlacedAs = Literal["EXACT", "NEW_DIMENSION", "ALIAS", "AMBIGUOUS", "REJECTED"]


class Lifecycle(StrEnum):
    """Where a candidate edge stands. TESTED is final for an edge that passed but was not chosen."""

    PROPOSED = "proposed"
    TESTED = "tested"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass
class Candidate:
    """One proposed edge, its test result and the decision taken on it."""

    edge: Edge
    why: str
    lifecycle: Lifecycle = Lifecycle.PROPOSED
    result: EdgeTestResult | None = None
    verdict: str = ""
    proposed_by: str = ""
    """Name of the EdgeProposer that suggested it (besides the deterministic rules), if any."""

    @property
    def definitional(self) -> bool:
        return self.edge.provenance is Provenance.LINEAGE

    @property
    def enters_graph(self) -> bool:
        return self.lifecycle in (Lifecycle.ACCEPTED, Lifecycle.PROPOSED)

    def describe(self) -> str:
        e = self.edge
        if e.kind is EdgeKind.FORMULA:
            return f"{e.target} = {e.expr}"
        if e.kind is EdgeKind.BREAKDOWN:
            return f"{e.target} by {e.dim}"
        return f"{', '.join(e.sources)} -> {e.target}"


@dataclass(frozen=True)
class Repair:
    """A fan-out join: how far off the SQL as written is, and the per-table form that fixes it."""

    factor: float
    sql: str
    diff: str


@dataclass
class Placement:
    """The outcome of `classify`: the certificate, the updated graph and every candidate with its lifecycle."""

    metric: MetricDefinition
    certificate: Certificate
    graph: Graph
    node: Node | None = None
    alias_of: str | None = None
    alias_scale: float = 1.0
    segment: Segment = field(default_factory=dict)
    candidates: list[Candidate] = field(default_factory=list)
    changes: list[GraphChange] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    repair: Repair | None = None

    @property
    def placed_as(self) -> PlacedAs:
        return self.certificate.placed_as

    def added_edges(self) -> list[Edge]:
        return [c.edge for c in self.candidates if c.enters_graph]


# --------------------------------------------------------------------------------------------- series


class SeriesBank:
    """Hourly total series over the edge-test window, aligned on the same hours, one receipt per series.

    `cache` has the shape `EdgeTester.test_formula` accepts, so the seed test runs on exactly these numbers.
    """

    def __init__(self, runner: Runner, as_of: datetime, window_days: int = IDENTITY_TEST.window_days):
        self.runner = runner
        self.as_of = as_of
        self.end = (as_of - timedelta(hours=DELIVERY_LAG_HOURS)).replace(minute=0, second=0, microsecond=0)
        self.start = self.end - timedelta(days=window_days) + timedelta(hours=1)
        self.hours = [self.start + timedelta(hours=i) for i in range(window_days * 24)]
        self._index = {h: i for i, h in enumerate(self.hours)}
        self.cache: dict[str, tuple[np.ndarray, str]] = {}

    @property
    def condition(self) -> str:
        return f"ts BETWEEN {sql_ts(self.start)} AND {sql_ts(self.end)}"

    def sql(self, key: str, sql: str, purpose: str) -> np.ndarray:
        """Run (once) a query with columns ts and `value`, or ts, `num` and `den`."""
        if key not in self.cache:
            rows, receipt = self.runner.query(sql, self.as_of, purpose=purpose)
            values = np.full(len(self.hours), np.nan)
            for row in rows:
                i = self._index.get(row["ts"])
                if i is None:
                    continue
                if "value" in row:
                    values[i] = np.nan if row["value"] is None else float(row["value"])
                else:
                    values[i] = float(row["num"] or 0) / float(row["den"]) if row["den"] else np.nan
            self.cache[key] = (values, receipt.id)
        return self.cache[key][0]

    def node(self, graph: Graph, node_id: str, segment: Segment | None = None) -> np.ndarray:
        """A node's compiled hourly series (optionally in one segment). Derived nodes raise NotImplementedError."""
        key = node_id + (json.dumps(segment, sort_keys=True) if segment else "")
        scope = f" in {segment}" if segment else ""
        return self.sql(key, hourly_sql(graph, node_id, self.condition, segment), f"classify: hourly {node_id}{scope}")

    def receipt(self, key: str) -> str:
        return self.cache[key][1]

    def receipts(self) -> list[str]:
        return list(dict.fromkeys(rid for _, rid in self.cache.values()))


# --------------------------------------------------------------------------------------------- proposers


class EdgeSuggestion(BaseModel):
    """A typed edge a proposer (for example an LLM) suggests. Only a proposal: the tests decide."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["formula", "cause"]
    target: str
    sources: list[str] = Field(min_length=1)
    expr: str | None = Field(default=None, description="formula: arithmetic over the sources (default: product)")
    lag_hours: list[int] | None = Field(default=None, description="cause: lags at which the source leads")
    why: str = ""


class SuggestionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edges: list[EdgeSuggestion]


@dataclass(frozen=True)
class ProposalContext:
    metric: MetricDefinition
    node: Node
    graph: Graph
    """The graph with the proposed node already in it."""


class EdgeProposer(Protocol):
    name: str

    def propose(self, context: ProposalContext) -> list[EdgeSuggestion]: ...


class LlmProposer:
    """Asks a language model for typed edges; `complete` is any prompt -> reply function (JSON reply).

    The model never decides. Every suggestion is tested like a deterministic candidate, and one that cannot
    be tested here (for example a log as the source) enters the graph only as PROPOSED with zero weight.
    """

    name = "llm"

    def __init__(self, complete: Callable[[str], str]):
        self.complete = complete

    def prompt(self, context: ProposalContext) -> str:
        new = context.node
        nodes = "\n".join(
            f"- {n.id} ({n.kind}, {n.unit}): {n.description}" for n in context.graph.nodes if n is not new
        )
        logs = "\n".join(f"- {log.id}: {log.description}" for log in context.graph.logs)
        return (
            "You place a new metric in a typed metric graph. Suggest edges that connect it to existing nodes.\n"
            "formula: target = expr over source node ids (an exact arithmetic identity, + - * / only).\n"
            "cause: a source node or log that can drive the target with a lag in hours (a mechanism).\n"
            'Reply with JSON only: {"edges": [{"kind": "formula"|"cause", "target": id, "sources": [ids], '
            '"expr": str|null, "lag_hours": [int]|null, "why": str}]}\n\n'
            f"New metric {new.id} ({new.kind}, {new.unit}): {context.metric.description}\n"
            f"SQL:\n{context.metric.sql}\n\nExisting nodes:\n{nodes}\n\nLogs:\n{logs}\n"
        )

    def propose(self, context: ProposalContext) -> list[EdgeSuggestion]:
        reply = re.sub(r"^```(?:json)?\s*|\s*```$", "", self.complete(self.prompt(context)).strip())
        try:
            return SuggestionBatch.model_validate(json.loads(reply)).edges
        except (json.JSONDecodeError, ValidationError) as err:
            raise ValueError(f"reply is not a valid suggestion batch: {err}") from err


# --------------------------------------------------------------------------------------------- the pipeline


def _ingredients(node: Node) -> set[str]:
    if node.kind is NodeKind.ADDITIVE:
        return {node.id}
    return {i for i in (node.numerator, node.denominator) if i}


class _Classifier:
    def __init__(
        self,
        metric: MetricDefinition,
        graph: Graph,
        runner: Runner,
        as_of: datetime,
        source: str,
        changelog: Changelog,
        proposers: Sequence[EdgeProposer],
    ):
        self.metric = metric
        self.graph = graph
        self.runner = runner
        self.as_of = as_of
        self.source = source
        self.changelog = changelog
        self.proposers = proposers
        self.bank = SeriesBank(runner, as_of)
        self.checks: list[str] = []
        self.uncertain: list[str] = []
        self.candidates: list[Candidate] = []
        self.edge_ids = {e.id for e in graph.edges}
        self.first_seq = len(changelog.entries)
        self.repair: Repair | None = None

    # ------------------------------------------------------------------ main flow

    def run(self) -> Placement:
        m = self.metric
        try:
            parsed = parse_metric(m)
            segment = segment_of(m.sql)
            lin = lineage(m.sql, self.graph, m.name)
        except MetricSqlError as err:
            return self._done("REJECTED", f"cannot place {m.name}: {err}")
        fanout = fanout_problems(m.sql)
        self.checks += [f"fan-out guard: {p}" for p in fanout]
        try:
            written = self.bank.sql(METRIC_KEY, hourly_as_written(m.sql, self.bank.condition), f"classify: {m.name}")
        except duckdb.Error as err:
            return self._done("REJECTED", f"the SQL does not run against the world: {err}")

        # The node the lineage describes: an existing one (alias) or a proposed new one.
        alias = self._lineage_alias(lin)
        node: Node | None = None
        graph = self.graph
        if alias is None and lin.kind is not NodeKind.DERIVED:
            node = self._new_node(lin, parsed.dims, written)
            graph = self._with(node=node)

        # Definition check: the SQL as written against Argus' compiled form.
        what = f"{alias}{segment or ''}" if alias else lin.expr
        try:
            if alias is not None or node is not None:
                compiled = self.bank.node(graph, alias or m.name, segment)
            else:
                compiled = eval_expr(lin.expr, {i: self.bank.node(graph, i, segment) for i in lin.ingredients})
        except ValueError as err:
            return self._done("REJECTED", f"cannot compile {what}: {err}")
        median, p95, hours = residuals(written, compiled)
        if not passes_identity(median, p95):
            return self._reject_definition(lin, parsed.dims, written, compiled, what, fanout, median, hours)
        self.checks.append(
            f"definition check: your SQL equals the compiled {what} over {hours} h "
            f"(median residual {median:.1e}, p95 {p95:.1e})"
        )
        if fanout:
            self.uncertain.append("the join keys do not cover every grain; the numbers agree today but can fan out")

        scale = 1.0
        if alias is None and not segment:
            numeric = self._numeric_alias(written, exclude={m.name})
            if numeric is not None:
                alias, scale = numeric
        self._name_check(alias)
        if alias is not None:
            return self._place_alias(alias, scale, segment, parsed.dims)
        if segment:
            return self._done(
                "REJECTED",
                f"{m.name} filters {segment} but no node computes {lin.expr} yet; remove the WHERE to add the node, "
                "Argus then watches every segment through its breakdowns",
            )
        if node is None:
            return self._done(
                "REJECTED",
                f"{m.name} = {lin.expr} is verified (definition check passed) but is a derived node, which the "
                "semantic layer cannot compile yet (compile.parts); placing it would break edge re-testing",
            )
        if m.name in {n.id for n in self.graph.nodes}:
            return self._done("REJECTED", f"the name {m.name} is taken by a node with a different definition")
        return self._place_new(node, lin, parsed.dims, graph)

    def _reject_definition(
        self,
        lin: Lineage,
        dims: list[str],
        written: np.ndarray,
        compiled: np.ndarray,
        what: str,
        fanout: list[str],
        median: float,
        hours: int,
    ) -> Placement:
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = written / compiled
        finite = ratio[np.isfinite(ratio)]
        factor = float(np.median(finite)) if len(finite) else math.nan
        head = (
            f"{self.metric.name} as written is {factor:.3g}x the compiled {what} "
            f"(median residual {median:.2e} over {hours} h)"
        )
        if not fanout:
            return self._done("REJECTED", f"{head}: the SQL computes something else than its lineage says")
        if lin.kind is NodeKind.RATIO:
            sql = repair_sql(self.metric.sql, self.graph, lin, dims)
            self.repair = Repair(factor, sql, unified_diff(self.metric.sql, sql, self.metric.name))
        return self._done(
            "REJECTED",
            f"{head}: join fan-out ({'; '.join(fanout)}). Repair: aggregate each fact view to the join keys before "
            "dividing (see the repair diff)",
        )

    def _name_check(self, alias: str | None) -> None:
        hint = name_hint(self.metric.name, self.graph)
        if hint is None:
            return
        if hint == alias:
            self.checks.append(f"name: {self.metric.name} names {hint}, and the definition agrees")
        else:
            self.uncertain.append(f"the name points at {hint}, but the definition places it elsewhere")

    # ------------------------------------------------------------------ alias

    def _lineage_alias(self, lin: Lineage) -> str | None:
        if lin.kind is NodeKind.ADDITIVE and lin.missing is None:
            return lin.expr
        for n in self.graph.nodes:
            same = (n.numerator, n.denominator) == (lin.numerator, lin.denominator)
            if lin.kind is NodeKind.RATIO and n.kind is NodeKind.RATIO and same:
                return n.id
        return None

    def _numeric_alias(self, written: np.ndarray, exclude: set[str]) -> tuple[str, float] | None:
        """An existing node with the same numbers up to a constant factor k (k = 1: the same series)."""
        hits: list[tuple[float, str, float]] = []
        for n in self.graph.nodes:
            if n.id in exclude or n.kind is NodeKind.DERIVED:
                continue
            x = self.bank.node(self.graph, n.id)
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = written / x
            ratio = ratio[np.isfinite(ratio)]
            if not len(ratio):
                continue
            k = float(np.median(ratio))
            median, p95, _ = residuals(written, k * x)
            if passes_identity(median, p95) and explained_share(written, k * x) >= MIN_EXPLAINED:
                hits.append((median, n.id, k))
        if not hits:
            self.checks.append("numeric alias: no existing node has the same numbers up to a constant factor")
            return None
        hits.sort()
        _, best, k = hits[0]
        k = float(round(k)) if abs(k - round(k)) < 1e-9 else k
        self.checks.append(f"numeric alias: your numbers are {best} x {k:g} on every hour (residual {hits[0][0]:.1e})")
        if len(hits) > 1:
            self.uncertain.append(f"also the same numbers as {', '.join(h[1] for h in hits[1:])}")
        return best, k

    def _place_alias(self, alias: str, scale: float, segment: Segment, dims: list[str]) -> Placement:
        target = self.graph.node(alias)
        scaled = f" x {scale:g}" if scale != 1 else ""
        cell = f"{alias}{segment}" if segment else alias
        have = {e.dim for e in self.graph.edges_into(alias, EdgeKind.BREAKDOWN)}
        for d in dict.fromkeys([*dims, *segment]):
            if d in have:
                continue
            if d not in target.dims:
                self.uncertain.append(f"{alias} cannot be broken down by {d}")
                continue
            self.candidates.append(self._breakdown(alias, d, "the metric groups by it and the graph lacks it"))
        tester = EdgeTester(self.graph, self.runner)
        for cand in self.candidates:
            self._test_breakdown(tester, cand)
        accepted = [c for c in self.candidates if c.lifecycle is Lifecycle.ACCEPTED]
        self._log_additions(None, accepted)
        graph = self._with(edges=[c.edge for c in accepted])
        kw: dict[str, Any] = {"alias_of": alias, "scale": scale, "segment": segment}
        if accepted:
            by = ", ".join(c.edge.dim or "" for c in accepted)
            return self._done(
                "NEW_DIMENSION",
                f"{self.metric.name} already exists as {cell}{scaled}; it adds the breakdown of {alias} by {by} "
                "(children sum verified)",
                graph,
                **kw,
            )
        watched = f", watched through the breakdown by {', '.join(segment)}" if segment else ""
        return self._done(
            "ALIAS", f"{self.metric.name} already exists as {cell}{scaled}{watched}; no new node", graph, **kw
        )

    # ------------------------------------------------------------------ new node

    def _new_node(self, lin: Lineage, dims: list[str], written: np.ndarray) -> Node:
        m = self.metric
        common: dict[str, Any] = {
            "id": m.name,
            "label": label_of(m.name),
            "description": m.description,
            "sql": m.sql.strip(),
            "source": self.source,
        }
        if lin.missing is not None:
            tbl, measure = lin.missing
            sql_type = next(c.sql_type for c in table(tbl).columns if c.name == measure)
            unit: Unit = "eur" if sql_type == "DOUBLE" else "count"
            self.checks.append(f"lineage: SUM({measure}) over {tbl} is a new base measure ({unit})")
            return Node(
                **common,
                kind=NodeKind.ADDITIVE,
                unit=unit,
                dims=table(tbl).dims,
                table=tbl,
                measure=measure,
            )
        assert lin.numerator and lin.denominator
        unit, why = unit_of(lin.expr, {n.id: n.unit for n in self.graph.nodes}, written)
        num, den = self.graph.node(lin.numerator), self.graph.node(lin.denominator)
        node_dims = [d for d in num.dims if d in den.dims]
        self.checks.append(f"lineage: ratio {lin.numerator} / {lin.denominator}; unit {unit} ({why})")
        if unit != "share" and set(m.name.split("_")) & SHARE_WORDS:
            self.uncertain.append(f"the name suggests a share, but the unit is {unit} ({why})")
        if [d for d in dims if d not in node_dims]:
            self.uncertain.append(f"grouped by {dims}, but only {node_dims} are carried by both ingredients")
        return Node(
            **common,
            kind=NodeKind.RATIO,
            unit=unit,
            dims=node_dims,
            numerator=lin.numerator,
            denominator=lin.denominator,
        )

    def _place_new(self, node: Node, lin: Lineage, dims: list[str], graph: Graph) -> Placement:
        self._lineage_candidates(node, lin)
        self._arithmetic_candidates(node)
        for d in dims:
            if d in node.dims:
                self.candidates.append(self._breakdown(node.id, d, "the metric groups by it"))
        self._proposer_candidates(node, graph)

        tester = EdgeTester(graph, self.runner)
        self.bank.cache[node.id] = self.bank.cache[METRIC_KEY]  # tests see the metric exactly as written
        for cand in list(self.candidates):
            if cand.lifecycle is not Lifecycle.PROPOSED:
                continue
            if cand.edge.kind is EdgeKind.FORMULA:
                self._test_formula(tester, cand, graph)
            elif cand.edge.kind is EdgeKind.BREAKDOWN:
                self._test_breakdown(tester, cand)
            elif cand.edge.kind is EdgeKind.CAUSE:
                self._test_cause(cand, graph)
        ambiguous = self._resolve_ambiguity(node)
        self._correlation_scan(node, graph)
        del self.bank.cache[node.id]

        for cand in self.candidates:
            if cand.lifecycle is Lifecycle.PROPOSED:
                cand.verdict = cand.verdict or "not testable here: kept with zero weight"
        formulas = [c for c in self.candidates if c.lifecycle is Lifecycle.ACCEPTED and c.edge.kind is EdgeKind.FORMULA]
        if not formulas:
            ambiguous = True
            self.uncertain.append("no formula connects the node to the graph; only correlations place it")
        state: NodeState = "probation" if ambiguous else "watching"
        node = node.model_copy(update={"state": state})
        entering = [c for c in self.candidates if c.enters_graph]
        self._log_additions(node, entering)
        result = Graph(
            version=self.graph.version,
            nodes=[*self.graph.nodes, node],
            edges=[*self.graph.edges, *(c.edge for c in entering)],
            logs=self.graph.logs,
        )
        placed_as: PlacedAs = "AMBIGUOUS" if ambiguous else "EXACT"
        worst = max((c.result.median_rel or 0.0 for c in formulas if c.result), default=0.0)
        breakdowns = [c.edge.dim or "" for c in entering if c.edge.kind is EdgeKind.BREAKDOWN]
        summary = (
            f"{node.id} = {lin.expr} ({node.kind}, {node.unit}): {len(formulas)} formula edge(s) verified "
            f"(median residual <= {worst:.1e} over {len(self.bank.hours)} h)"
            + (f", breakdowns by {', '.join(breakdowns)} verified" if breakdowns else "")
        )
        return self._done(placed_as, summary, result, node=node)

    # ------------------------------------------------------------------ candidates

    def _new_edge_id(self, base: str) -> str:
        eid, n = base, 2
        while eid in self.edge_ids:
            eid, n = f"{base}_{n}", n + 1
        self.edge_ids.add(eid)
        return eid

    def _formula(self, target: str, sources: list[str], expr: str, provenance: Provenance, why: str) -> Candidate:
        edge = Edge(
            id=self._new_edge_id(f"f_{target}_from_{'_'.join(sources)}"),
            kind=EdgeKind.FORMULA,
            target=target,
            sources=sources,
            expr=expr,
            status=EdgeStatus.PROPOSED,
            weight=0.0,
            provenance=provenance,
            test=IDENTITY_TEST,
        )
        return Candidate(edge, why)

    def _breakdown(self, target: str, dim: str, why: str) -> Candidate:
        edge = Edge(
            id=self._new_edge_id(f"b_{target}_{dim}"),
            kind=EdgeKind.BREAKDOWN,
            target=target,
            dim=dim,
            status=EdgeStatus.PROPOSED,
            weight=0.0,
            provenance=Provenance.LINEAGE,
            test=CHILDREN_SUM_TEST,
        )
        return Candidate(edge, why)

    def _lineage_candidates(self, node: Node, lin: Lineage) -> None:
        """Edges that hold by definition: `A = B * r`, and telescoping ratio chains through r."""
        r, a, b = node.id, lin.numerator, lin.denominator
        if lin.kind is not NodeKind.RATIO or not a or not b:
            return
        self.candidates.append(
            self._formula(a, [b, r], f"{b} * {r}", Provenance.LINEAGE, f"definition {r} = {a} / {b}")
        )
        ratios = [n for n in self.graph.nodes if n.kind is NodeKind.RATIO]
        for x in ratios:
            for y in ratios:
                if y.denominator == b and y.numerator == x.denominator and x.numerator == a:  # r = (C/B) * (A/C)
                    why = f"ratio chain {b} -> {y.numerator} -> {a}"
                    self.candidates.append(self._formula(r, [y.id, x.id], f"{y.id} * {x.id}", Provenance.LINEAGE, why))
                if x.numerator == a and y.numerator == b and x.denominator == y.denominator:  # x = (B/D) * (A/B)
                    why = f"ratio chain {x.denominator} -> {b} -> {a}"
                    self.candidates.append(self._formula(x.id, [y.id, r], f"{y.id} * {r}", Provenance.LINEAGE, why))
                if x.denominator == b and y.denominator == a and x.numerator == y.numerator:  # x = (A/B) * (C/A)
                    why = f"ratio chain {b} -> {a} -> {x.numerator}"
                    self.candidates.append(self._formula(x.id, [r, y.id], f"{r} * {y.id}", Provenance.LINEAGE, why))

    def _arithmetic_candidates(self, node: Node) -> None:
        """`new = x * y` for every pair of existing nodes; only near-exact, discriminating fits become candidates."""
        written = self.bank.cache[METRIC_KEY][0]
        known = {frozenset(c.edge.sources) for c in self.candidates if c.edge.target == node.id}
        ids = [n.id for n in self.graph.nodes if n.kind is not NodeKind.DERIVED]
        series = {i: self.bank.node(self.graph, i) for i in ids}
        pairs = [(x, y) for x, y in combinations(ids, 2) if frozenset((x, y)) not in known]
        for x, y in pairs:
            pred = series[x] * series[y]
            if passes_identity(*residuals(written, pred)[:2]) and explained_share(written, pred) >= MIN_EXPLAINED:
                why = "fits on 28 days of data (empirical)"
                self.candidates.append(self._formula(node.id, [x, y], f"{x} * {y}", Provenance.ARITHMETIC, why))
        self.checks.append(f"arithmetic search: {len(pairs)} products of existing nodes screened against {node.id}")

    def _proposer_candidates(self, node: Node, graph: Graph) -> None:
        context = ProposalContext(self.metric, node, graph)
        for proposer in self.proposers:
            try:
                suggestions = proposer.propose(context)
            except Exception as err:  # a proposer must never break placement
                self.uncertain.append(f"proposer {proposer.name} failed: {err}")
                continue
            for s in suggestions:
                self._suggestion(proposer.name, s, node, graph)

    def _suggestion(self, by: str, s: EdgeSuggestion, node: Node, graph: Graph) -> None:
        why = f"{by}: {s.why}" if s.why else f"suggested by {by}"
        for c in self.candidates:
            if c.edge.kind.value == s.kind and c.edge.target == s.target and set(c.edge.sources) == set(s.sources):
                c.proposed_by, c.why = by, f"{c.why}; also {why}"
                return
        ids = {n.id for n in graph.nodes}
        logs = {log.id for log in graph.logs}
        unknown = [i for i in [s.target, *s.sources] if i not in ids | logs]
        if s.kind == "formula":
            expr = s.expr or " * ".join(s.sources)
            cand = self._formula(s.target, list(s.sources), expr, Provenance.LLM, why)
            cand.proposed_by = by
            try:
                names = {n.id for n in ast.walk(ast.parse(expr, mode="eval")) if isinstance(n, ast.Name)}
            except SyntaxError:
                names = set()
            if unknown or names != set(s.sources) or node.id not in [s.target, *s.sources]:
                bad = (
                    f"unknown ids {unknown}" if unknown else "expr must use exactly the sources, one being the new node"
                )
                cand.lifecycle, cand.verdict = Lifecycle.REJECTED, f"invalid: {bad}"
            self.candidates.append(cand)
            return
        from_logs = [x for x in s.sources if x in logs]
        problem: str | None
        if unknown:
            problem = f"unknown ids {unknown}"
        elif s.target in logs:
            problem = "a log cannot be the effect"
        elif node.id not in [s.target, *s.sources]:
            problem = "the edge must involve the new node"
        elif from_logs and len(from_logs) != len(s.sources):
            problem = "sources mix logs and nodes"
        else:
            problem = None
        if problem:
            edge = Edge(
                id=self._new_edge_id(f"c_{by}_{node.id}"),
                kind=EdgeKind.CAUSE,
                target=node.id,
                sources=[node.id],
                status=EdgeStatus.PROPOSED,
                weight=0.0,
                provenance=Provenance.LLM,
            )
            self.candidates.append(
                Candidate(edge, why, Lifecycle.REJECTED, verdict=f"invalid: {problem}", proposed_by=by)
            )
            return
        if from_logs:
            # A log as the cause is an evidence edge; onset alignment is checked inside every investigation.
            edge = Edge(
                id=self._new_edge_id(f"ev_{'_'.join(x.removeprefix('log_') for x in s.sources)}_{s.target}"),
                kind=EdgeKind.EVIDENCE,
                target=s.target,
                sources=list(s.sources),
                status=EdgeStatus.PROPOSED,
                weight=0.0,
                provenance=Provenance.LLM,
                test=ONSET_TEST,
            )
            verdict = "evidence edges are checked per investigation (onset alignment): kept with zero weight"
            self.candidates.append(Candidate(edge, why, verdict=verdict, proposed_by=by))
            return
        edge = Edge(
            id=self._new_edge_id(f"c_{'_'.join(s.sources)}_{s.target}"),
            kind=EdgeKind.CAUSE,
            target=s.target,
            sources=list(s.sources),
            lag_hours=s.lag_hours or LAG_TEST.lag_hours,
            status=EdgeStatus.PROPOSED,
            weight=0.0,
            provenance=Provenance.LLM,
            test=LAG_TEST,
        )
        self.candidates.append(Candidate(edge, why, proposed_by=by))

    # ------------------------------------------------------------------ tests

    def _series(self, graph: Graph, node_id: str) -> np.ndarray:
        if node_id == self.metric.name:
            return self.bank.cache[METRIC_KEY][0]
        return self.bank.node(graph, node_id)

    def _test_formula(self, tester: EdgeTester, cand: Candidate, graph: Graph) -> None:
        e = cand.edge
        try:
            for i in [e.target, *e.sources]:
                self._series(graph, i)
        except NotImplementedError as err:
            cand.verdict = f"not testable here ({err}): kept with zero weight"
            return
        result = tester.test_formula(e, self.as_of, self.bank.cache)
        cand.result, cand.lifecycle = result, Lifecycle.TESTED
        numbers = f"median residual {result.median_rel:.1e}, p95 {result.p95_rel:.1e} over {result.hours} h"
        passed = bool(result.passed)
        if passed and not cand.definitional:
            values = {i: self.bank.cache[i][0] for i in e.sources}
            explained = explained_share(self.bank.cache[e.target][0], eval_expr(e.expr or "", values))
            passed = explained >= MIN_EXPLAINED
            numbers += f", explains {explained:.1%} of the variance"
        self._decide(cand, passed, EdgeStatus.VALID, numbers, result)

    def _test_breakdown(self, tester: EdgeTester, cand: Candidate) -> None:
        result = tester.test_breakdown(cand.edge, self.as_of)
        cand.result, cand.lifecycle = result, Lifecycle.TESTED
        numbers = f"children sum max error {result.max_rel_err:.1e} over {result.hours} h"
        self._decide(cand, bool(result.passed), EdgeStatus.VALID, numbers, result)

    def _test_cause(self, cand: Candidate, graph: Graph) -> None:
        """A proposed mechanism: supported when the source leads the target at one of its lags (BH over them)."""
        e = cand.edge
        try:
            target = deseasonalise(self._series(graph, e.target), self.bank.hours)
            sources = {s: deseasonalise(self._series(graph, s), self.bank.hours) for s in e.sources}
        except NotImplementedError as err:
            cand.verdict = f"not testable here ({err}): kept with zero weight"
            return
        tests = with_q(
            [t for s, v in sources.items() for t in lag_tests(s, v, e.target, target, e.lag_hours or [0], both=False)]
        )
        best = min(tests, key=lambda t: (t.q, -abs(t.r)))
        passed = best.q < (LAG_TEST.alpha or 0) and abs(best.r) >= MIN_ABS_CORR
        note = f"{best.describe()} over {len(tests)} lag tests"
        keys = [METRIC_KEY if i == self.metric.name else i for i in (e.target, *e.sources)]
        result = EdgeTestResult(
            ran_at=self.as_of, passed=passed, hours=best.n, receipts=[self.bank.receipt(k) for k in keys], note=note
        )
        cand.result, cand.lifecycle = result, Lifecycle.TESTED
        self._decide(cand, passed, EdgeStatus.SUPPORTED, f"mechanism proposed, {note}", result)

    def _decide(self, cand: Candidate, passed: bool, status: EdgeStatus, numbers: str, result: EdgeTestResult) -> None:
        if passed:
            cand.lifecycle, cand.verdict = Lifecycle.ACCEPTED, numbers
            update = {"status": status, "weight": STATUS_WEIGHT[status], "last_test": result}
            cand.edge = cand.edge.model_copy(update=update)
        else:
            cand.lifecycle, cand.verdict = Lifecycle.REJECTED, f"failed: {numbers}"
        self._log_test(cand)

    def _resolve_ambiguity(self, node: Node) -> bool:
        """Several decompositions of the new node passed: the simplest wins, a tie makes the placement ambiguous."""
        decomps = [
            c
            for c in self.candidates
            if c.lifecycle is Lifecycle.ACCEPTED and c.edge.kind is EdgeKind.FORMULA and c.edge.target == node.id
        ]
        if len(decomps) < 2:
            return False

        def rank(c: Candidate) -> tuple[int, int]:
            return (0 if c.definitional else 1, len(c.edge.sources))

        decomps.sort(key=lambda c: (*rank(c), c.result.median_rel or 0.0 if c.result else 0.0))
        best, rest = decomps[0], decomps[1:]
        tied = [c for c in rest if rank(c) == rank(best)]
        for c in rest:
            c.lifecycle = Lifecycle.TESTED
            c.verdict += f"; kept as an alternative to {best.edge.id}"
            c.edge = c.edge.model_copy(update={"status": EdgeStatus.PROPOSED, "weight": 0.0})
        if not tied:
            return False
        note = (
            f"ambiguous: {len(tied) + 1} equally simple formulas fit ({'; '.join(c.describe() for c in [best, *tied])})"
        )
        status = EdgeStatus.PROBATION
        best.edge = best.edge.model_copy(update={"status": status, "weight": STATUS_WEIGHT[status], "note": note})
        best.verdict += f"; {status} because {note}"
        self.uncertain.append(note)
        return True

    def _mechanical(self, node: Node) -> set[str]:
        """Nodes tied to the new one by formulas or shared ingredients: their correlation is arithmetic, not cause."""
        formulas = [e for e in self.graph.edges if e.kind is EdgeKind.FORMULA] + [
            c.edge for c in self.candidates if c.edge.kind is EdgeKind.FORMULA and c.lifecycle is Lifecycle.ACCEPTED
        ]

        def factors(start: str) -> set[str]:
            """Every node the start decomposes into, through nested formulas."""
            out: set[str] = set()
            todo = [start]
            while todo:
                current = todo.pop()
                for e in formulas:
                    if e.target == current:
                        fresh = [s for s in e.sources if s not in out]
                        out |= set(fresh)
                        todo += fresh
            return out

        near = {node.id} | factors(node.id)
        for e in formulas:
            if node.id in e.sources:
                near |= {e.target, *e.sources}
        nodes = {n.id: n for n in [*self.graph.nodes, node]}
        shared = set().union(*(_ingredients(nodes[i]) for i in near if i in nodes))
        mine = factors(node.id)
        return {
            n.id
            for n in self.graph.nodes
            if n.id in near or _ingredients(n) & shared or factors(n.id) & mine or n.kind is NodeKind.DERIVED
        }

    def _correlation_scan(self, node: Node, graph: Graph) -> None:
        """Cause candidates from data alone: BH-significant lagged correlations with formula-unrelated nodes."""
        excluded = self._mechanical(node) | {c.edge.target for c in self.candidates if c.edge.kind is EdgeKind.CAUSE}
        excluded |= {s for c in self.candidates if c.edge.kind is EdgeKind.CAUSE for s in c.edge.sources}
        pool = [n.id for n in self.graph.nodes if n.id not in excluded]
        mine = deseasonalise(self._series(graph, node.id), self.bank.hours)
        lags = LAG_TEST.lag_hours or [0]
        tests = with_q(
            [
                t
                for i in pool
                for t in lag_tests(i, deseasonalise(self.bank.node(graph, i), self.bank.hours), node.id, mine, lags)
            ]
        )
        alpha = LAG_TEST.alpha or 0
        best: dict[str, LagTest] = {}
        for t in tests:
            other = t.leader if t.follower == node.id else t.follower
            if t.q < alpha and abs(t.r) >= MIN_ABS_CORR and (other not in best or abs(t.r) > abs(best[other].r)):
                best[other] = t
        winners = sorted(best.values(), key=lambda t: -abs(t.r))[:MAX_CAUSE_EDGES]
        self.checks.append(
            f"correlation scan: {len(pool)} nodes without a formula or ingredient link x lags {lags[0]}..{lags[-1]} h "
            f"both ways = {len(tests)} tests, BH alpha {alpha}, |r| >= {MIN_ABS_CORR}: {len(best)} passed, "
            f"kept {len(winners)}"
        )
        for t in winners:
            other = t.leader if t.follower == node.id else t.follower
            source, target = (t.leader, t.follower) if t.lag else (other, node.id)
            note = f"{t.describe()} over {len(tests)} tests"
            keys = [METRIC_KEY if i == node.id else i for i in (target, source)]
            result = EdgeTestResult(
                ran_at=self.as_of, passed=True, hours=t.n, receipts=[self.bank.receipt(k) for k in keys], note=note
            )
            edge = Edge(
                id=self._new_edge_id(f"c_{source}_{target}"),
                kind=EdgeKind.CAUSE,
                target=target,
                sources=[source],
                lag_hours=[t.lag],
                status=EdgeStatus.PROBATION,
                weight=STATUS_WEIGHT[EdgeStatus.PROBATION],
                provenance=Provenance.LEARNED,
                test=LAG_TEST,
                last_test=result,
                note="correlated, not causal",
            )
            cand = Candidate(edge, "correlation scan", Lifecycle.ACCEPTED, result, f"correlated, not causal: {note}")
            self.candidates.append(cand)
            self._log_test(cand)
            self.uncertain.append(f"{edge.id} is a correlation only (PROBATION, half weight): correlated, not causal")

    # ------------------------------------------------------------------ registration

    def _with(self, node: Node | None = None, edges: Sequence[Edge] = ()) -> Graph:
        nodes = [*self.graph.nodes, node] if node else list(self.graph.nodes)
        return Graph(version=self.graph.version, nodes=nodes, edges=[*self.graph.edges, *edges], logs=self.graph.logs)

    def _log_test(self, cand: Candidate) -> None:
        self.changelog.append(
            sim_ts=self.as_of,
            kind="test_run",
            node=self.metric.name,
            edge=cand.edge.id,
            reason=f"{cand.describe()}: {cand.lifecycle} ({cand.verdict})",
            receipts=cand.result.receipts if cand.result else [],
        )

    def _log_additions(self, node: Node | None, entering: Sequence[Candidate]) -> None:
        if node is not None:
            self.changelog.append(
                sim_ts=self.as_of,
                kind="node_added",
                node=node.id,
                reason=f"onboarded from {self.source} as {node.kind} ({node.unit}), state {node.state}",
                receipts=[self.bank.receipt(METRIC_KEY)],
            )
        for c in entering:
            self.changelog.append(
                sim_ts=self.as_of,
                kind="edge_added",
                node=self.metric.name,
                edge=c.edge.id,
                new_status=c.edge.status,
                reason=f"{c.describe()} [{c.edge.provenance}]: {c.verdict}",
                receipts=c.result.receipts if c.result else [],
            )

    def _done(
        self,
        placed_as: PlacedAs,
        summary: str,
        graph: Graph | None = None,
        node: Node | None = None,
        alias_of: str | None = None,
        scale: float = 1.0,
        segment: Segment | None = None,
    ) -> Placement:
        receipts = self.bank.receipts()
        for c in self.candidates:
            receipts += [r for r in (c.result.receipts if c.result else []) if r not in receipts]
        cert = Certificate(
            metric=self.metric.name,
            placed_as=placed_as,
            summary=summary,
            tried=self.checks
            + [
                f"{c.edge.id} [{c.edge.provenance}] {c.describe()} -> {c.lifecycle}: {c.verdict}"
                for c in self.candidates
            ],
            passed=[
                f"{c.edge.id} {c.describe()} -> {c.edge.status}: {c.verdict}"
                for c in self.candidates
                if c.lifecycle is Lifecycle.ACCEPTED
            ],
            uncertain=self.uncertain,
            edges=[c.edge.id for c in self.candidates if c.enters_graph] if graph else [],
            receipts=receipts,
        )
        if placed_as == "REJECTED":
            self.changelog.append(
                sim_ts=self.as_of,
                kind="test_run",
                node=self.metric.name,
                reason=f"REJECTED: {summary}",
                receipts=receipts,
            )
        return Placement(
            metric=self.metric,
            certificate=cert,
            graph=graph or self.graph,
            node=node,
            alias_of=alias_of,
            alias_scale=scale,
            segment=segment or {},
            candidates=self.candidates,
            changes=self.changelog.entries[self.first_seq :],
            checks=self.checks,
            repair=self.repair,
        )


def classify(
    metric: MetricDefinition,
    graph: Graph,
    runner: Runner,
    as_of: datetime,
    *,
    source: str | None = None,
    changelog: Changelog | None = None,
    proposers: Sequence[EdgeProposer] = (),
) -> Placement:
    """Place one C2 metric in the graph. Never mutates `graph`; the result carries the updated graph.

    `as_of` pins the data: the 28 complete days before it are the test window. `changelog`, when given,
    receives every test run and addition. `proposers` (for example an `LlmProposer`) may suggest extra edges.
    """
    source = source or f"metrics/{metric.name}.yml"
    return _Classifier(metric, graph, runner, as_of, source, changelog or Changelog(), proposers).run()


# --------------------------------------------------------------------------------------------- CLI


def render(p: Placement) -> str:
    """A terminal report of one placement: the verdict, every check and every candidate with its lifecycle."""
    c = p.certificate
    lines = [f"{c.metric}  ->  {c.placed_as}", f"  {c.summary}"]
    lines += [f"  check      {line}" for line in p.checks]
    for cand in p.candidates:
        status = str(cand.edge.status) if cand.enters_graph else ""
        lines.append(
            f"  {cand.lifecycle.upper():<10} {status:<9} {cand.edge.kind:<9} {cand.describe():<58} "
            f"[{cand.edge.provenance}] {cand.verdict}"
        )
    lines += [f"  uncertain  {u}" for u in c.uncertain]
    if p.repair:
        lines += ["  repair diff:", *(f"    {line}" for line in p.repair.diff.splitlines())]
    return "\n".join(lines)


def _default_as_of(world: Path) -> datetime:
    manifest = world.parent / "manifest.json"
    if not manifest.exists():
        raise SystemExit(f"no manifest.json next to {world}; pass --as-of")
    return datetime.fromisoformat(json.loads(manifest.read_text())["live_start"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m argus.graph.classify", description=(__doc__ or "").split("\n")[0])
    parser.add_argument("metrics", nargs="+", type=Path, help="metric YAML files (C2), placed in order")
    parser.add_argument("--world", type=Path, required=True, help="world.duckdb")
    parser.add_argument("--as-of", type=datetime.fromisoformat, help="default: live_start from manifest.json")
    parser.add_argument("--graph", type=Path, help="graph.json to start from (default: the seed graph)")
    parser.add_argument("--llm-replay", type=Path, help="a recorded LLM reply (JSON) to use as the LLM proposer")
    parser.add_argument("--out", type=Path, help="write graph.json, graph_changelog.jsonl, certificates.json here")
    parser.add_argument("--json", action="store_true", help="print the certificates as JSON instead of the report")
    args = parser.parse_args(argv)

    graph = Graph.model_validate_json(args.graph.read_text()) if args.graph else load_seed_graph()
    as_of = args.as_of or _default_as_of(args.world)
    proposers: list[EdgeProposer] = []
    if args.llm_replay:
        reply = args.llm_replay.read_text()
        proposers.append(LlmProposer(lambda _prompt: reply))
    runner = Runner(args.world)
    changelog = Changelog()
    placements = []
    for path in args.metrics:
        placement = classify(
            load_metric(path), graph, runner, as_of, source=str(path), changelog=changelog, proposers=proposers
        )
        graph = placement.graph
        placements.append(placement)
        if not args.json:
            print(render(placement), end="\n\n")
    certificates = [p.certificate.model_dump(mode="json") for p in placements]
    if args.json:
        print(json.dumps(certificates, indent=2))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        write_graph(graph, args.out / "graph.json")
        changelog.write(args.out / "graph_changelog.jsonl")
        (args.out / "certificates.json").write_text(json.dumps(certificates, indent=2) + "\n")
    runner.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
