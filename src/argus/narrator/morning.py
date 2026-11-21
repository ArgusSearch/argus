"""Build the morning report from the published run and its visible findings."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from argus.contracts.events import Event, EventType, IncidentUpdatedPayload, InvestigationStepPayload
from argus.contracts.findings import Anomaly, Findings, Incident, Note, TrailStep, Verdict
from argus.contracts.graph import Graph
from argus.narrator.playbooks import PlaybookRun, map_playbook
from argus.narrator.run_queries import Activity, ReceiptLink, RunWindow, measure_activity

Section = Literal["happened", "decided", "asks"]


class ReportLine(BaseModel):
    id: str
    section: Section
    text: str
    incident_id: str | None = None
    note_id: str | None = None
    receipts: list[ReceiptLink] = Field(min_length=1)


class MorningReport(BaseModel):
    title: Literal["While you slept"] = "While you slept"
    stream: str
    through_seq: int
    activity: Activity
    activity_receipt: ReceiptLink
    lines: list[ReportLine]
    investigations: list[PlaybookRun]
    markdown: str


_NOTE_LABEL = {
    "expected": "Expected change",
    "data_issue": "Data issue",
    "suppressed": "Suppressed alert",
}


def _count(number: int, unit: str) -> str:
    return f"{number:,} {unit}" + ("s" if number != 1 else "")


def _markdown(lines: list[ReportLine]) -> str:
    output = ["# While you slept"]
    for section, label in (
        ("happened", "What happened"),
        ("decided", "What Argus decided"),
        ("asks", "Human approval and review"),
    ):
        body = []
        for line in lines:
            if line.section == section:
                text = re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", " ".join(line.text.split()))
                links = " ".join(f"[{ref.id}]({ref.href})" for ref in line.receipts)
                body.append(f"- {text} {links}")
        if body:
            output += ["", f"## {label}", "", *body]
    return "\n".join(output) + "\n"


def _note_line(
    window: RunWindow, event: Event, tick: Event | None, semantic: Callable[..., list[ReceiptLink]]
) -> ReportLine:
    note = Note.model_validate(event.payload)
    event_links = [window.event_link(event)]
    if note.kind == "data_issue" and tick is not None:
        event_links.append(window.event_link(tick))
    return ReportLine(
        id=f"note:{note.id}",
        note_id=note.id,
        section="decided",
        text=f"{_NOTE_LABEL[note.kind]} - {note.reason}",
        receipts=event_links + semantic(*note.receipts, *(number.receipt for number in note.numbers)),
    )


def _incident_lines(
    window: RunWindow,
    event: Event,
    findings: Findings | None,
    verdict_event: Event | None,
    semantic: Callable[..., list[ReceiptLink]],
) -> list[ReportLine]:
    update = IncidentUpdatedPayload.model_validate(event.payload)

    def line(what: str, section: Section, text: str, links: list[ReceiptLink]) -> ReportLine:
        return ReportLine(id=f"{update.id}:{what}", incident_id=update.id, section=section, text=text, receipts=links)

    decision = [window.event_link(event)]
    if verdict_event is not None:
        decision.append(window.event_link(verdict_event))
    evidence = list(decision)
    finding_link = window.link(f"findings-{event.seq}")
    if findings:
        evidence.append(finding_link)
        change = findings.root.change_pct if findings.root else findings.observed.change_pct
        evidence += semantic(change.receipt)
        if findings.root and findings.root.evidence:
            evidence += semantic(*(rid for step in findings.trail if step.kind == "events" for rid in step.receipts))
    result = [
        line(
            "verdict",
            "decided",
            f"{update.id} · {update.verdict.value} · {update.state.value} - {update.title}",
            evidence,
        )
    ]
    if findings:
        observed = findings.observed
        base_receipts = (observed.observed.receipt, observed.expected.receipt)
        links = semantic(*base_receipts, observed.change_pct.receipt)
        if set(base_receipts) <= {ref.id for ref in links}:
            result.append(
                line(
                    "observed",
                    "happened",
                    f"{observed.node} moved {observed.change_pct.value:+.2f}% against its expectation "
                    f"({observed.observed.value:,.6g} observed, {observed.expected.value:,.6g} expected).",
                    [*links, finding_link],
                )
            )
        impact = findings.impact
        if impact and (
            links := semantic(impact.eur_so_far.receipt, impact.gmv_eur_per_hour.receipt, impact.per_hour.receipt)
        ):
            label = "GMV" if impact.node == "orders" else impact.node.replace("_", " ")
            result.append(
                line(
                    "impact",
                    "happened",
                    f"Estimated {label} change during the investigation window (EUR {impact.eur_so_far.value:+,.0f}).",
                    [*links, finding_link],
                )
            )
        result.append(
            line(
                "remainder",
                "decided",
                f"{findings.unexplained_share:.1%} of the deviation remains unexplained.",
                [finding_link],
            )
        )
        if findings.uncertain and update.verdict is Verdict.SUPPORTED_CAUSE:
            result.append(
                line("uncertainty", "decided", f"Still uncertain - {' '.join(findings.uncertain)}", [finding_link])
            )
        for index, hypothesis in enumerate(findings.ruled_out):
            if hypothesis.result == "refuted" and (links := semantic(*hypothesis.receipts)):
                result.append(
                    line(
                        "refuted-" + str(index + 1),
                        "decided",
                        f"Ruled out {hypothesis.hypothesis} - {hypothesis.reason}",
                        [*links, finding_link],
                    )
                )
        if findings.suggested_action and findings.suggested_action.needs_approval:
            result.append(
                line(
                    "approval",
                    "asks",
                    f"{findings.suggested_action.text} (Human approval required.)",
                    [finding_link, *decision],
                )
            )

    if update.verdict in (Verdict.HYPOTHESIS, Verdict.UNEXPLAINED):
        uncertainty = " ".join(findings.uncertain) if findings else ""
        text = f"Further evidence needed for {update.id} ({update.verdict.value})."
        result.append(line("review", "asks", f"{text} {uncertainty}".strip(), evidence))
    return result


def build_morning_report(
    window: RunWindow,
    incidents: Sequence[Incident],
    graph: Graph,
    has_receipt: Callable[[str], bool],
) -> tuple[MorningReport, dict[int, Findings]]:
    """Produce deterministic prose and evidence links without provider calls."""
    activity = measure_activity(window)
    activity_receipt = window.link("activity")
    lines = [
        ReportLine(
            id="watched",
            section="happened",
            text=(
                f"Monitored {_count(activity.ticks, 'hour')} and scored {_count(activity.series_hours, 'metric-hour')}."
            ),
            receipts=[activity_receipt],
        ),
        ReportLine(
            id="activity",
            section="decided",
            text=(
                f"Opened {_count(activity.anomalies, 'anomaly check')}, "
                f"completed {_count(activity.investigations, 'investigation')}, and recorded "
                f"{_count(activity.incidents, 'incident')} ({activity.resolved_incidents:,} resolved)."
            ),
            receipts=[activity_receipt],
        ),
    ]

    def semantic(*ids: str | None) -> list[ReceiptLink]:
        return [window.semantic_link(rid) for rid in dict.fromkeys(ids) if rid and has_receipt(rid)]

    incidents_by_id = {incident.id: incident for incident in incidents}
    anomalies: dict[str, Anomaly] = {}
    trails: dict[str, list[TrailStep]] = defaultdict(list)
    verdicts: dict[str, Event] = {}
    latest: dict[str, Event] = {}
    notes: list[Event] = []
    ticks: dict[datetime, Event] = {}
    incident_ids: dict[str, str] = {}
    for event in window.events:
        match event.type:
            case EventType.ANOMALY_OPENED:
                opened = Anomaly.model_validate(event.payload)
                anomalies[opened.id] = opened
            case EventType.INVESTIGATION_STEP:
                stage = InvestigationStepPayload.model_validate(event.payload)
                if stage.incident_id is not None:
                    incident_ids[stage.anomaly_id] = stage.incident_id
                prior = trails[stage.anomaly_id]
                if prior and stage.step.step <= prior[-1].step:
                    # A failed investigation can restart with the Stage-1 fallback.
                    prior.clear()
                    verdicts.pop(stage.anomaly_id, None)
                prior.append(stage.step)
                if stage.step.kind == "verdict":
                    verdicts[stage.anomaly_id] = event
            case EventType.INCIDENT_UPDATED:
                latest[event.payload["id"]] = event
            case EventType.NOTE_LOGGED:
                notes.append(event)
            case EventType.TICK:
                ticks[event.sim_ts] = event

    published_findings: dict[int, Findings] = {}
    for incident_id, event in latest.items():
        incident = incidents_by_id.get(incident_id)
        findings = incident.findings if incident else None
        if findings and (findings.as_of > event.sim_ts or findings.verdict != event.payload["verdict"]):
            # A legacy recording can have only the final version of its findings.
            findings = None
        anomaly_id = findings.anomaly_id if findings else None
        lines.extend(
            _incident_lines(window, event, findings, verdicts.get(anomaly_id) if anomaly_id else None, semantic)
        )
        if incident is not None and findings is not None:
            published_findings[event.seq] = findings
            for linked in (*incident.anomalies, findings.anomaly_id):
                incident_ids[linked] = incident_id
            trails.setdefault(findings.anomaly_id, findings.trail)
    lines.extend(_note_line(window, event, ticks.get(event.sim_ts), semantic) for event in notes)

    investigations = []
    for anomaly_id, trail in trails.items():
        linked_incident_id = incident_ids.get(anomaly_id)
        anomaly = anomalies.get(anomaly_id)
        incident = incidents_by_id.get(linked_incident_id) if linked_incident_id else None
        if anomaly is not None:
            node, direction = anomaly.node, anomaly.direction
        elif incident is not None:
            node, direction = incident.findings.observed.node, incident.direction
        else:
            continue
        if run := map_playbook(graph, node, direction, anomaly_id, linked_incident_id, trail):
            investigations.append(run)

    return (
        MorningReport(
            stream=window.stream,
            through_seq=window.through_seq,
            activity=activity,
            activity_receipt=activity_receipt,
            lines=lines,
            investigations=investigations,
            markdown=_markdown(lines),
        ),
        published_findings,
    )
