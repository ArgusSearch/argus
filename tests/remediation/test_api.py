"""Operator routes: only an operator session with its CSRF token decides; the answers follow the frozen contract."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from argus.agent.types import ProposalView
from argus.remediation import OperatorGate, create_router
from argus.remediation.api import COOKIE, CSRF_HEADER, is_local

from .conftest import context, evidence

Make = Callable[..., Any]


@pytest.fixture
def api(make_service: Make) -> tuple[TestClient, ProposalView, Any]:
    service, clock, _ = make_service()
    view = service.propose(context(datetime(2026, 11, 20, 2)), "INC-0001", "rollback_pacer", evidence())
    assert isinstance(view, ProposalView)
    app = FastAPI()
    app.include_router(create_router(service, OperatorGate(allow_client=lambda host: True)))
    return TestClient(app), view, clock


def session(client: TestClient) -> dict[str, str]:
    opened = client.post("/agent/operator/session")
    assert opened.status_code == 200 and opened.json()["principal"] == "operator"
    assert COOKIE in client.cookies
    return {CSRF_HEADER: opened.json()["csrf_token"]}


def body(view: ProposalView, key: str = "key-approve-01") -> dict[str, str]:
    return {"digest": view.digest, "idempotency_key": key}


def test_actions_are_listed_and_read(api: tuple[TestClient, ProposalView, Any]) -> None:
    client, view, _ = api
    listed = client.get("/agent/actions")
    assert listed.status_code == 200 and [ProposalView.model_validate(v) for v in listed.json()] == [view]
    assert ProposalView.model_validate(client.get(f"/agent/actions/{view.id}").json()) == view
    assert client.get("/agent/actions/act_9999").status_code == 404


def test_a_decision_needs_an_operator_session_and_its_token(api: tuple[TestClient, ProposalView, Any]) -> None:
    client, view, _ = api
    assert client.post(f"/agent/actions/{view.id}/approve", json=body(view)).status_code == 403
    headers = session(client)
    assert client.post(f"/agent/actions/{view.id}/approve", json=body(view)).status_code == 403  # no token
    wrong = {CSRF_HEADER: "not-the-token"}
    assert client.post(f"/agent/actions/{view.id}/approve", json=body(view), headers=wrong).status_code == 403
    evil = headers | {"Origin": "https://evil.example"}
    assert client.post(f"/agent/actions/{view.id}/approve", json=body(view), headers=evil).status_code == 403
    assert client.get(f"/agent/actions/{view.id}").json()["state"] == "AWAIT_OPERATOR"


def test_the_body_cannot_name_the_principal(api: tuple[TestClient, ProposalView, Any]) -> None:
    client, view, _ = api
    headers = session(client)
    sneaky = body(view) | {"principal": "the-model"}
    assert client.post(f"/agent/actions/{view.id}/approve", json=sneaky, headers=headers).status_code == 422


def test_approve_then_repeat_then_conflict(api: tuple[TestClient, ProposalView, Any]) -> None:
    client, view, _ = api
    headers = session(client) | {"Origin": "http://localhost:5173"}
    first = client.post(f"/agent/actions/{view.id}/approve", json=body(view), headers=headers)
    assert first.status_code == 200 and first.json()["decision"]["principal"] == "operator"
    applied = client.get(f"/agent/actions/{view.id}").json()
    assert applied["state"] == "APPLIED"
    again = client.post(f"/agent/actions/{view.id}/approve", json=body(view), headers=headers)
    assert again.status_code == 200 and again.json() == applied
    other = client.post(f"/agent/actions/{view.id}/approve", json=body(view, "key-approve-02"), headers=headers)
    assert other.status_code == 409
    deny = client.post(f"/agent/actions/{view.id}/deny", json=body(view), headers=headers)
    assert deny.status_code == 409


def test_deny_stale_and_expired(api: tuple[TestClient, ProposalView, Any]) -> None:
    client, view, clock = api
    headers = session(client)
    stale = {"digest": "sha256:" + "0" * 64, "idempotency_key": "key-approve-01"}
    assert client.post(f"/agent/actions/{view.id}/approve", json=stale, headers=headers).status_code == 409
    clock.now = datetime(2026, 11, 21, 0)
    late = client.post(f"/agent/actions/{view.id}/approve", json=body(view), headers=headers)
    assert late.status_code == 409 and "expired" in late.json()["detail"]
    assert client.get(f"/agent/actions/{view.id}").json()["state"] == "EXPIRED"


def test_denial(api: tuple[TestClient, ProposalView, Any]) -> None:
    client, view, _ = api
    headers = session(client)
    denied = client.post(f"/agent/actions/{view.id}/deny", json=body(view, "key-deny-0001"), headers=headers)
    assert denied.status_code == 200 and denied.json()["state"] == "DENIED"
    assert client.post(f"/agent/actions/{view.id}/approve", json=body(view), headers=headers).status_code == 409


def test_sessions_open_only_locally(make_service: Make) -> None:
    service, _, _ = make_service()
    app = FastAPI()
    app.include_router(create_router(service))  # the default gate: loopback clients only
    client = TestClient(app)  # its client host is "testclient", not a loopback address
    assert client.post("/agent/operator/session").status_code == 403
    assert is_local("127.0.0.1") and is_local("::1") and is_local("localhost")
    assert not is_local("10.0.0.7") and not is_local(None) and not is_local("evil.example")
