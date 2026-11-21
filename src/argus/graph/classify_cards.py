"""Before/after cards: every graph state change with the test value that caused it, ready for the UI.

Trust is shown as transitions that carry their number: `PROPOSED -> VALID, residual 0.00 %`,
`PROPOSED -> PROBATION, r=0.81 same hour, correlated not causal`, `new metric -> REJECTED, fan-out x8`
with the repair diff. One `Card` shape covers both sources of change:

* `placement_cards`: everything a metric onboarding did (the metric verdict, the node, each candidate edge);
* `retest_cards`: the status changes of an `EdgeTester.run_all` re-test (for example `VALID -> BROKEN`).

`to_events` maps cards onto the existing C5 payloads (`edge_status` with the test result, `graph_changed`
with the changelog entry), so the stream needs no new event type. The card list itself (with the repair diff,
which C5 has no field for) is written to `cards.json` by the CLI.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from argus.contracts.events import EdgeStatusPayload, EventType
from argus.contracts.graph import EdgeKind, EdgeStatus, EdgeTestResult, Provenance
from argus.graph.classify import Candidate, Lifecycle, Placement, describe_edge, ingredients_of
from argus.graph.edge_tests import EdgeStatusChange

Tone = Literal["good", "watch", "bad"]

_STATUS_TONE: dict[str, Tone] = {
    EdgeStatus.VALID: "good",
    EdgeStatus.SUPPORTED: "good",
    EdgeStatus.PROBATION: "watch",
    EdgeStatus.PROPOSED: "watch",
    EdgeStatus.BROKEN: "bad",
    "EXACT": "good",
    "NEW_DIMENSION": "good",
    "ALIAS": "good",
    "AMBIGUOUS": "watch",
    "REJECTED": "bad",
    "ALTERNATIVE": "watch",
    "watching": "good",
    "probation": "watch",
}


class Card(BaseModel):
    """One before -> after transition of the graph, with the evidence that moved it."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="stable within a run: '<metric or retest>/<subject>'")
    sim_ts: datetime
    metric: str | None = Field(default=None, description="the onboarded metric that caused it; None for a re-test")
    subject: str = Field(description="edge id, node id or metric name")
    subject_kind: Literal["metric", "node", "edge"]
    edge_kind: EdgeKind | None = None
    title: str = Field(description="what changed, e.g. 'gmv = sessions * revenue_per_session'")
    before: str = Field(description="state before, e.g. PROPOSED, VALID, 'new metric', 'absent'")
    after: str = Field(description="state after, e.g. VALID, BROKEN, REJECTED, EXACT")
    tone: Tone = Field(description="UI colour hint: good (passed), watch (half or zero weight), bad")
    evidence: str = Field(description="the test value that decided it, e.g. 'residual 0.00 % over 672 h'")
    detail: str = ""
    provenance: Provenance | None = None
    receipts: list[str] = Field(default_factory=list)
    diff: str | None = Field(default=None, description="repair diff (fan-out), unified format")
    result: EdgeTestResult | None = Field(default=None, description="the full test result behind the evidence")

    def line(self) -> str:
        title = self.title if len(self.title) <= 58 else self.title[:57] + "~"
        return f"{self.before:>10} -> {self.after:<13} {title:<58} {self.evidence}"


def evidence(kind: EdgeKind, result: EdgeTestResult | None) -> str:
    """The deciding number of a test result in words."""
    if result is None:
        return "not tested here"
    if kind is EdgeKind.FORMULA and result.median_rel is not None:
        p95 = f", p95 {result.p95_rel * 100:.2f} %" if result.p95_rel is not None else ""
        return f"residual {result.median_rel * 100:.2f} %{p95} over {result.hours} h"
    if kind is EdgeKind.BREAKDOWN and result.max_rel_err is not None:
        return f"children sum off by at most {result.max_rel_err * 100:.2f} % over {result.hours} h"
    return result.note or ("passed" if result.passed else "failed")


def _after(c: Candidate) -> str:
    if c.lifecycle is Lifecycle.REJECTED:
        return "REJECTED"
    if c.lifecycle is Lifecycle.TESTED:
        return "ALTERNATIVE"
    return str(c.edge.status)


