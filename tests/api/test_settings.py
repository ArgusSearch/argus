"""Operator settings validation, isolation and behavior at the live service boundary."""

from __future__ import annotations

import json
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from argus.agent.fake import FakeLlmClient
from argus.agent.investigate import AgentSelector
from argus.agent.journal import Journal
from argus.agent.service import AgentService
from argus.api import settings_routes
from argus.api.app import create_app
from argus.api.recording import FIXTURES
from argus.api.sources import LiveSource, ReplaySource
from argus.contracts.findings import Anomaly
from argus.settings import SettingsStore
from argus.watcher.detect import Score
from mockmart.world import WorldPaths

LOCAL = ("127.0.0.1", 46312)


def authorize(client: TestClient) -> dict[str, str]:
    response = client.post("/settings/operator/session")
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    return {"X-Argus-CSRF": response.json()["csrf_token"]}


def update(
    client: TestClient,
    headers: dict[str, str],
    area: str,
    changes: dict[str, Any],
    expected: int = 200,
) -> dict[str, Any]:
    revision = client.get("/settings", headers=headers).json()["revision"]
    response = client.patch(f"/settings/{area}", headers=headers, json={"revision": revision, "changes": changes})
    assert response.status_code == expected, response.text
    return response.json()  # type: ignore[no-any-return]


def test_settings_validation_persistence_undo_and_reset(tmp_path: Path) -> None:
    path = tmp_path / "operator.json"
    app = create_app(ReplaySource(), start=False, settings_path=path)
    client = TestClient(app, client=LOCAL)
    assert client.get("/settings").status_code == 403
    assert TestClient(app, client=("198.51.100.29", 4567)).post("/settings/operator/session").status_code == 403
    headers = authorize(client)
    assert authorize(client) == headers, "the operator session survives a reload"
    assert client.get("/settings", headers={**headers, "Origin": "https://untrusted.example"}).status_code == 403
    assert client.patch("/settings/budgets", headers={"X-Argus-CSRF": "wrong"}).status_code == 403
    assert (
        client.patch(
            "/settings/budgets",
            headers={**headers, "Content-Type": "application/json"},
            content="x" * 40_000,
        ).status_code
        == 413
    )

    update(client, headers, "thresholds", {"alarm_z": 1}, 422)
    update(client, headers, "thresholds", {"per_metric": {"unknown": {}}}, 422)
    update(client, headers, "budgets", {"requests": -1}, 422)
    update(client, headers, "quiet-hours", {"enabled": True, "start": "35:00"}, 422)
    update(client, headers, "autonomy", {"approve_action": "alone"}, 422)
    assert not path.exists()

    result = update(client, headers, "thresholds", {"alarm_z": 8.5})
    assert result["settings"]["thresholds"]["alarm_z"] == 8.5
    assert SettingsStore(path).read().thresholds.alarm_z == 8.5
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    conflict = client.patch("/settings/thresholds", headers=headers, json={"revision": 0, "changes": {"alarm_z": 10}})
    assert conflict.status_code == 409
    undo = client.post("/settings/thresholds/undo", headers=headers, json={"revision": result["revision"]})
    assert undo.json()["settings"]["thresholds"]["alarm_z"] == 5.0

    secret = "settings-test-key-sample"
    result = update(client, headers, "ai", {"provider": "anthropic", "api_key": secret})
    assert result["settings"]["ai"]["api_key_configured"] is True
    assert "api_key" not in result["settings"]["ai"]
    assert secret in path.read_text()
    assert secret not in client.get("/settings/export", headers=headers).text
    assert set(client.get("/settings/export/run", headers=headers).json()) == {"graph", "incidents", "notes"}
    invalid = update(client, headers, "ai", {"api_key": {"token": secret}}, 422)
    assert secret not in json.dumps(invalid)

    restarted = TestClient(create_app(ReplaySource(), start=False, settings_path=path), client=LOCAL)
    new_headers = authorize(restarted)
    assert restarted.get("/settings", headers=new_headers).json()["revision"] == result["revision"]
    reset = restarted.post(
        "/settings/reset", headers=new_headers, json={"revision": result["revision"], "confirm": "reset"}
    )
    assert reset.json()["settings"]["ai"]["api_key_configured"] is False
    assert secret not in path.read_text()


def test_public_sessions_cannot_affect_local_state_or_send_requests(tmp_path: Path) -> None:
    path = tmp_path / "operator.json"
    app = create_app(ReplaySource(), start=False, settings_path=path, public_settings=True)
    first, second = TestClient(app, client=LOCAL), TestClient(app, client=LOCAL)
    one, two = authorize(first), authorize(second)
    update(first, one, "autonomy", {"monitor": "off"})
    assert second.get("/settings", headers=two).json()["settings"]["autonomy"]["monitor"] == "alone"
    assert first.get("/settings", headers=two).status_code == 403
    update(first, one, "ai", {"provider": "anthropic", "api_key": "local-only-placeholder"}, 403)
    update(first, one, "notifications", {"slack_url": "https://example.org/notify"}, 403)
    assert first.post("/settings/notifications/test", headers=one, json={"channel": "slack"}).status_code == 403
    assert first.post("/settings/sources/test", headers=one, json={"id": "shop"}).status_code == 403
    assert not path.exists()


