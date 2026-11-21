"""'While you slept': the run so far in a few honest lines, each with the receipts behind it.

Counts come from the event stream (ticks, notes, anomalies, edge tests); money and verdicts come from
the incidents' findings, which carry their receipts. A line without receipts says so: it is a count of
what the monitor did, not a number read from the data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from argus.api.state import ALARM_Z, WIGGLE_Z, RunState
from argus.contracts.findings import Incident, IncidentState
from argus.contracts.graph import EdgeKind, Graph

Tone = Literal["neutral", "good", "warn", "bad"]


class DigestLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    value: str
    detail: str
    receipts: list[str] = []
    tone: Tone = "neutral"


class Digest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    since: datetime | None
    until: datetime | None
    lines: list[DigestLine]
    markdown: str


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def segment_label(segment: dict[str, str]) -> str:
    order = ["country", "platform", "provider", "channel", "category", "advertiser_id"]
    keys = sorted(segment, key=lambda k: order.index(k) if k in order else len(order))
    return " · ".join(segment[k] for k in keys) or "all traffic"


def build_digest(state: RunState, incidents: list[Incident], graph: Graph) -> Digest:
    """Counts from the folded stream; incidents and the graph from the source (live or replay)."""
    with state.lock:  # one consistent read of the folded state
        first, last = state.first_tick, state.last_tick
        ticks, series_hours, wiggles = state.tick_count, state.series_hours, state.wiggles
        notes = list(state.notes)
        anomalies = list(state.anomalies.values())
    lines: list[DigestLine] = []
    since, until = (first.hour if first else None), (last.hour if last else None)
    nodes = len(last.scored_nodes) if last else 0
    lines.append(
        DigestLine(
            key="watched",
            label="Watched",
            value=f"{series_hours:,} series-hours",
            detail=f"{nodes} metrics every hour for {_plural(ticks, 'hour')}, with no one asking",
        )
    )
    noticed = [n for n in notes if n.kind == "suppressed" and n.node and "symptom" not in n.reason]
    lines.append(
        DigestLine(
            key="wiggles",
            label="Ignored",
            value=_plural(wiggles, "wiggle"),
            detail=(
                f"|z| between {WIGGLE_Z:.0f} and {ALARM_Z:.0f}, below the alarm line; "
                f"{len(noticed)} logged as noticed, not paged"
            ),
            receipts=[r for n in noticed for r in n.receipts],
            tone="good",
        )
    )
    expected = [n for n in notes if n.kind == "expected"]
    data_issues = [n for n in notes if n.kind == "data_issue"]
    held = expected + data_issues
    lines.append(
        DigestLine(
            key="held_back",
            label="Held back",
            value=_plural(len(held), "alert"),
            detail=(
                f"{_plural(len(expected), 'planned or harmless change')}, "
                f"{_plural(len(data_issues), 'late-data delay')}: didn't wake you"
            ),
            receipts=[r for n in held for r in n.receipts],
            tone="good",
        )
    )
    lines.append(
        DigestLine(
            key="anomalies",
            label="Opened",
            value=_plural(len(anomalies), "anomaly"),
            detail="; ".join(f"{a.node} |z| {abs(a.z):.1f} at {a.hour:%H:%M}" for a in anomalies) or "none",
            receipts=[r for a in anomalies for r in a.receipts],
            tone="bad" if anomalies else "good",
        )
    )
    for inc in sorted(incidents, key=lambda i: i.opened_at):
        f = inc.findings
        receipts = [
            q.receipt
            for q in (
                f.root.change_pct if f.root else None,
                *((f.impact.per_hour, f.impact.gmv_eur_per_hour) if f.impact else ()),
            )
            if q is not None and q.receipt
        ]
        state_text = {
            IncidentState.RESOLVED: f"resolved {inc.resolved_at:%H:%M}" if inc.resolved_at else "resolved",
            IncidentState.MONITORING: "back in band, monitoring",
        }.get(inc.state, inc.state.value)
        lines.append(
            DigestLine(
                key=f"incident:{inc.id}",
                label=inc.id,
                value=f"€{inc.severity_eur:,.0f}",
                detail=f"{f.verdict.value}: {inc.title} ({segment_label(inc.segment)}), {state_text}",
                receipts=list(dict.fromkeys(receipts)),
                tone="good" if inc.state is IncidentState.RESOLVED else "bad",
            )
        )
    symptoms = [n for n in notes if n.kind == "suppressed" and "symptom" in n.reason]
    if symptoms:
        lines.append(
            DigestLine(
                key="silenced",
                label="Silenced",
                value=_plural(len(symptoms), "symptom alert"),
                detail="one problem, one incident: downstream metrics folded into their root cause",
                receipts=[r for n in symptoms for r in n.receipts],
                tone="good",
            )
        )
    tested = [e for e in graph.edges if e.kind in (EdgeKind.FORMULA, EdgeKind.BREAKDOWN) and e.last_test]
    broken = [e for e in tested if e.last_test and e.last_test.passed is False]
    lines.append(
        DigestLine(
            key="edges",
            label="Graph",
            value=f"{len(tested) - len(broken)}/{len(tested)} edge tests pass",
            detail=", ".join(e.id for e in broken) + " broken" if broken else "every formula and breakdown holds",
            receipts=[r for e in tested[:3] if e.last_test for r in e.last_test.receipts[:1]],
            tone="bad" if broken else "good",
        )
    )
    queries = sum(i.findings.cost.queries for i in incidents)
    seconds = sum(i.findings.cost.seconds for i in incidents)
    llm = sum(i.findings.cost.llm_calls for i in incidents)
    lines.append(
        DigestLine(
            key="cost",
            label="Cost",
            value=f"{queries} queries",
            detail=f"{seconds:.2f} s of investigation, {_plural(llm, 'LLM call')}: the math decides, not a model",
        )
    )
    window = f"{since:%a %d %b %H:%M} to {until:%a %d %b %H:%M}" if since and until else "no data yet"
    title = f"While you slept ({window})"
    md = [f"## {title}", ""]
    md += [
        f"- **{line.label}: {line.value}**: {line.detail}" + "".join(f" [{r}]" for r in line.receipts[:4])
        for line in lines
    ]
    return Digest(title=title, since=since, until=until, lines=lines, markdown="\n".join(md) + "\n")
