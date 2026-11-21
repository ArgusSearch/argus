"""The recorded S1 run in fixtures/ replays as a valid C5 stream, and replay never shows the future."""

from __future__ import annotations

from argus.api.recording import FIXTURES, load_recording
from argus.contracts.events import EventType, InvestigationStepPayload
from argus.contracts.findings import IncidentState, Verdict


def test_fixtures_load_as_a_valid_recording() -> None:
    rec = load_recording(FIXTURES)
    types = {e.type for e in rec.events}
    assert {EventType.TICK, EventType.EDGE_STATUS, EventType.ANOMALY_OPENED, EventType.INVESTIGATION_STEP} <= types
    assert EventType.INCIDENT_UPDATED in types
    assert rec.manifest["world_start"] and rec.graph.nodes and rec.receipts
    assert load_recording(FIXTURES / "events.jsonl").events == rec.events


def test_every_referenced_receipt_exists() -> None:
    rec = load_recording(FIXTURES)
    known = {r.id for r in rec.receipts}
    for event in rec.events:
        if event.type is EventType.INVESTIGATION_STEP:
            step = InvestigationStepPayload.model_validate(event.payload).step
            assert set(step.receipts) <= known, step
    for snap in rec.incidents:
        f = snap.incident.findings
        quantities = [f.observed.observed, f.observed.expected, f.observed.change_pct]
        if f.impact:
            quantities += [f.impact.per_hour, f.impact.gmv_eur_per_hour]
        assert {q.receipt for q in quantities if q.receipt} <= known


def test_s1_story_in_snapshots() -> None:
    rec = load_recording(FIXTURES)
    assert [s.incident.state for s in rec.incidents] == [
        IncidentState.EXPLAINED,
        IncidentState.MONITORING,
        IncidentState.RESOLVED,
    ]
    final = rec.incidents[-1].incident
    assert final.verdict is Verdict.SUPPORTED_CAUSE
    assert final.findings.root and final.findings.root.evidence
    assert final.findings.root.evidence.ref == "ps_payco_degraded"


def test_snapshots_never_lead_the_stream() -> None:
    """Each snapshot is cut back to its event: history up to that hour, only the steps published so far."""
    rec = load_recording(FIXTURES)
    events = {e.seq: e for e in rec.events}
    for snap in rec.incidents:
        event = events[snap.seq]
        assert event.type is EventType.INCIDENT_UPDATED
        assert snap.incident.state.value == event.payload["state"]
        assert snap.incident.history[-1].to_state is snap.incident.state
        published = sum(1 for e in rec.events if e.type is EventType.INVESTIGATION_STEP and e.seq <= snap.seq)
        assert len(snap.incident.findings.trail) <= published
        if snap.incident.state is not IncidentState.RESOLVED:
            assert snap.incident.resolved_at is None
