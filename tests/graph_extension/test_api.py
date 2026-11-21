"""A new metric places itself in the running graph through the API: EXACT, AMBIGUOUS and a fan-out rejection,
live over a world and from the recorded demo pack in a replay."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from argus.api.app import create_app
from argus.api.recording import FIXTURES
from argus.api.sources import LiveSource, ReplaySource
from argus.contracts.events import EventType
from argus.graph.extension import RECORDING, load_recorded, record, recorded_metrics
from mockmart.sim import WorldConfig
from mockmart.world import generate

PACK = recorded_metrics()
CPI, CONV, RPC, RPI, SPEND = (m.model_dump() for m in PACK)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The world the pack is recorded on: S4, seed 1 (`make world SCENARIO=s4 SEED=1`)."""
    return generate("s4", WorldConfig(seed=1), tmp_path_factory.mktemp("worlds") / "s4-1").world


@pytest.fixture(scope="module")
def live(world: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[TestClient, LiveSource]]:
    source = LiveSource(world)
    app = create_app(source, start=False, web_dist=tmp_path_factory.mktemp("dist"))
    with TestClient(app) as client:
        yield client, source


def edge(result: dict[str, Any], reads: str) -> dict[str, Any]:
    return next(c for c in result["candidates"] if c["reads"] == reads)


def test_the_pack_is_a_cpm_chain_an_ambiguous_yield_and_a_fan_out() -> None:
    assert [m.name for m in PACK] == [
        "cost_per_impression",
        "conversions_per_impression",
        "revenue_per_conversion",
        "revenue_per_impression",
        "ad_spend_per_session",
    ]


def test_live_exact_placement_with_a_lineage_certificate(live: tuple[TestClient, LiveSource]) -> None:
    client, source = live
    before = len(client.get("/graph").json()["nodes"])
    res = client.post("/graph/metrics", json=CPI)
    assert res.status_code == 200
    r = res.json()
    assert (r["placed_as"], r["mode"], r["world"]) == ("EXACT", "live", "S4 world, seed 1")
    assert r["node"]["numerator"] == "ad_spend" and r["node"]["denominator"] == "ad_impressions"
    assert r["parents"] == ["ctr", "cpc"] and r["node"]["state"] == "watching"
    chain = edge(r, "cost_per_impression = ctr * cpc")
    assert chain["lifecycle"] == "accepted" and chain["edge"]["status"] == "VALID"
    assert chain["edge"]["provenance"] == "lineage" and chain["result"]["hours"] == 672
    assert any("cost_per_impression = ctr * cpc -> VALID" in line for line in r["certificate"]["passed"])
    assert r["cards"][0]["after"] == "EXACT" and r["receipts"]

    graph = client.get("/graph").json()
    assert len(graph["nodes"]) == before + 1
    assert {e["id"] for e in r["added_edges"]} <= {e["id"] for e in graph["edges"]}
    assert source.runtime.graph.node("cost_per_impression").kind == "ratio"  # the runtime re-tests it daily
    receipt = r["certificate"]["receipts"][0]
    assert client.get(f"/receipts/{receipt}").json()["id"] == receipt

    kinds = [(e.type, e.payload.get("kind")) for e in source.bus.history]
    assert (EventType.GRAPH_CHANGED, "node_added") in kinds and (EventType.EDGE_STATUS, None) in kinds


def test_live_ambiguous_placement_stays_on_probation(live: tuple[TestClient, LiveSource]) -> None:
    client, _ = live
    for m in (CPI, CONV, RPC):
        assert client.post("/graph/metrics", json=m).json()["placed_as"] == "EXACT"
    r = client.post("/graph/metrics", json=RPI).json()
    assert r["placed_as"] == "AMBIGUOUS" and r["node"]["state"] == "probation"
    chosen = edge(r, "revenue_per_impression = cost_per_impression * roas")
    assert chosen["lifecycle"] == "accepted" and chosen["edge"]["status"] == "PROBATION"
    assert chosen["edge"]["weight"] == 0.5
    other = edge(r, "revenue_per_impression = conversions_per_impression * revenue_per_conversion")
    assert other["lifecycle"] == "tested" and other["result"]["passed"]
    assert r["alternatives"] == ["revenue_per_impression = conversions_per_impression * revenue_per_conversion"]
    assert any(u.startswith("ambiguous: 2 equally simple formulas fit") for u in r["certificate"]["uncertain"])
    assert other["edge"]["id"] not in {e["id"] for e in client.get("/graph").json()["edges"]}


