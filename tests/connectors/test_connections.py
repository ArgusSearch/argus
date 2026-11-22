from __future__ import annotations

from datetime import datetime
from functools import partial
from pathlib import Path
from stat import S_IMODE

import pytest
from fastapi.testclient import TestClient
from test_providers import plausible_response, stripe_response

from argus.agent.types import RunContext
from argus.api import app as api_app
from argus.api.sources import LiveSource
from argus.connectors.provider import ProviderError
from argus.connectors.service import Connections
from argus.connectors.vault import Credentials, Vault
from argus.evidence.store import EvidenceStore

CLIENT = {"base_url": "http://127.0.0.1:8000", "client": ("127.0.0.1", 50000)}
KEY = "mock-credential-that-must-stay-private"


def authenticate(client: TestClient) -> dict[str, str]:
    session = client.post("/connections/operator/session")
    assert session.is_success, session.text
    cookie = session.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/connections" in cookie
    return {"X-Argus-CSRF": session.json()["csrf_token"]}


@pytest.fixture
def live_api(s1_world, monkeypatch, tmp_path):
    class Provider:
        increase = 0
        offline = False

        def __call__(self, endpoint, key, *, body=None, params=None):
            if endpoint == "plausible":
                assert key == KEY
                if self.offline:
                    raise ProviderError("The provider could not be reached.")
                return plausible_response(endpoint, key, body=body, increase=self.increase)
            assert key == "rk_test_example"
            response = stripe_response(endpoint, key, params=params)
            for row in response["data"]:
                row["created"] = params["created[lt]"] - 86400
            return response

    provider = Provider()
    monkeypatch.setattr(api_app, "Connections", partial(Connections, fetch=provider))
    source = LiveSource(s1_world.world, agent="off")
    directory = tmp_path / "storage"
    app = api_app.create_app(source, start=False, connections_path=directory)
    with TestClient(app, **CLIENT) as client:
        yield client, source, directory, provider


def test_requires_local_operator_and_csrf(live_api):
    client, _, _, _ = live_api
    assert client.get("/connections").status_code == 403
    assert client.post("/connections/operator/session", headers={"CF-Connecting-IP": "203.0.113.1"}).status_code == 403
    assert client.post("/connections/operator/session", headers={"Host": "api.example.com"}).status_code == 403
    assert client.post("/connections/operator/session", headers={"Origin": "http://localhost:9090"}).status_code == 403
    headers = authenticate(client)
    assert client.get("/connections").status_code == 403
    assert client.get("/connections", headers=headers).status_code == 200
    assert client.get("/connections", headers={**headers, "Origin": "https://attacker.example"}).status_code == 403
    bad = client.post(
        "/connections/plausible/connect", headers=headers, json={"key": KEY, "target": "https://127.0.0.1"}
    )
    assert bad.status_code == 422 and KEY not in bad.text
    bad = client.post("/connections/stripe/connect", headers=headers, json={"key": "sk_live_fixture", "target": "EUR"})
    assert bad.status_code == 422 and "sk_live_fixture" not in bad.text


