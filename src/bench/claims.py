"""Normalise an agent's output into claims: one per incident or note, in the shape the grader compares.

A claim says: at `detected_at` (sim time), node X in segment S has verdict V, with this evidence and
these ruled-out alternatives. Incidents are pages unless their verdict says nothing is broken
(EXPECTED) or only the data is (DATA_ISSUE). Notes never page.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from argus.contracts.events import EventType, IncidentUpdatedPayload
from argus.contracts.findings import Incident, Note, Verdict
from bench.agents import AgentOutput

BUSINESS_VERDICTS = frozenset({Verdict.SUPPORTED_CAUSE, Verdict.HYPOTHESIS, Verdict.UNEXPLAINED})
NOTE_VERDICT = {"expected": Verdict.EXPECTED, "data_issue": Verdict.DATA_ISSUE}


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["incident", "note"]
    id: str
    verdict: Verdict
    node: str | None
    segment: dict[str, str] = Field(default_factory=dict)
    detected_at: datetime = Field(description="sim time (as_of) the claim was first made")
    evidence: list[str] = Field(default_factory=list, description="log ids cited as the first cause")
    ruled_out: list[str] = Field(default_factory=list, description="log ids refuted as the cause")
    text: str = Field(default="", description="headline or reason, searched for log ids as a fallback")

    @property
    def is_page(self) -> bool:
        """A page wakes a human about the business: an incident whose verdict says something is wrong."""
        return self.source == "incident" and self.verdict in BUSINESS_VERDICTS


def _from_incident(inc: Incident, anomaly_seen: dict[str, datetime]) -> Claim:
    seen = [t.sim_ts for t in inc.history] + [anomaly_seen[a] for a in inc.anomalies if a in anomaly_seen]
    f = inc.findings
    evidence = [f.root.evidence.ref] if f.root is not None and f.root.evidence is not None else []
    ruled_out = [r.evidence.ref for r in f.ruled_out if r.result == "refuted" and r.evidence is not None]
    return Claim(
        source="incident",
        id=inc.id,
        verdict=inc.verdict,
        node=inc.root_node,
        segment=dict(inc.segment),
        detected_at=min(seen) if seen else inc.opened_at,
        evidence=evidence,
        ruled_out=ruled_out,
        text=" ".join([inc.title, f.headline, *(r.hypothesis for r in f.ruled_out)]),
    )


def _from_note(note: Note) -> Claim | None:
    verdict = NOTE_VERDICT.get(note.kind)
    if verdict is None:  # "suppressed": a symptom silenced by an open incident, not a claim of its own
        return None
    return Claim(
        source="note",
        id=note.id,
        verdict=verdict,
        node=note.node,
        segment=dict(note.segment),
        detected_at=note.sim_ts,
        text=note.reason,
    )


def _from_events(output: AgentOutput) -> tuple[list[Claim], list[Note]]:
    """Fallback for agents that only emit the C5 stream: incidents from `incident_updated` summaries."""
    first: dict[str, datetime] = {}
    last: dict[str, IncidentUpdatedPayload] = {}
    notes: list[Note] = []
    for event in sorted(output.events, key=lambda e: e.seq):
        if event.type == EventType.INCIDENT_UPDATED:
            payload = IncidentUpdatedPayload.model_validate(event.payload)
            first.setdefault(payload.id, event.sim_ts)
            last[payload.id] = payload
        elif event.type == EventType.NOTE_LOGGED:
            notes.append(Note.model_validate(event.payload))
    claims = [
        Claim(
            source="incident",
            id=p.id,
            verdict=p.verdict,
            node=p.root_node,
            segment=dict(p.segment),
            detected_at=first[p.id],
            text=f"{p.title} {p.reason}",
        )
        for p in last.values()
    ]
    return claims, notes


def claims_from_output(output: AgentOutput) -> list[Claim]:
    anomaly_seen = {a.id: a.detected_at for a in output.anomalies}
    if output.incidents:
        claims = [_from_incident(i, anomaly_seen) for i in output.incidents]
        notes = list(output.notes)
    else:
        claims, event_notes = _from_events(output)
        notes = list(output.notes) or event_notes
    claims += [c for c in (_from_note(n) for n in notes) if c is not None]
    return sorted(claims, key=lambda c: (c.detected_at, c.id))
