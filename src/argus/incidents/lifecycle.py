"""Incident lifecycle: one problem, one incident, no alert spam.

* Fingerprint = (root node, root segment, direction). A repeat firing updates the open incident.
* Symptom alerts are silenced while their cause is open: the incident's `symptoms` are the root node and
  every node whose formula contains it (payment_success_rate -> cvr, orders, gmv), plus the trigger node.
* States: open -> investigating -> explained -> monitoring -> resolved. The root segment is monitored every
  hour; 3 consecutive normal hours resolve the incident. It reopens if it fires again within 24 h.
* Severity = cumulative EUR impact against the expectation, not z.
* DATA_ISSUE and EXPECTED findings never open an incident; they become notes ("didn't wake you").
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from argus.contracts.findings import (
    Anomaly,
    Findings,
    Incident,
    IncidentState,
    IncidentTransition,
    Note,
    Quantity,
    Segment,
    Verdict,
)
from argus.contracts.graph import Graph, NodeKind
from argus.decompose.segments import Cell
from argus.graph.store import product_factors
from argus.semantic.compile import hourly_sql, points_condition
from argus.semantic.runner import Runner

HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)
REOPEN_WITHIN = timedelta(hours=24)
CALM_Z = 2.0
CALM_HOURS = 3
# A ratio of amounts (pacing = spend / planned spend, around 1) has no count model: `Cell.z` gives it a
# Poisson-style variance on EUR amounts, or a binomial one whenever it dips just below 1, both far below how
# much a healthy hour moves (up to about 10% for pacing), and a huge one when the spend is zero. The calm test
# uses a relative noise scale instead; without it a recovered pacing ratio never stays calm long enough to resolve.
RATIO_NOISE = 0.06


def fingerprint(node: str, segment: Segment, direction: str) -> str:
    key = f"{node}|{','.join(f'{k}={v}' for k, v in sorted(segment.items()))}|{direction}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def calm_z(cell: Cell, share: bool) -> float:
    """z for the calm test: `Cell.z` for counts and shares; a ratio of amounts is scaled by `RATIO_NOISE`."""
    if share or not cell.is_ratio or not cell.cur_den or not cell.base_den or not cell.base:
        return cell.z
    p0, p1 = cell.base / cell.base_den, cell.cur / cell.cur_den
    return (p1 - p0) / (RATIO_NOISE * abs(p0))


def symptoms_of(graph: Graph, root: str) -> list[str]:
    out = {root}
    for node in graph.nodes:
        factors = product_factors(graph, node.id) or []
        if root in factors:
            out.add(node.id)
    return sorted(out)


@dataclass
class _Monitor:
    calm: int = 0
    aov: float = 0.0
    last_hour: datetime | None = None


@dataclass
class IncidentBook:
    graph: Graph
    incidents: dict[str, Incident] = field(default_factory=dict)
    notes: list[Note] = field(default_factory=list)
    _monitors: dict[str, _Monitor] = field(default_factory=dict)

    # ------------------------------------------------------------------ queries
    def open_incidents(self) -> list[Incident]:
        return [i for i in self.incidents.values() if i.state is not IncidentState.RESOLVED]

    def covering(self, node: str, direction: str) -> Incident | None:
        for inc in self.open_incidents():
            if node in inc.symptoms and inc.direction == direction:
                return inc
        return None

    def add_note(self, **fields: object) -> Note:
        note = Note(id=f"note_{len(self.notes) + 1:04d}", **fields)  # type: ignore[arg-type]
        self.notes.append(note)
        return note

    # ------------------------------------------------------------------ updates
    def suppress(self, anomaly: Anomaly, incident: Incident, as_of: datetime) -> Note:
        incident.anomalies.append(anomaly.id)
        incident.updated_at = anomaly.hour
        return self.add_note(
            kind="suppressed",
            sim_ts=as_of,
            node=anomaly.node,
            segment=anomaly.segment,
            reason=f"{anomaly.node} {anomaly.direction} is a symptom of {incident.id} ({incident.title}); not paged",
            numbers=[Quantity(value=anomaly.z, unit="z", receipt=anomaly.receipts[0] if anomaly.receipts else None)],
            receipts=anomaly.receipts,
        )

    def record(self, findings: Findings, anomaly: Anomaly, as_of: datetime) -> tuple[Incident | None, str]:
        """File the findings of an investigation. Returns (incident or None, change)."""
        if findings.verdict in (Verdict.DATA_ISSUE, Verdict.EXPECTED):
            self.add_note(
                kind="data_issue" if findings.verdict is Verdict.DATA_ISSUE else "expected",
                sim_ts=as_of,
                node=anomaly.node,
                segment=anomaly.segment,
                reason=findings.headline,
                numbers=[findings.observed.change_pct],
                receipts=[r for s in findings.trail for r in s.receipts],
            )
            return None, "note"
        root = findings.root
        node, segment = (root.node, root.segment) if root else (anomaly.node, anomaly.segment)
        fp = fingerprint(node, segment, anomaly.direction)
        hour = anomaly.hour
        for inc in self.incidents.values():
            if inc.fingerprint != fp:
                continue
            if inc.state is not IncidentState.RESOLVED:
                inc.anomalies.append(anomaly.id)
                inc.updated_at = hour
                if anomaly.node not in inc.symptoms:
                    inc.symptoms.append(anomaly.node)
                if inc.verdict is Verdict.HYPOTHESIS and findings.verdict is Verdict.SUPPORTED_CAUSE:
                    inc.findings = findings.model_copy(update={"incident_id": inc.id})
                    inc.verdict = findings.verdict
                    inc.title = findings.headline
                return inc, "updated"
            if inc.resolved_at is not None and hour - inc.resolved_at <= REOPEN_WITHIN:
                inc.reopened += 1
                inc.anomalies.append(anomaly.id)
                inc.resolved_at = None
                inc.updated_at = hour
                self._move(inc, IncidentState.OPEN, hour, f"fired again within 24 h ({anomaly.id})")
                self._move(inc, IncidentState.EXPLAINED, hour, "same fingerprint as before")
                self._monitors[inc.id] = _Monitor(aov=self._monitors.get(inc.id, _Monitor()).aov)
                return inc, "reopened"
        inc = Incident(
            id=f"INC-{len(self.incidents) + 1:04d}",
            fingerprint=fp,
            title=findings.headline,
            verdict=findings.verdict,
            state=IncidentState.OPEN,
            root_node=node,
            segment=segment,
            direction=anomaly.direction,
            severity_eur=abs(findings.impact.eur_so_far.value) if findings.impact else 0.0,
            opened_at=hour,
            updated_at=hour,
            anomalies=[anomaly.id],
            symptoms=sorted(set(symptoms_of(self.graph, node)) | {anomaly.node}),
            findings=findings,
        )
        inc.findings = findings.model_copy(update={"incident_id": inc.id})
        inc.history.append(
            IncidentTransition(sim_ts=hour, from_state=None, to_state=IncidentState.OPEN, reason=anomaly.id)
        )
        self._move(inc, IncidentState.INVESTIGATING, hour, "fixed opening started")
        if findings.verdict in (Verdict.SUPPORTED_CAUSE, Verdict.HYPOTHESIS):
            self._move(inc, IncidentState.EXPLAINED, hour, findings.verdict.value)
        self.incidents[inc.id] = inc
        aov = 0.0
        if findings.impact and findings.impact.per_hour.value:
            aov = findings.impact.gmv_eur_per_hour.value / findings.impact.per_hour.value
        self._monitors[inc.id] = _Monitor(aov=aov, last_hour=hour)
        return inc, "opened"

    def monitor(
        self, runner: Runner, hour: datetime, as_of: datetime, calm_hours: int = CALM_HOURS
    ) -> list[tuple[Incident, str]]:
        """Advance the lifecycle of every open incident from its root segment's value this hour."""
        changes = []
        for inc in self.open_incidents():
            mon = self._monitors.setdefault(inc.id, _Monitor())
            if mon.last_hour is not None and hour <= mon.last_hour:
                continue
            mon.last_hour = hour
            cell = self._root_cell(runner, inc, hour, as_of)
            if cell is None:
                continue
            z = calm_z(cell, self.graph.node(inc.root_node).unit == "share")
            if abs(z) < CALM_Z:
                mon.calm += 1
            else:
                mon.calm = 0
                inc.severity_eur = round(inc.severity_eur + abs(cell.deviation) * mon.aov, 2)
            reason = f"root segment z {z:+.1f} at {hour:%Y-%m-%d %H:%M}"
            if inc.state is IncidentState.EXPLAINED and 1 <= mon.calm < calm_hours:
                self._move(inc, IncidentState.MONITORING, hour, reason)
                changes.append((inc, "state"))
            elif inc.state is IncidentState.MONITORING and mon.calm == 0:
                self._move(inc, IncidentState.EXPLAINED, hour, reason)
                changes.append((inc, "state"))
            elif inc.state in (IncidentState.EXPLAINED, IncidentState.MONITORING) and mon.calm >= calm_hours:
                inc.resolved_at = hour
                self._move(inc, IncidentState.RESOLVED, hour, f"{calm_hours} consecutive normal hours")
                changes.append((inc, "state"))
            inc.updated_at = hour
        return changes

    def _root_cell(self, runner: Runner, inc: Incident, hour: datetime, as_of: datetime) -> Cell | None:
        node = self.graph.node(inc.root_node)
        hours = [hour - k * WEEK for k in range(0, 5)]
        rows = runner.fetch(hourly_sql(self.graph, inc.root_node, points_condition(hours), inc.segment), as_of)
        by_ts = {r["ts"]: r for r in rows}
        if hour not in by_ts or any(h not in by_ts for h in hours[1:]):
            return None
        cur, base = by_ts[hour], [by_ts[h] for h in hours[1:]]
        if node.kind is NodeKind.RATIO:
            return Cell(
                "h",
                float(cur["num"] or 0),
                sum(float(b["num"] or 0) for b in base) / 4,
                float(cur["den"] or 0),
                sum(float(b["den"] or 0) for b in base) / 4,
            )
        return Cell("h", float(cur["value"] or 0), sum(float(b["value"] or 0) for b in base) / 4)

    @staticmethod
    def _move(inc: Incident, state: IncidentState, ts: datetime, reason: str) -> None:
        inc.history.append(IncidentTransition(sim_ts=ts, from_state=inc.state, to_state=state, reason=reason))
        inc.state = state
