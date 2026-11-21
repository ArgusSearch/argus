"""Incident lifecycle, symptom silencing, and the narrator's number check."""

from __future__ import annotations

from datetime import datetime, timedelta

from argus.contracts.findings import Anomaly, Cost, Findings, ObservedChange, Quantity, RootCause, Verdict, Window
from argus.contracts.graph import Graph
from argus.incidents.lifecycle import IncidentBook, fingerprint, symptoms_of
from argus.narrator.report import render, unbacked_numbers

T0 = datetime(2026, 11, 20, 21)


def _anomaly(aid: str, node: str, hour: datetime) -> Anomaly:
    return Anomaly(
        id=aid,
        node=node,
        direction="down",
        hour=hour,
        detected_at=hour + timedelta(hours=2),
        onset=hour,
        observed=0.92,
        expected=0.95,
        band=(0.94, 0.96),
        z=-8.0,
        rule="z_gt_open",
        receipts=["r1"],
    )


def _findings(anomaly: Anomaly, verdict: Verdict = Verdict.SUPPORTED_CAUSE) -> Findings:
    q = Quantity(value=-3.2, unit="pct", receipt="r1")
    return Findings(
        anomaly_id=anomaly.id,
        verdict=verdict,
        headline="Payment success rate down in DE / android / PayCo",
        as_of=anomaly.detected_at,
        window=Window(start=anomaly.onset, end=anomaly.hour),
        observed=ObservedChange(
            node=anomaly.node,
            segment={},
            observed=Quantity(value=0.92, unit="value", receipt="r1"),
            expected=Quantity(value=0.95, unit="value", receipt="r1"),
            change_pct=q,
        ),
        root=RootCause(
            node="payment_success_rate",
            segment={"country": "DE", "platform": "android", "provider": "PayCo"},
            direction="down",
            change_pct=Quantity(value=-34.6, unit="pct", receipt="r2"),
        ),
        explained_share=0.9,
        unexplained_share=0.1,
        cost=Cost(queries=3, seconds=0.01),
    )


def test_fingerprint_is_order_independent() -> None:
    a = fingerprint("n", {"country": "DE", "platform": "android"}, "down")
    b = fingerprint("n", {"platform": "android", "country": "DE"}, "down")
    assert a == b and a != fingerprint("n", {"country": "DE"}, "down")


def test_symptoms_include_the_formula_ancestors(graph: Graph) -> None:
    assert {"payment_success_rate", "cvr", "orders", "gmv"} <= set(symptoms_of(graph, "payment_success_rate"))


def test_one_problem_one_incident_symptoms_suppressed_and_reopen(graph: Graph) -> None:
    book = IncidentBook(graph)
    a1 = _anomaly("an_1", "payment_success_rate", T0)
    inc, change = book.record(_findings(a1), a1, a1.detected_at)
    assert inc is not None and change == "opened" and inc.state.value == "explained"
    # a downstream symptom while the cause is open is silenced, not paged
    covering = book.covering("cvr", "down")
    assert covering is inc
    note = book.suppress(_anomaly("an_2", "cvr", T0 + timedelta(hours=3)), inc, T0)
    assert note.kind == "suppressed" and len(book.incidents) == 1
    # the same root firing again updates, it does not open a second incident
    a3 = _anomaly("an_3", "payment_success_rate", T0 + timedelta(hours=4))
    again, change = book.record(_findings(a3), a3, a3.detected_at)
    assert again is inc and change == "updated" and len(book.incidents) == 1
    # resolved, then the same fingerprint within 24 h reopens the same incident
    inc.state = inc.state.__class__.RESOLVED
    inc.resolved_at = T0 + timedelta(hours=10)
    a4 = _anomaly("an_4", "payment_success_rate", T0 + timedelta(hours=20))
    reopened, change = book.record(_findings(a4), a4, a4.detected_at)
    assert reopened is inc and change == "reopened" and inc.reopened == 1 and len(book.incidents) == 1


def test_data_issue_never_opens_an_incident(graph: Graph) -> None:
    book = IncidentBook(graph)
    a = _anomaly("an_1", "orders", T0)
    inc, change = book.record(_findings(a, Verdict.DATA_ISSUE), a, a.detected_at)
    assert inc is None and change == "note" and book.notes[-1].kind == "data_issue"


def test_template_passes_the_number_check_and_an_invented_number_fails(graph: Graph) -> None:
    book = IncidentBook(graph)
    a = _anomaly("an_1", "payment_success_rate", T0)
    inc, _ = book.record(_findings(a), a, a.detected_at)
    assert inc is not None
    report = render(inc, graph)
    assert unbacked_numbers(report, inc.findings, extra=inc.model_dump(mode="json")) == []
    extra = inc.model_dump(mode="json")
    assert "-41.0" in unbacked_numbers(report.replace("-34.6%", "-41.0%"), inc.findings, extra=extra)
    assert "+34.6" in unbacked_numbers(report.replace("-34.6%", "+34.6%"), inc.findings, extra=extra)
