"""End to end: the watcher over generated MockMart worlds, graded against the hidden truth."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import numpy as np
import pytest

from argus.contracts.events import Event, EventType, TickPayload
from argus.contracts.findings import Anomaly, Note
from argus.contracts.graph import Graph
from argus.detect import EventRecorder, Watcher
from argus.semantic.runner import Runner
from mockmart.sim import WorldParams

from .conftest import World

pytestmark = pytest.mark.e2e

FRESH_ORDERS = "fact_orders_hourly"
STALL_HOURS = 3
STALL_DELAY_MIN = 240


@pytest.mark.parametrize("seed", [7, 4, 5])
def test_s1_payco_detected_within_exit_criteria(make_world: Callable[..., World], graph: Graph, seed: int) -> None:
    world = make_world("s1", seed)
    fault = world.fault()
    max_delay = timedelta(hours=fault["expected"]["max_detection_delay_hours"])
    runner = Runner(world.path)
    watcher = Watcher(runner, graph)
    # a day of quiet live data before the fault, then up to the deadline of the exit criteria
    for _ in watcher.run(fault["start_ts"] - timedelta(hours=24), fault["start_ts"] + max_delay):
        pass

    before = [a for a in watcher.anomalies if a.hour < fault["start_ts"]]
    assert before == [], f"false alarms before the fault: {before}"
    hits = [a for a in watcher.anomalies if a.node == fault["root_node"] and a.direction == "down"]
    assert hits, f"no {fault['root_node']} anomaly; opened: {[(a.node, a.segment) for a in watcher.anomalies]}"
    first = hits[0]
    assert first.detected_at - fault["start_ts"] <= max_delay
    # onset is the first hour of the |z| > 2 run, so a noisy hour just before the fault may start it;
    # it must stay inside the evidence window the investigator searches ([onset - 2 h, onset])
    assert fault["start_ts"] - timedelta(hours=2) <= first.onset <= first.hour
    assert set(first.segment.items()) <= set(fault["segment"].items())
    assert first.observed < first.band[0] < first.expected

    # every number on the anomaly comes from a receipt that re-runs to the same hash
    for rid in first.receipts:
        assert runner.rerun(rid)[1]
    rows = [r for r in runner.fetch(runner.receipts[first.receipts[0]].sql, first.detected_at) if r["ts"] == first.hour]
    assert rows and np.isclose(rows[0]["num"] / rows[0]["den"], first.observed)


@pytest.mark.parametrize("seed", [7, 3])
def test_quiet_world_stays_silent(make_world: Callable[..., World], graph: Graph, seed: int) -> None:
    world = make_world("quiet", seed)
    recorder = EventRecorder()
    watcher = Watcher(Runner(world.path), graph, emit=recorder)
    reports = list(watcher.run(world.live_start, world.end))

    assert watcher.anomalies == []
    assert watcher.notes == []
    assert len(reports) == int((world.end - world.live_start) / timedelta(hours=1)) + 1
    assert watcher.funnel.series > 20 * len(reports)  # it did look: north stars plus the attention budget

    ticks = [e for e in recorder.events if e.type is EventType.TICK]
    assert len(ticks) == len(reports)
    assert all(TickPayload.model_validate(t.payload).pending_nodes == [] for t in ticks)


def test_events_follow_the_c5_contract(make_world: Callable[..., World], graph: Graph) -> None:
    world = make_world("s1", 7)
    fault = world.fault()
    recorder = EventRecorder(start_seq=100)
    watcher = Watcher(Runner(world.path), graph, emit=recorder)
    for _ in watcher.run(fault["start_ts"] - timedelta(hours=2), fault["start_ts"] + timedelta(hours=3)):
        pass

    events = recorder.events
    assert [e.seq for e in events] == list(range(100, 100 + len(events)))
    for event in events:
        Event.model_validate(event.model_dump(mode="json"))
    by_tick: dict[object, list[EventType]] = {}
    for event in events:
        by_tick.setdefault(event.sim_ts, []).append(event.type)
    for types in by_tick.values():
        assert types[0] is EventType.ATTENTION and types[-1] is EventType.TICK
    opened = [Anomaly.model_validate(e.payload) for e in events if e.type is EventType.ANOMALY_OPENED]
    assert any(a.node == "payment_success_rate" for a in opened)
    attention = next(e for e in events if e.type is EventType.ATTENTION)
    assert "payment_success_rate[provider]" in attention.payload["scores"]


def _stall_orders(world_start_offset_hours: int) -> Callable[[WorldParams], None]:
    def mutate(params: WorldParams) -> None:
        delay = np.zeros(len(params.hours))
        first = params.hour_index(params.cfg.live_start) + world_start_offset_hours
        delay[first : first + STALL_HOURS] = STALL_DELAY_MIN
        params.extra_delay_min[FRESH_ORDERS] = delay

    return mutate


def test_late_table_is_a_data_issue_not_an_alert(make_world: Callable[..., World], graph: Graph) -> None:
    offset = 30
    world = make_world("quiet", 7, mutate=_stall_orders(offset), tag="-stall")
    stall = world.live_start + timedelta(hours=offset)
    watcher = Watcher(Runner(world.path), graph)
    reports = list(watcher.run(stall, stall + timedelta(hours=12)))

    notes: list[Note] = [n for r in reports for n in r.notes]
    assert [n.kind for n in notes] == ["data_issue", "data_issue"]
    assert FRESH_ORDERS in notes[0].reason and "late" in notes[0].reason
    assert "caught up" in notes[1].reason
    assert notes[0].numbers[0].value == pytest.approx(0.55)

    held = [r for r in reports if "orders" in r.tick.pending_nodes]
    assert held and all({"gmv", "cvr", "aov"} <= set(r.tick.pending_nodes) for r in held)
    assert [f.status for f in held[0].tick.freshness if f.table == FRESH_ORDERS] == ["pending"]
    assert watcher.anomalies == []

    # as the backfill lands, every held hour is scored exactly once and in order
    scored = [lk.hour for r in reports for lk in r.looks if lk.unit.node == "orders" and lk.unit.is_total]
    first_hour, last_hour = reports[0].hour, reports[-1].hour
    assert scored == [
        first_hour + k * timedelta(hours=1) for k in range(int((last_hour - first_hour) / timedelta(hours=1)) + 1)
    ]
    catch_up = next(r for r in reports if notes[1] in r.notes)
    assert len([lk for lk in catch_up.looks if lk.unit.node == "orders" and lk.unit.is_total]) > 1