def test_test_buttons_contact_only_saved_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[tuple[str, dict[str, object] | None]] = []
    monkeypatch.setattr(settings_routes, "send_https", lambda url, message=None: used.append((url, message)))
    client = TestClient(create_app(ReplaySource(), start=False, settings_path=tmp_path / "settings.json"), client=LOCAL)
    headers = authorize(client)
    target = "https://example.org/slack?token=endpoint-secret"
    update(client, headers, "notifications", {"slack_url": target})
    response = client.post(
        "/settings/notifications/test",
        headers=headers,
        json={"channel": "slack", "url": "https://other.example/"},
    )
    assert response.status_code == 200
    assert used == [(target, {"text": "Argus notification test"})]
    assert target not in client.get("/settings", headers=headers).text

    update(
        client,
        headers,
        "sources",
        {
            "sources": [
                {"id": "shop", "name": "Example shop", "connector": "shopify", "url": "https://example.org/shop"},
            ]
        },
    )
    response = client.post("/settings/sources/test", headers=headers, json={"id": "shop"})
    assert response.status_code == 200
    assert used[-1] == ("https://example.org/shop", None)


def test_saved_autonomy_thresholds_and_budget_change_live_work(
    s1_world: WorldPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = LiveSource(s1_world.world, agent="off")
    fake = FakeLlmClient()
    journal = Journal(source.bus.stream)
    source.agent = AgentService("live", journal, client=fake, selector=AgentSelector(fake, journal))
    app = create_app(source, start=False, settings_path=tmp_path / "settings.json")
    with TestClient(app, client=LOCAL) as client:
        headers = authorize(client)
        runtime = source.runtime
        first = runtime.ticks()[0]
        update(client, headers, "autonomy", {"monitor": "off", "retest_graph": "off", "investigate": "off"})
        runtime.tick(first)
        assert not source.bus.state.last_tick.scored_nodes
        assert not fake.requests

        update(client, headers, "autonomy", {"monitor": "alone", "defer_late_data": "off"})
        update(client, headers, "thresholds", {"per_metric": {"orders": {"wiggle_z": 1, "pair_z": 2, "alarm_z": 3}}})
        monkeypatch.setattr(runtime.detector, "score", lambda node, hour: Score(node, hour, 120, 100, 4.1, 0.1))
        monkeypatch.setattr(runtime.plan_watch, "check_plans", lambda _: [])
        runtime.tick(runtime.ticks()[1])
        assert [a.node for a in runtime.anomalies.values()] == ["orders"]
        assert not runtime.book.incidents, "the configured autonomy policy stopped the investigation"

        update(client, headers, "autonomy", {"investigate": "alone", "defer_late_data": "alone"})
        update(client, headers, "budgets", {"requests": 0})
        anomaly = Anomaly.model_validate(json.loads((FIXTURES / "anomalies.json").read_bytes())[0])
        runtime._on_anomaly(anomaly, anomaly.detected_at)
        assert client.get("/agent/health").json()["caps"]["requests"] == 0
        assert not fake.requests, "the live model was stopped before its first request"
        run = next(iter(journal.runs.values()))
        assert run.status == "budget" and run.llm_calls == 0
        assert runtime.book.incidents, "the deterministic investigator still filed the incident"


def test_midnight_and_weekend_quiet_hours(tmp_path: Path) -> None:
    client = TestClient(create_app(ReplaySource(), start=False, settings_path=tmp_path / "settings.json"), client=LOCAL)
    headers = authorize(client)
    update(client, headers, "quiet-hours", {"enabled": True, "weekends": True, "bypass_eur": 1000})
    hours = SettingsStore(tmp_path / "settings.json").read().quiet_hours
    assert hours.holds(datetime.fromisoformat("2026-11-20T21:01:00"), 500)  # Friday 22:01 in Berlin
    assert hours.holds(datetime.fromisoformat("2026-11-21T10:12:00"), 500)
    assert not hours.holds(datetime.fromisoformat("2026-11-21T10:12:00"), 1000)
    assert not hours.holds(datetime.fromisoformat("2026-11-23T06:00:00"), 999)  # Monday 07:00 in Berlin


def test_provider_selection_and_monthly_spend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from argus.agent import settings_runtime
    from argus.agent.fake import tool_use
    from argus.agent.types import LlmRequest
    from argus.settings import AiModel, Budgets

    local = SettingsStore(tmp_path / "settings.json")
    fake = FakeLlmClient([tool_use("get_series", {})])
    provider_keys: list[str | None] = []

    class OpenAIAdapter:
        def __init__(self, key: str | None = None) -> None:
            provider_keys.append(key)

        def models(self, *, critic: bool) -> Any:
            return SimpleNamespace(loop="gpt-6.2-sol", synthesis="gpt-6.2-astra", critic="gpt-6.2-astra")

        def create(self, request: LlmRequest) -> Any:
            return fake.create(request).model_copy(update={"model": request.model})

    monkeypatch.delenv("ARGUS_DISABLE_PROVIDER", raising=False)
    monkeypatch.setattr(settings_runtime, "import_module", lambda _: SimpleNamespace(OpenAIClient=OpenAIAdapter))
    monkeypatch.setattr(settings_runtime.provider, "price", lambda _model, usage: 0.02 if usage else 0)
    agent = settings_runtime.SettingsAgent(AgentService("off", Journal()), "live", local)
    local.update(
        "ai",
        0,
        lambda _: AiModel.model_validate(
            {
                "provider": "openai",
                "model": "gpt-6.2-astra",
                "api_key": "configured-placeholder",
            }
        ),
    )
    local.update("budgets", 1, lambda _: Budgets(monthly_usd=0.01))
    service = agent.refresh()
    assert service.enabled and service.health()["models"]["loop"] == "gpt-6.2-astra"
    assert provider_keys == ["configured-placeholder"]
    assert service.client is not None
    request = LlmRequest(model="gpt-6.2-astra", system="", tools=[], messages=[], max_tokens=30, key="ask:one")
    service.client.create(request)
    assert fake.requests == [request]
    assert agent.budget().usd == 0
    with pytest.raises(settings_runtime.ProviderUnavailable, match="monthly model budget"):
        service.client.create(request)
    assert len(fake.requests) == 1
    assert settings_runtime.MonthlySpend(agent.meter.path).remaining(0.01) == 0


def test_quiet_delivery_waits_until_next_eligible_tick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from threading import Event

    from argus import notifications
    from argus.contracts.findings import Incident
    from argus.settings import Channels, Notifications, QuietHours

    local = SettingsStore(tmp_path / "settings.json")
    local.update("channels", 0, lambda _: Channels(slack=True))
    local.update(
        "notifications", 1, lambda _: Notifications.model_validate({"slack_url": "https://example.org/webhook"})
    )
    local.update("quiet_hours", 2, lambda _: QuietHours(enabled=True))
    message_sent = Event()
    monkeypatch.setattr(notifications, "send_https", lambda *_: message_sent.set())
    incident = Incident.model_validate(json.loads((FIXTURES / "incidents.json").read_bytes())[0])
    notices = notifications.IncidentNotices(local)
    try:
        notices.add(incident, datetime.fromisoformat("2026-11-21T01:00:00"))
        assert incident.id in notices.pending
        assert not message_sent.is_set()
        notices.flush(datetime.fromisoformat("2026-11-21T06:00:00"))
        assert message_sent.wait(2)
        assert incident.id not in notices.pending
    finally:
        notices.close()


def test_settings_write_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_routes, "monotonic", lambda: 60)
    client = TestClient(
        create_app(ReplaySource(), start=False, public_settings=True, settings_path=tmp_path), client=LOCAL
    )
    headers = authorize(client)
    for revision in range(30):
        change = {"revision": revision, "changes": {"name": f"Visitor {revision}"}}
        assert client.patch("/settings/account", headers=headers, json=change).status_code == 200
    blocked = client.patch("/settings/account", headers=headers, json={"revision": 30, "changes": {"name": "Visitor"}})
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"


def test_cloudflare_settings_use_partitioned_cookies_and_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    from scripts.cloudflare_api import PAGES_ORIGIN, origin_app

    monkeypatch.chdir(tmp_path)
    for key in os.environ.copy():
        if key.startswith(("ANTHROPIC_", "OPENAI_")):
            monkeypatch.delenv(key)
    api = TestClient(origin_app(None), client=LOCAL, base_url="https://argus-api.caniberk.dev")
    origin = {"Origin": PAGES_ORIGIN}
    preflight = api.options(
        "/settings/appearance",
        headers={**origin, "Access-Control-Request-Method": "PATCH", "Access-Control-Request-Headers": "X-Argus-CSRF"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == PAGES_ORIGIN
    session = api.post("/settings/operator/session", headers=origin)
    assert session.status_code == 200
    assert "Secure" in session.headers["set-cookie"]
    assert "Partitioned" in session.headers["set-cookie"]
    assert "SameSite=None" in session.headers["set-cookie"]
    saved = api.patch(
        "/settings/appearance",
        headers={**origin, "X-Argus-CSRF": session.json()["csrf_token"]},
        json={"revision": 0, "changes": {"theme": "dark"}},
    )
    assert saved.status_code == 200 and saved.json()["simulator"]