def placement_cards(p: Placement) -> list[Card]:
    """Cards for one onboarding: the metric verdict first, then the node, then every candidate edge."""
    name = p.metric.name
    if p.repair:
        verdict = f"fan-out x{p.repair.factor:.3g}: the join counts rows several times"
    elif p.alias_of:
        scale = f" x {p.alias_scale:g}" if p.alias_scale != 1 else ""
        verdict = f"same numbers as {p.alias_of}{p.segment or ''}{scale}"
    else:
        verdict = p.definition or p.certificate.summary
    cards = [
        Card(
            id=f"{name}/{name}",
            sim_ts=p.as_of,
            metric=name,
            subject=name,
            subject_kind="metric",
            title=f"{name}: {p.metric.description}",
            before="new metric",
            after=p.placed_as,
            tone=_STATUS_TONE[p.placed_as],
            evidence=verdict,
            detail=p.certificate.summary,
            receipts=p.certificate.receipts,
            diff=p.repair.diff if p.repair else None,
        )
    ]
    if p.node is not None:
        cards.append(
            Card(
                id=f"{name}/node:{p.node.id}",
                sim_ts=p.as_of,
                metric=name,
                subject=p.node.id,
                subject_kind="node",
                title=f"{p.node.label} ({p.node.kind}, {p.node.unit})",
                before="absent",
                after=p.node.state,
                tone=_STATUS_TONE.get(p.node.state, "watch"),
                evidence=p.definition,
                detail=f"{p.node.kind} over {', '.join(sorted(ingredients_of(p.node)))}; dims {', '.join(p.node.dims)}",
                receipts=p.certificate.receipts[:1],
            )
        )
    for c in p.candidates:
        after = _after(c)
        cards.append(
            Card(
                id=f"{name}/{c.edge.id}",
                sim_ts=p.as_of,
                metric=name,
                subject=c.edge.id,
                subject_kind="edge",
                edge_kind=c.edge.kind,
                title=describe_edge(c.edge),
                before=str(EdgeStatus.PROPOSED),
                after=after,
                tone=_STATUS_TONE.get(after, "bad"),
                evidence=evidence(c.edge.kind, c.result),
                detail=c.verdict,
                provenance=c.edge.provenance,
                receipts=c.result.receipts if c.result else [],
                result=c.result,
            )
        )
    return cards


def retest_cards(changes: Sequence[EdgeStatusChange], as_of: datetime) -> list[Card]:
    """Cards for a re-test tick: only real transitions (a first run that confirms the status is no news)."""
    cards = []
    for ch in changes:
        if ch.old is None or ch.old is ch.new:
            continue
        cards.append(
            Card(
                id=f"retest/{ch.edge.id}@{as_of:%Y%m%dT%H%M}",
                sim_ts=as_of,
                subject=ch.edge.id,
                subject_kind="edge",
                edge_kind=ch.edge.kind,
                title=describe_edge(ch.edge),
                before=str(ch.old),
                after=str(ch.new),
                tone=_STATUS_TONE[ch.new],
                evidence=evidence(ch.edge.kind, ch.result),
                detail=ch.edge.note,
                provenance=ch.edge.provenance,
                receipts=ch.result.receipts,
                result=ch.result,
            )
        )
    return cards


def to_events(p: Placement) -> list[tuple[EventType, dict[str, Any]]]:
    """The placement as C5 payloads: one `graph_changed` per changelog entry, one `edge_status` per tested edge
    that entered the graph (old_status None: the edge is new)."""
    events: list[tuple[EventType, dict[str, Any]]] = [
        (EventType.GRAPH_CHANGED, change.model_dump(mode="json")) for change in p.changes
    ]
    for c in p.candidates:
        if c.enters_graph and c.result is not None:
            payload = EdgeStatusPayload(edge=c.edge.id, old_status=None, new_status=c.edge.status, result=c.result)
            events.append((EventType.EDGE_STATUS, payload.model_dump(mode="json")))
    return events