def test_live_fan_out_is_rejected_with_a_repair_and_leaves_the_graph(live: tuple[TestClient, LiveSource]) -> None:
    client, _ = live
    graph = client.get("/graph").json()
    r = client.post("/graph/metrics", json=SPEND).json()
    assert r["placed_as"] == "REJECTED" and r["node"] is None and not r["added_edges"]
    assert r["repair"]["factor"] == pytest.approx(6.72, abs=0.01)
    assert "join fan-out" in r["summary"] and "+WITH num AS" in r["repair"]["diff"]
    assert r["cards"][0]["diff"] == r["repair"]["diff"]
    assert client.get("/graph").json() == graph


def test_listing_reading_and_idempotent_onboarding(live: tuple[TestClient, LiveSource]) -> None:
    client, _ = live
    state = client.get("/graph/metrics").json()
    names = [p["metric"]["name"] for p in state["placements"]]
    assert names[0] == "cost_per_impression" and "revenue_per_impression" in names and state["mode"] == "live"
    again = client.post("/graph/metrics", json=CPI)  # the same metric again: the placement is not repeated
    assert again.status_code == 200 and client.get("/graph/metrics").json()["version"] == state["version"]
    assert client.get("/graph/metrics/revenue_per_impression").json()["placed_as"] == "AMBIGUOUS"
    assert client.get("/graph/metrics/nope").status_code == 404
    assert client.post("/graph/metrics", json={"name": "x"}).status_code == 422
    assert client.post("/metrics", json=CPI).status_code == 501  # the frozen C5 table keeps its stub


def test_yaml_body_is_a_metric_file(live: tuple[TestClient, LiveSource]) -> None:
    client, _ = live
    path = sorted((RECORDING / "metrics").glob("*.yml"))[0]
    res = client.post("/graph/metrics", content=path.read_bytes(), headers={"content-type": "application/yaml"})
    assert res.status_code == 200 and res.json()["metric"]["name"] == "cost_per_impression"


def test_replay_places_the_recorded_pack_in_order(tmp_path: Path) -> None:
    source = ReplaySource(FIXTURES / "s4", seconds_per_tick=0.001)
    with TestClient(create_app(source, web_dist=tmp_path)) as client:
        blocked = client.post("/graph/metrics", json=RPI)
        assert blocked.status_code == 409 and "cost_per_impression" in blocked.json()["detail"]
        unknown = client.post("/graph/metrics", json={**CPI, "sql": CPI["sql"].replace("ad_spend", "ad_clicks")})
        assert unknown.status_code == 409 and "make demo" in unknown.json()["detail"]
        assert [m["name"] for m in client.get("/graph/metrics").json()["recorded"]] == [m.name for m in PACK]

        verdicts = [client.post("/graph/metrics", json=m).json()["placed_as"] for m in (CPI, CONV, RPC, RPI, SPEND)]
        assert verdicts == ["EXACT", "EXACT", "EXACT", "AMBIGUOUS", "REJECTED"]
        graph = client.get("/graph").json()
        nodes = {n["id"]: n for n in graph["nodes"]}
        assert nodes["revenue_per_impression"]["state"] == "probation"
        r = client.get("/graph/metrics/revenue_per_impression").json()
        assert r["mode"] == "recorded" and {e["id"] for e in r["added_edges"]} <= {e["id"] for e in graph["edges"]}
        receipt = r["receipts"][0]["id"]
        assert receipt.startswith("gx-") and client.get(f"/receipts/{receipt}").json()["id"] == receipt
        assert client.post(f"/receipts/{receipt}/rerun").status_code == 409

        client.post("/replay", json={"action": "restart"})
        assert client.get("/graph/metrics").json()["placements"] == []
        assert "revenue_per_impression" not in {n["id"] for n in client.get("/graph").json()["nodes"]}


def _comparable(results: list[Any]) -> str:
    data = json.loads(json.dumps(results, default=str))
    for r in data:
        for receipt in r["receipts"]:
            receipt.pop("ms")
    return json.dumps(data, sort_keys=True)


def test_the_recording_is_what_the_classifier_places_today(world: Path, tmp_path: Path) -> None:
    """Re-record on a fresh S4 seed-1 world: re-run `python -m argus.graph.extension record` when this fails."""
    (tmp_path / "metrics").mkdir()
    for path in sorted((RECORDING / "metrics").glob("*.yml")):
        (tmp_path / "metrics" / path.name).write_text(path.read_text())
    record(world, tmp_path)
    fresh = _comparable([r.model_dump(mode="json") for r in load_recorded(tmp_path)])
    fresh = fresh.replace(str(tmp_path), "fixtures/graph_extension")  # the checked-in one names repo paths
    assert fresh == _comparable([r.model_dump(mode="json") for r in load_recorded()])