def test_sync_updates_graph_and_keeps_original_receipts(live_api):
    client, source, directory, provider = live_api
    headers = authenticate(client)
    assert client.get("/connections/plausible", headers=headers).json()["status"] == "missing"
    sync = client.post("/connections/plausible/connect", headers=headers, json={"key": KEY, "target": "example.com"})
    assert sync.status_code == 200 and sync.json()["status"] == "connected", sync.text
    assert KEY not in sync.text and sync.headers["Cache-Control"] == "no-store"
    assert KEY.encode() not in (directory / "plausible.enc").read_bytes()
    for filename in ("master.key", "plausible.enc"):
        assert S_IMODE((directory / filename).stat().st_mode) == 0o600

    metric = client.get("/graph/metrics/plausible_visitors").json()
    assert metric["node"]["source"] == "connector:plausible"
    assert client.get("/graph").json()["nodes"][-1]["id"] == "plausible_conversions"
    assert KEY not in str(metric)
    receipt = metric["receipts"][0]["id"]
    assert client.post(f"/receipts/{receipt}/rerun").json()["matches"] is True

    runner = source.runtime.runner
    graph = source.graph()
    snapshot = runner.source_snapshots["plausible"]
    ctx = RunContext(
        run_id="ask-test",
        kind="ask",
        stream=source.bus.stream,
        as_of=datetime(2026, 10, 1),
        through_seq=source.bus.last_seq,
        world_revision="factual",
    )
    store = EvidenceStore()
    store.bind(
        ctx,
        graph=graph,
        runner=runner,
        latest_hour=ctx.as_of,
        source_clocks={
            "connector:plausible": (snapshot.synced_at, snapshot.latest_hour),
        },
    )
    window = {"start": "2026-11-21T00:00:00", "end": "2026-11-21T00:00:00"}
    observation = store.dispatch(
        ctx,
        "get_series",
        {
            "node": "plausible_pageviews",
            "segment": {"page_path": "/pricing"},
            "window": window,
        },
    )
    assert observation.availability == "ok"
    assert observation.data["points"][0]["value"] == 17
    assert observation.receipt_refs

    provider.increase = 8
    assert client.post("/connections/plausible/test", headers=headers).json()["status"] == "connected"
    current = client.get("/graph/metrics/plausible_visitors").json()["receipts"][0]
    assert current["result_hash"] != metric["receipts"][0]["result_hash"]
    assert client.post(f"/receipts/{receipt}/rerun").json()["matches"] is True
    assert store.rerun_receipt(ctx, observation.receipt_refs[0])[1] is True

    provider.offline = True
    failure = client.post("/connections/plausible/test", headers=headers).json()
    assert failure["status"] == "error" and failure["has_key"] and failure["last_synced"]
    response = client.post("/connections/plausible/disconnect", headers=headers)
    assert response.json()["status"] == "missing" and not (directory / "plausible.enc").exists()
    assert client.post(f"/receipts/{receipt}/rerun").json()["matches"] is True


def test_stripe_ratio_and_restoration(live_api):
    client, source, directory, _ = live_api
    headers = authenticate(client)
    saved = client.post(
        "/connections/stripe/connect", headers=headers, json={"key": "rk_test_example", "target": "EUR"}
    )
    assert saved.json()["status"] == "connected", saved.text
    assert "rk_test_example" not in saved.text
    placed = client.get("/graph/metrics/stripe_payment_success_rate").json()
    node = placed["node"]
    assert node["kind"] == "ratio"
    assert node["numerator"] == "stripe_successful_payments"
    assert node["denominator"] == "stripe_resolved_payments"
    receipt = placed["receipts"][0]
    snapshot = source.runtime.runner.source_snapshots["stripe"]
    rows = source.runtime.runner.fetch(receipt["sql"], snapshot.synced_at)
    assert next(row["value"] for row in rows if row["ts"] == snapshot.latest_hour) == pytest.approx(2 / 3)

    assert client.post("/connections/stripe/disconnect", headers=headers).is_success
    reopened = LiveSource(source.runtime.world, agent="off")
    app = api_app.create_app(reopened, start=False, connections_path=directory)
    with TestClient(app, **CLIENT) as restarted:
        placement = restarted.get("/graph/metrics/stripe_payment_success_rate").json()
        assert placement["receipts"][0]["result_hash"] == receipt["result_hash"]
        assert restarted.get("/connections/stripe", headers=authenticate(restarted)).json()["status"] == "missing"


def test_rate_limit_applies_across_sessions(live_api):
    client, _, _, _ = live_api
    headers = authenticate(client)
    for _ in range(8):
        assert client.post("/connections/plausible/test", headers=headers).status_code == 200
    client.cookies.clear()
    headers = authenticate(client)
    reply = client.post("/connections/plausible/test", headers=headers)
    assert reply.status_code == 429 and reply.headers["Retry-After"] == "60"


def test_desktop_credentials_use_an_os_keyring(tmp_path: Path):
    class Keyring:
        def __init__(self):
            self.values = {}

        def get_password(self, service, username):
            return self.values.get((service, username))

        def set_password(self, service, username, key):
            self.values[service, username] = key

        def delete_password(self, service, username):
            del self.values[service, username]

    keyring = Keyring()
    vault = Vault(tmp_path, keyring)
    vault.save("stripe", Credentials.model_validate({"key": "rk_test_example", "target": "eur"}))
    assert "rk_test_example" in next(iter(keyring.values.values()))
    assert list(tmp_path.iterdir()) == []
    assert vault.read("stripe").target == "eur"
    vault.delete("stripe")
    assert vault.read("stripe") is None
