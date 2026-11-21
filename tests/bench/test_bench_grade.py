"""Unit tests for the grader, the sealed envelope and pass^k (no worlds generated)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from argus.contracts.findings import Verdict
from bench.claims import Claim
from bench.grade import WorldWindow, grade_run
from bench.scorecard import pass_hat_k
from bench.sealed import bench_commitment, commitment_of, verify

WINDOW = WorldWindow(live_start=datetime(2026, 11, 18), world_end=datetime(2026, 11, 23), delivery_lag_hours=2)
T0 = datetime(2026, 11, 20, 14)
S1_SEG = {"country": "DE", "platform": "android", "provider": "PayCo"}


def _fault() -> dict:
    return {
        "event_id": "s1_payco_outage",
        "kind": "fault",
        "start_ts": T0,
        "end_ts": T0 + timedelta(hours=8),
        "root_node": "payment_success_rate",
        "segment": dict(S1_SEG),
        "expected": {
            "verdict": "SUPPORTED_CAUSE",
            "root_node": "payment_success_rate",
            "segment": dict(S1_SEG),
            "evidence": "ps_payco_degraded",
            "ruled_out": ["dep_android-app_8.3.0"],
        },
    }


def _innocent() -> dict:
    seg = {"advertiser_id": "adv_05", "country": "FR"}
    return {
        "event_id": "s2_planned_budget_increase",
        "kind": "innocent",
        "start_ts": T0,
        "end_ts": None,
        "root_node": "ad_spend",
        "segment": seg,
        "expected": {
            "verdict": "EXPECTED",
            "root_node": "ad_spend",
            "segment": seg,
            "evidence": "bud_adv_05_FR_increase",
            "evidence_any": ["bud_adv_05_FR_increase", "cal_adv_05_FR_push"],
            "affected_nodes": ["ad_spend", "ad_clicks"],
        },
    }


def _data() -> dict:
    return {
        "event_id": "s3_orders_loader_stall",
        "kind": "data",
        "start_ts": T0,
        "end_ts": T0 + timedelta(hours=3),
        "root_node": "orders",
        "segment": {},
        "expected": {"verdict": "DATA_ISSUE", "root_node": "orders", "affected_nodes": ["orders", "gmv"]},
    }


def _claim(verdict: Verdict, node: str | None, segment: dict, hours: float = 2, **kw) -> Claim:
    source = kw.pop("source", "incident")
    return Claim(
        source=source,
        id=kw.pop("id", f"{source}-{node}-{verdict.value}"),
        verdict=verdict,
        node=node,
        segment=segment,
        detected_at=T0 + timedelta(hours=hours),
        **kw,
    )


def _grade(truth: list[dict], claims: list[Claim]):
    return grade_run(
        truth, claims, WINDOW, case="c", scenario="s", seed=1, agent="a", commitment="sha256:x", verified=True
    )


@pytest.mark.parametrize(
    ("claim", "grade"),
    [
        (
            _claim(
                Verdict.SUPPORTED_CAUSE,
                "payment_success_rate",
                S1_SEG,
                evidence=["ps_payco_degraded"],
                ruled_out=["dep_android-app_8.3.0"],
            ),
            4,
        ),
        (_claim(Verdict.SUPPORTED_CAUSE, "payment_success_rate", S1_SEG, evidence=["ps_payco_degraded"]), 3),
        (
            _claim(
                Verdict.SUPPORTED_CAUSE,
                "payment_success_rate",
                {"country": "DE", "platform": "android"},
                evidence=["ps_payco_degraded"],
                ruled_out=["dep_android-app_8.3.0"],
            ),
            3,
        ),
        (_claim(Verdict.SUPPORTED_CAUSE, "payment_success_rate", {"country": "DE"}), 2),
        (_claim(Verdict.SUPPORTED_CAUSE, "cvr", {"country": "DE"}, text="PayCo degraded: ps_payco_degraded"), 2),
        (_claim(Verdict.SUPPORTED_CAUSE, "cvr", {"platform": "android"}), 0),
        (
            _claim(Verdict.SUPPORTED_CAUSE, "payment_success_rate", S1_SEG, evidence=["dep_android-app_8.3.0"]),
            0,
        ),
        (_claim(Verdict.UNEXPLAINED, "payment_success_rate", {}), 1),
        (_claim(Verdict.HYPOTHESIS, "payment_success_rate", S1_SEG), 1),
        (_claim(Verdict.EXPECTED, "payment_success_rate", S1_SEG, source="note"), 0),
    ],
)
def test_fault_levels(claim: Claim, grade: int):
    run = _grade([_fault()], [claim])
    assert run.events[0].grade == grade, run.events[0].label


def test_fault_missed_outside_window_or_segment():
    late = _claim(Verdict.SUPPORTED_CAUSE, "payment_success_rate", S1_SEG, hours=20)
    elsewhere = _claim(Verdict.SUPPORTED_CAUSE, "payment_success_rate", {"country": "FR"})
    run = _grade([_fault()], [late, elsewhere])
    assert run.events[0].grade == 0 and run.events[0].label == "missed"
    assert run.false_alarms == [late.id, elsewhere.id] and run.pages == 2 and not run.passed


def test_ttd_and_pass():
    exact = _claim(
        Verdict.SUPPORTED_CAUSE,
        "payment_success_rate",
        S1_SEG,
        hours=3,
        evidence=["ps_payco_degraded"],
        ruled_out=["dep_android-app_8.3.0"],
    )
    symptom = _claim(Verdict.UNEXPLAINED, "orders", {"country": "DE"}, hours=2, id="sym")
    run = _grade([_fault()], [exact, symptom])
    assert run.events[0].grade == 4 and run.events[0].ttd_hours == 2.0
    assert run.false_alarms == [] and run.true_pages == 2 and run.passed


def test_innocent_levels():
    seg = {"advertiser_id": "adv_05", "country": "FR"}
    note = _claim(Verdict.EXPECTED, "ad_spend", seg, source="note", text="planned: bud_adv_05_FR_increase")
    vague = _claim(Verdict.EXPECTED, "ad_spend", {"country": "FR"}, source="note")
    page = _claim(Verdict.UNEXPLAINED, "ad_spend", {"country": "FR"})
    other_node = _claim(Verdict.UNEXPLAINED, "sessions", {"country": "FR"})
    assert _grade([_innocent()], [note]).events[0].grade == 4
    assert _grade([_innocent()], [vague]).events[0].grade == 3
    assert _grade([_innocent()], []).events[0].grade == 2
    paged = _grade([_innocent()], [note, page])
    assert paged.events[0].grade == 0 and paged.false_alarms == [page.id]
    unrelated = _grade([_innocent()], [note, other_node])
    assert unrelated.events[0].grade == 4 and unrelated.false_alarms == [other_node.id], "not this event's fault"


def test_data_levels():
    flag = _claim(Verdict.DATA_ISSUE, "orders", {}, source="note")
    page = _claim(Verdict.UNEXPLAINED, "orders", {})
    stray = _claim(Verdict.DATA_ISSUE, "ad_spend", {}, source="note", id="stray")
    run = _grade([_data()], [flag, stray])
    assert run.events[0].grade == 4 and run.data_claims == 2 and run.true_data_claims == 1
    assert _grade([_data()], [flag, page]).events[0].grade == 1
    assert _grade([_data()], [page]).events[0].grade == 0
    assert _grade([_data()], []).events[0].label == "missed"


def test_quiet_world_passes_only_without_pages():
    assert _grade([], []).passed
    noise = _grade([], [_claim(Verdict.UNEXPLAINED, "sessions", {})])
    assert not noise.passed and len(noise.false_alarms) == 1
    assert _grade([], [_claim(Verdict.EXPECTED, "sessions", {}, source="note")]).passed, "notes never page"


def test_red_herrings_are_not_graded():
    herring = {**_fault(), "event_id": "herring", "kind": "red_herring", "expected": {}}
    assert _grade([herring], []).events == []


def test_commitment_roundtrip():
    c = commitment_of("abc", '{"x":1}')
    assert c.startswith("sha256:") and len(c) == 7 + 64
    assert verify(c, "abc", '{"x":1}')
    assert not verify(c, "abd", '{"x":1}') and not verify(c, "abc", '{"x":2}')
    assert bench_commitment({"a": "1", "b": "2"}) == bench_commitment({"b": "2", "a": "1"})


def test_pass_hat_k():
    assert pass_hat_k(3, 3, 3) == 1.0 and pass_hat_k(3, 2, 3) == 0.0
    assert pass_hat_k(4, 3, 2) == pytest.approx(0.5) and pass_hat_k(5, 5, 1) == 1.0
    with pytest.raises(ValueError):
        pass_hat_k(2, 2, 3)
