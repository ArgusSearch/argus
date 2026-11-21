"""Expectation, robust z-scores and the open / resolve rules for the monitored (north-star) nodes.

```
expected  y_hat_t = median(y_{t-168k}, k = 1..4) x (1 + planned_uplift_t)   # additive: same hour of week
          y_hat_t = sum(num_{t-168k}) / sum(den_{t-168k})                     # ratio: pooled over 4 weeks
residual  r_t = y_t / y_hat_t - 1                                             # relative
scale     s = 1.4826 x MAD(r) over the previous 168 hours                    # many points, not 4
floor     Poisson 1/sqrt(y_hat) for counts, binomial sqrt((1-p)/(p n)) for rates
z_t       = r_t / max(s, floor_t)
open      |z| > 4, or 2 of the last 3 hours |z| > 3 (same sign)
resolve   3 consecutive hours with |z| < 2
onset     first hour of the run with |z| > 2
```

Planned events change the expectation (`planned_uplift`), they never mute a metric.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from argus.contracts.findings import Anomaly
from argus.contracts.graph import Graph, NodeKind
from argus.semantic.compile import hourly_sql, parts, points_condition
from argus.semantic.runner import Runner, sql_ts

HOUR = timedelta(hours=1)
WEEK_H = 168
SCALE_HOURS = 168
LOOKBACK_HOURS = 4 * WEEK_H + SCALE_HOURS + 24
REFRESH_HOURS = 6
Z_OPEN, Z_PAIR, Z_ONSET, Z_CALM = 4.0, 3.0, 2.0, 2.0
CALM_HOURS = 3


def planned_uplift(node_id: str, hour: datetime) -> float:
    """Relative uplift from planned calendar events (log_calendar.planned_uplift). Lane B, scenario S2."""
    return 0.0


@dataclass
class Score:
    node: str
    hour: datetime
    observed: float
    expected: float
    z: float
    sigma_rel: float

    @property
    def band(self) -> tuple[float, float]:
        width = 2 * self.sigma_rel * self.expected
        return (self.expected - width, self.expected + width)


class TotalsCache:
    """Hourly totals per fact view, refreshed incrementally. Complete hours never change, so only the most
    recent hours and hours that were incomplete at the last fetch are queried again."""

    def __init__(self, runner: Runner):
        self.runner = runner
        self.frames: dict[str, pd.DataFrame] = {}

    def refresh(self, table: str, measures: list[str], hour: datetime, as_of: datetime, stale: set[datetime]) -> None:
        frame = self.frames.get(table)
        since = hour - LOOKBACK_HOURS * HOUR if frame is None else min({hour - REFRESH_HOURS * HOUR, *stale})
        sums = ", ".join(f"SUM({m}) AS {m}" for m in measures)
        sql = (
            f"SELECT ts, {sums} FROM {table} WHERE ts BETWEEN {sql_ts(since)} AND {sql_ts(hour)} "
            "GROUP BY ts ORDER BY ts"
        )
        fresh = pd.DataFrame(self.runner.fetch(sql, as_of), columns=["ts", *measures]).set_index("ts").astype(float)
        if frame is None:
            self.frames[table] = fresh
        else:
            merged = pd.concat([frame[frame.index < since], fresh])
            self.frames[table] = merged[merged.index >= hour - LOOKBACK_HOURS * HOUR]

    def series(self, table: str, measure: str, hours: pd.DatetimeIndex) -> np.ndarray:
        return self.frames[table][measure].reindex(hours).to_numpy(dtype=float)


@dataclass
class NodeState:
    z: dict[datetime, float] = field(default_factory=dict)
    open_anomaly: Anomaly | None = None
    calm: int = 0


class Detector:
    def __init__(self, graph: Graph, runner: Runner, nodes: list[str] | None = None):
        self.graph = graph
        self.runner = runner
        self.cache = TotalsCache(runner)
        self.nodes = nodes or [n.id for n in graph.north_stars()]
        self.state: dict[str, NodeState] = {n: NodeState() for n in self.nodes}
        self._anomaly_seq = 0

    def tables(self, node_id: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for p in parts(self.graph, node_id):
            assert p.node.table and p.node.measure
            out.setdefault(p.node.table, []).append(p.node.measure)
        return out

    def all_tables(self) -> dict[str, list[str]]:
        merged: dict[str, set[str]] = {}
        for node in self.nodes:
            for tbl, ms in self.tables(node).items():
                merged.setdefault(tbl, set()).update(ms)
        return {t: sorted(ms) for t, ms in merged.items()}

    def refresh(self, hour: datetime, as_of: datetime, stale: dict[str, set[datetime]]) -> None:
        for tbl, measures in self.all_tables().items():
            self.cache.refresh(tbl, measures, hour, as_of, stale.get(tbl, set()))

    def score(self, node_id: str, hour: datetime) -> Score | None:
        node = self.graph.node(node_id)
        hours = pd.date_range(hour - LOOKBACK_HOURS * HOUR + HOUR, hour, freq="h")
        lags = [k * WEEK_H for k in range(1, 5)]
        idx = np.arange(4 * WEEK_H, len(hours))  # hours with a full 4-week history

        def lagged(arr: np.ndarray) -> np.ndarray:
            return np.stack([arr[idx - lag] for lag in lags])

        ps = parts(self.graph, node_id)
        if node.kind is NodeKind.ADDITIVE:
            y = self.cache.series(ps[0].node.table or "", ps[0].node.measure or "", hours)
            expected = np.median(lagged(y), axis=0)
            observed = y[idx]
            floor = 1 / np.sqrt(np.maximum(expected, 1.0)) if node.unit == "count" else np.zeros_like(expected)
        else:
            num = self.cache.series(ps[0].node.table or "", ps[0].node.measure or "", hours)
            den = self.cache.series(ps[1].node.table or "", ps[1].node.measure or "", hours)
            with np.errstate(divide="ignore", invalid="ignore"):
                expected = lagged(num).sum(axis=0) / lagged(den).sum(axis=0)
                observed = num[idx] / den[idx]
            floor = _ratio_floor(ps[0].node.unit, ps[1].node.unit, expected, num[idx], den[idx])
        expected = expected * (1 + planned_uplift(node_id, hour))
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = observed / expected - 1
        if not np.isfinite(rel[-1]):
            return None
        window = rel[-SCALE_HOURS - 1 : -1]
        window = window[np.isfinite(window)]
        mad = float(np.median(np.abs(window - np.median(window)))) if len(window) else 0.0
        sigma = max(1.4826 * mad, float(floor[-1]), 1e-9)
        return Score(node_id, hour, float(observed[-1]), float(expected[-1]), float(rel[-1] / sigma), sigma)

    def observe(self, score: Score, as_of: datetime) -> tuple[Anomaly | None, Anomaly | None]:
        """Apply the open / resolve rules. Returns (opened, resolved)."""
        st = self.state[score.node]
        st.z[score.hour] = score.z
        prev = [st.z.get(score.hour - k * HOUR) for k in (1, 2)]
        if st.open_anomaly is not None:
            st.calm = st.calm + 1 if abs(score.z) < Z_CALM else 0
            if st.calm >= CALM_HOURS:
                closed, st.open_anomaly, st.calm = st.open_anomaly, None, 0
                return None, closed
            return None, None
        rule = None
        if abs(score.z) > Z_OPEN:
            rule = "z_gt_4"
        elif abs(score.z) > Z_PAIR and any(p is not None and abs(p) > Z_PAIR and p * score.z > 0 for p in prev):
            rule = "two_of_three_gt_3"
        if rule is None:
            return None, None
        onset = score.hour
        while (z := st.z.get(onset - HOUR)) is not None and abs(z) > Z_ONSET and z * score.z > 0:
            onset -= HOUR
        self._anomaly_seq += 1
        receipt = self._receipt(score, as_of)
        anomaly = Anomaly(
            id=f"an_{self._anomaly_seq:04d}",
            node=score.node,
            direction="down" if score.z < 0 else "up",
            hour=score.hour,
            detected_at=as_of,
            onset=onset,
            observed=round(score.observed, 6),
            expected=round(score.expected, 6),
            band=(round(score.band[0], 6), round(score.band[1], 6)),
            z=round(score.z, 2),
            rule=rule,  # type: ignore[arg-type]
            receipts=[receipt],
        )
        st.open_anomaly, st.calm = anomaly, 0
        return anomaly, None

    def _receipt(self, score: Score, as_of: datetime) -> str:
        hours = [score.hour - k * WEEK_H * HOUR for k in range(0, 5)]
        sql = hourly_sql(self.graph, score.node, points_condition(hours))
        _, receipt = self.runner.query(
            sql, as_of, purpose=f"{score.node}: observed hour and the same hour in the 4 previous weeks"
        )
        return receipt.id


def _ratio_floor(num_unit: str, den_unit: str, p: np.ndarray, num: np.ndarray, den: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        if num_unit == "count" and den_unit == "count" and np.all(p[np.isfinite(p)] <= 1):
            return np.sqrt(np.clip(1 - p, 0, 1) / (p * den))
        terms = np.zeros_like(p)
        if num_unit == "count":
            terms = terms + 1 / np.maximum(num, 1)
        if den_unit == "count":
            terms = terms + 1 / np.maximum(den, 1)
        return np.sqrt(terms)
