"""Claim normalisation: incidents, notes and the C5 fallback become the same comparable claims."""

from __future__ import annotations

from datetime import datetime, timedelta

from argus.contracts.events import Event, IncidentUpdatedPayload
from argus.contracts.findings import (
    Anomaly,
    Cost,
    EvidenceRef,
    Findings,
    Incident,
    IncidentState,
    IncidentTransition,
    Note,
    ObservedChange,
    Quantity,
    RootCause,
    RuledOut,
    Verdict,
    Window,
)
from bench.agents import AgentOutput
from bench.claims import claims_from_output

HOUR = datetime(2026, 11, 20, 14)
AS_OF = HOUR + timedelta(hours=2)
Q = Quantity(value=1.0, unit="count", receipt=None)


def _ref(log_id: str) -> EvidenceRef:
    return EvidenceRef(log="log_events", ref=log_id, ts=HOUR, kind="x", description=log_id)


def _incident() -> Incident:
    findings = Findings(
        anomaly_id="an_1",
        verdict=Verdict.SUPPORTED_CAUSE,
        headline="PayCo degraded",
        as_of=AS_OF,
        window=Window(start=HOUR, end=HOUR),
        observed=ObservedChange(node="payment_success_rate", segment={}, observed=Q, expected=Q, change_pct=Q),
        root=RootCause(node="payment_success_rate", segment={}, direction="down", evidence=_ref("ps_1"), change_pct=Q),
        ruled_out=[
            RuledOut(hypothesis="release", prediction="p", result="refuted", reason="r", evidence=_ref("dep_1")),
            RuledOut(hypothesis="maybe", prediction="p", result="inconclusive", reason="r", evidence=_ref("dep_2")),
        ],
        explained_share=1.0,
        unexplained_share=0.0,
        cost=Cost(queries=1, seconds=0.1),
    )
    return Incident(
        id="INC-1",
        fingerprint="f",
        title="t",
        verdict=Verdict.SUPPORTED_CAUSE,
        state=IncidentState.EXPLAINED,
        root_node="payment_success_rate",
        segment={"country": "DE"},
        direction="down",
        severity_eur=1.0,
        opened_at=HOUR,
        updated_at=AS_OF,
        anomalies=["an_1"],
        # A runtime may stamp the opening with the data hour; the anomaly's detected_at is the real as_of.
        history=[IncidentTransition(sim_ts=HOUR, from_state=None, to_state=IncidentState.OPEN, reason="an_1")],
        findings=findings,
    )


def _anomaly() -> Anomaly:
    return Anomaly(
        id="an_1",
        node="payment_success_rate",
        direction="down",
        hour=HOUR,
        detected_at=AS_OF,
        onset=HOUR,
        observed=0.9,
        expected=0.95,
        band=(0.94, 0.96),
        z=-6.0,
        rule="z_gt_open",
    )


def test_incident_claim_uses_anomaly_detection_time_and_refuted_evidence():
    claims = claims_from_output(AgentOutput(incidents=[_incident()], anomalies=[_anomaly()]))
    (c,) = claims
    assert c.is_page and c.detected_at == AS_OF and c.segment == {"country": "DE"}
    assert c.evidence == ["ps_1"] and c.ruled_out == ["dep_1"], "inconclusive alternatives are not ruled out"
    without_anomalies = claims_from_output(AgentOutput(incidents=[_incident()]))
    assert without_anomalies[0].detected_at == HOUR, "falls back to the incident history"


def test_notes_map_to_verdicts_and_suppressed_notes_are_dropped():
    notes = [
        Note(id="n1", kind="expected", sim_ts=AS_OF, node="ad_spend", reason="planned"),
        Note(id="n2", kind="data_issue", sim_ts=AS_OF, reason="late"),
        Note(id="n3", kind="suppressed", sim_ts=AS_OF, reason="symptom of INC-1"),
    ]
    claims = claims_from_output(AgentOutput(notes=notes))
    assert [(c.id, c.verdict) for c in claims] == [("n1", Verdict.EXPECTED), ("n2", Verdict.DATA_ISSUE)]
    assert not any(c.is_page for c in claims)


def test_event_stream_fallback():
    def updated(seq: int, at: datetime, verdict: Verdict) -> Event:
        payload = IncidentUpdatedPayload(
            id="INC-7",
            title="t",
            state=IncidentState.OPEN,
            verdict=verdict,
            root_node="orders",
            segment={},
            direction="down",
            severity_eur=0.0,
            change="opened" if seq == 1 else "updated",
        )
        return Event.make(seq, at, payload)

    note = Note(id="n1", kind="data_issue", sim_ts=AS_OF, reason="late")
    events = [
        updated(1, AS_OF, Verdict.UNEXPLAINED),
        Event.make(2, AS_OF, note),
        updated(3, AS_OF + timedelta(hours=1), Verdict.SUPPORTED_CAUSE),
    ]
    claims = claims_from_output(AgentOutput(events=events))
    inc = next(c for c in claims if c.source == "incident")
    assert inc.detected_at == AS_OF and inc.verdict == Verdict.SUPPORTED_CAUSE, "first seen, final verdict"
    assert [c.id for c in claims if c.source == "note"] == ["n1"]
