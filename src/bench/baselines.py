"""Baseline agent: the alert a BI tool would send, so the scorecard shows what the graph and investigation add.

`ThresholdBaseline` watches five north-star totals hour by hour through the live window, exactly as
the data arrives (each tick pins `as_of` and reads only the `fact_*` views). The expectation for an hour
is the median of the same hour of the week over the last four weeks; the noise scale is the robust
spread of that forecast's relative error over history. It pages with |z| > 4, or 2 of the last 3 hours
beyond 3 in the same direction, which are Argus's own detection rules. It has no graph, no segments and
no logs, so every page says UNEXPLAINED on the whole business.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import duckdb
import numpy as np

from argus.contracts.findings import (
    Anomaly,
    Cost,
    Findings,
    Incident,
    IncidentState,
    IncidentTransition,
    ObservedChange,
    Quantity,
    Verdict,
    Window,
)
from bench.agents import AgentOutput

WEEK_H = 168
WEEKS = 4
Z_OPEN = 4.0
Z_TWO_OF_THREE = 3.0
Z_CLEAR = 2.0
CLEAR_HOURS = 3
DIRECTIONS: tuple[tuple[Literal["up", "down"], float], ...] = (("up", 1.0), ("down", -1.0))


@dataclass(frozen=True)
class _Node:
    id: str
    table: str
    expr: str
    unit: str


NODES: tuple[_Node, ...] = (
    _Node("sessions", "fact_funnel_hourly", "SUM(sessions)", "count"),
    _Node("orders", "fact_orders_hourly", "SUM(orders)", "count"),
    _Node("gmv", "fact_orders_hourly", "SUM(gmv)", "eur"),
    _Node(
        "payment_success_rate",
        "fact_payments_hourly",
        "SUM(payment_successes) / NULLIF(SUM(payment_attempts), 0)",
        "share",
    ),
    _Node("ad_spend", "fact_ads_hourly", "SUM(ad_spend)", "eur"),
)
TABLES = tuple(dict.fromkeys(n.table for n in NODES))


def _ts(value: datetime) -> str:
    return f"TIMESTAMP '{value:%Y-%m-%d %H:%M:%S}'"


@dataclass
class _Open:
    incident: Incident
    calm: int = 0


@dataclass
class _State:
    z_hist: dict[str, list[float]] = field(default_factory=dict)
    open: dict[tuple[str, str], _Open] = field(default_factory=dict)
    incidents: list[Incident] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)


class ThresholdBaseline:
    name = "threshold"

    def run(self, world: Path, manifest: Path) -> AgentOutput:
        meta = json.loads(manifest.read_text())
        live_start = datetime.fromisoformat(meta["live_start"])
        world_start = datetime.fromisoformat(meta["world_start"])
        world_end = datetime.fromisoformat(meta["world_end"])
        lag = timedelta(hours=int(meta["delivery_lag_hours"]))
        started = time.perf_counter()
        con = duckdb.connect(str(world), read_only=True)
        queries = 0
        try:
            # History: every hour that is complete when the live window opens.
            con.execute(f"SET VARIABLE as_of = {_ts(live_start)}")
            n_hist = int((live_start - lag - world_start) / timedelta(hours=1))
            n_all = int((world_end - world_start) / timedelta(hours=1))
            series = {n.id: np.full(n_all, np.nan) for n in NODES}
            for table in TABLES:
                mine = [n for n in NODES if n.table == table]
                cols = ", ".join(f"{n.expr} AS {n.id}" for n in mine)
                rows = con.execute(
                    f"SELECT ts, {cols} FROM {table} WHERE ts < {_ts(live_start - lag)} GROUP BY ts ORDER BY ts"
                ).fetchall()
                queries += 1
                for row in rows:
                    h = int((row[0] - world_start) / timedelta(hours=1))
                    for i, n in enumerate(mine):
                        series[n.id][h] = float(row[i + 1])
            sigma = {n.id: _robust_sigma(series[n.id][:n_hist]) for n in NODES}

            state = _State()
            as_of = live_start + lag
            while as_of <= world_end:
                hour = as_of - lag
                h = int((hour - world_start) / timedelta(hours=1))
                con.execute(f"SET VARIABLE as_of = {_ts(as_of)}")
                for table in TABLES:
                    mine = [n for n in NODES if n.table == table]
                    cols = ", ".join(f"{n.expr} AS {n.id}" for n in mine)
                    hit = con.execute(f"SELECT {cols} FROM {table} WHERE ts = {_ts(hour)}").fetchone()
                    queries += 1
                    for i, n in enumerate(mine):
                        value = float(hit[i]) if hit is not None and hit[i] is not None else float("nan")
                        expected = _forecast(series[n.id], h)
                        self._score(state, n, hour, as_of, value, expected, sigma[n.id])
                        series[n.id][h] = value  # what the tool saw; forecasts a week later use it
                as_of += timedelta(hours=1)
        finally:
            con.close()
        seconds = time.perf_counter() - started
        cost = Cost(queries=queries, seconds=round(seconds, 2))
        for inc in state.incidents:
            inc.findings.cost = cost
        return AgentOutput(incidents=state.incidents, anomalies=state.anomalies, cost=cost)

    def _score(
        self, state: _State, node: _Node, hour: datetime, as_of: datetime, value: float, expected: float, sigma: float
    ) -> None:
        if not np.isfinite(value) or not np.isfinite(expected) or expected == 0:
            return
        z = (value / expected - 1.0) / sigma
        hist = state.z_hist.setdefault(node.id, [])
        hist.append(z)
        last3 = hist[-3:]
        for direction, sign in DIRECTIONS:
            key = (node.id, direction)
            fired = sign * z > Z_OPEN or sum(sign * x > Z_TWO_OF_THREE for x in last3) >= 2
            current = state.open.get(key)
            if current is not None:
                current.calm = 0 if abs(z) >= Z_CLEAR else current.calm + 1
                current.incident.updated_at = as_of
                if current.calm >= CLEAR_HOURS:
                    self._resolve(state, key, as_of)
            elif fired:
                self._open(state, node, direction, hour, as_of, value, expected, sigma, z)

    def _open(
        self,
        state: _State,
        node: _Node,
        direction: Literal["up", "down"],
        hour: datetime,
        as_of: datetime,
        value: float,
        expected: float,
        sigma: float,
        z: float,
    ) -> None:
        an_id = f"an_{len(state.anomalies) + 1:04d}"
        inc_id = f"INC-{len(state.incidents) + 1:04d}"
        band = (expected * (1 - 2 * sigma), expected * (1 + 2 * sigma))
        rule: Literal["z_gt_open", "two_of_three"] = "z_gt_open" if abs(z) > Z_OPEN else "two_of_three"
        state.anomalies.append(
            Anomaly(
                id=an_id,
                node=node.id,
                direction=direction,
                hour=hour,
                detected_at=as_of,
                onset=hour,
                observed=value,
                expected=expected,
                band=band,
                z=round(z, 2),
                rule=rule,
            )
        )
        change = value / expected - 1.0
        headline = f"{node.id} {change:+.1%} vs the last {WEEKS} weeks (z {z:+.1f}); cause unknown"
        findings = Findings(
            anomaly_id=an_id,
            verdict=Verdict.UNEXPLAINED,
            headline=headline,
            as_of=as_of,
            window=Window(start=hour, end=hour),
            observed=ObservedChange(
                node=node.id,
                segment={},
                observed=Quantity(value=value, unit=node.unit, receipt=None),
                expected=Quantity(value=expected, unit=node.unit, receipt=None),
                change_pct=Quantity(value=round(change * 100, 2), unit="pct", receipt=None),
            ),
            explained_share=0.0,
            unexplained_share=1.0,
            cost=Cost(queries=0, seconds=0.0),
        )
        incident = Incident(
            id=inc_id,
            fingerprint=f"{node.id}|{{}}|{direction}",
            title=f"{node.id} {direction} on the whole business",
            verdict=Verdict.UNEXPLAINED,
            state=IncidentState.OPEN,
            root_node=node.id,
            segment={},
            direction=direction,
            severity_eur=0.0,
            opened_at=hour,
            updated_at=as_of,
            anomalies=[an_id],
            history=[IncidentTransition(sim_ts=as_of, from_state=None, to_state=IncidentState.OPEN, reason=headline)],
            findings=findings,
        )
        state.incidents.append(incident)
        state.open[(node.id, direction)] = _Open(incident)

    def _resolve(self, state: _State, key: tuple[str, str], as_of: datetime) -> None:
        inc = state.open.pop(key).incident
        inc.history.append(
            IncidentTransition(
                sim_ts=as_of, from_state=inc.state, to_state=IncidentState.RESOLVED, reason="back inside the band"
            )
        )
        inc.state = IncidentState.RESOLVED
        inc.resolved_at = as_of


def _forecast(series: np.ndarray, h: int) -> float:
    past = [series[h - k * WEEK_H] for k in range(1, WEEKS + 1) if h - k * WEEK_H >= 0]
    past = [p for p in past if np.isfinite(p)]
    return float(np.median(past)) if len(past) >= 2 else float("nan")


def _robust_sigma(history: np.ndarray) -> float:
    """1.4826 x MAD of the forecast's relative error over every history hour with a full forecast."""
    errors = []
    for h in range(WEEKS * WEEK_H, len(history)):
        expected = _forecast(history, h)
        if np.isfinite(expected) and expected and np.isfinite(history[h]):
            errors.append(history[h] / expected - 1.0)
    arr = np.asarray(errors)
    mad = float(np.median(np.abs(arr - np.median(arr))))
    return max(1.4826 * mad, 1e-4)
