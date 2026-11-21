"""The watcher: one tick per simulated hour, statistics only (no LLM).

Per tick, with `as_of` on the hour and the scored hour `as_of - lag`:

1. Freshness gate: completeness of every fact view; a table that goes late (or catches up) becomes a
   data-issue note, and nodes that read it are pending instead of scored.
2. Always-on looks: every north-star total and the series of every open anomaly, scored hour by hour, so a
   backlog left by a late table is caught up in order once it lands.
3. Attention: every other unit (node totals and breakdowns) gets an attention score and the top `budget`
   units are looked at, scoring the current hour only (see `argus.detect.attention`).
4. Rules: z_gt_open and two_of_three on every looked-at series, the pacing rule on every budget line.
   At most one anomaly is open per (node, direction); a slice that fires while its node already has an
   open anomaly in that direction is the same problem seen from another angle, and the coarsest firing
   segment wins (the investigator finds the root segment).
5. Resolve: an open anomaly closes after `calm_hours` calm hours of its own series.
6. Events (C5): attention, note_logged, anomaly_opened, then tick.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from pydantic import BaseModel

from argus.contracts.events import AttentionPayload, Event, TickPayload
from argus.contracts.findings import Anomaly, Direction, Note, Quantity, Segment
from argus.contracts.graph import Graph, NodeKind
from argus.detect.attention import AttentionBudget, Unit, watchable_nodes
from argus.detect.calendar import Calendar
from argus.detect.expectation import HOURS_PER_WEEK, Method, ScoreParams, SeriesScore, score_series
from argus.detect.freshness import FreshnessGate, FreshnessState
from argus.detect.pacing import LINE_DIMS, PACING_NODE, PLAN_NODE, SPEND_NODE, PacingParams, burn_scores, pacing_breach
from argus.detect.rules import RuleParams, Trigger, family_params, is_calm, open_trigger
from argus.detect.series import NodeSeries, SeriesStore, noise_drivers, source_tables
from argus.semantic.compile import hourly_sql, points_condition, quote, segment_where
from argus.semantic.runner import Runner, sql_ts

HOUR = timedelta(hours=1)
Emit = Callable[[datetime, BaseModel], None]
"""Event sink: receives (sim_ts, C5 payload) in emission order."""


@dataclass(frozen=True)
class WatcherConfig:
    lag_hours: int = 2
    budget: int = 6
    tail_hours: int = 24
    freshness_lookback_hours: int = 48
    score: ScoreParams = field(default_factory=ScoreParams)
    rules: RuleParams = field(default_factory=RuleParams)
    pacing: PacingParams = field(default_factory=PacingParams)

    @property
    def window_hours(self) -> int:
        """Hours of history behind one scored hour: baseline weeks + residual history + the rule tail."""
        return self.score.weeks * HOURS_PER_WEEK + self.score.history_hours + self.tail_hours


@dataclass(frozen=True)
class Look:
    """One series (a unit's slice) scored at one hour."""

    unit: Unit
    slice_key: str
    segment: Segment
    hour: datetime
    score: SeriesScore

    @property
    def z(self) -> float:
        return self.score.last_z


@dataclass
class OpenAnomaly:
    anomaly: Anomaly
    unit: Unit
    slice_key: str


@dataclass(frozen=True)
class Funnel:
    """Anodot-style funnel for one tick: series scored, wiggles ignored (|z| > 2), rule hits, anomalies."""

    series: int = 0
    wiggles: int = 0
    triggers: int = 0
    opened: int = 0

    def __add__(self, other: Funnel) -> Funnel:
        return Funnel(
            self.series + other.series,
            self.wiggles + other.wiggles,
            self.triggers + other.triggers,
            self.opened + other.opened,
        )


@dataclass
class TickReport:
    as_of: datetime
    hour: datetime
    tick: TickPayload
    attention: AttentionPayload
    looked: list[str]
    opened: list[Anomaly] = field(default_factory=list)
    resolved: list[Anomaly] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    funnel: Funnel = field(default_factory=Funnel)
    looks: list[Look] = field(default_factory=list)
    """Every series scored in this tick (for the UI's funnel and for calibration)."""

    def payloads(self) -> list[BaseModel]:
        """C5 payloads in emission order."""
        return [self.attention, *self.notes, *self.opened, self.tick]


class EventRecorder:
    """Minimal in-process sink: wraps payloads into numbered C5 events (the runtime bus does the same)."""

    def __init__(self, start_seq: int = 1):
        self.events: list[Event] = []
        self._next = start_seq

    def __call__(self, sim_ts: datetime, payload: BaseModel) -> None:
        self.events.append(Event.make(self._next, sim_ts, payload))
        self._next += 1


def _poisson_x(drivers: list[NodeSeries] | None, key: str) -> np.ndarray | None:
    """Sum of 1 / count over the driver counts of one slice (the counting-noise variance of ln(value))."""
    if drivers is None or any(key not in d.num.columns for d in drivers):
        return None
    total = np.zeros(len(drivers[0].hours))
    for d in drivers:
        counts = d.num[key].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            total = total + np.where(counts > 0, 1.0 / counts, np.nan)
    return total


def floor_hour(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def _method(graph: Graph, node_id: str) -> Method:
    node = graph.node(node_id)
    return "binomial" if node.kind is NodeKind.RATIO and node.unit == "share" else "log"


class Watcher:
    """Watches every node of the graph over a world; call `tick(as_of)` once per simulated hour."""

    def __init__(self, runner: Runner, graph: Graph, config: WatcherConfig | None = None, emit: Emit | None = None):
        self.runner = runner
        self.graph = graph
        self.config = config = config or WatcherConfig()
        self.emit = emit
        self.store = SeriesStore(runner, graph)
        self.attention = AttentionBudget(graph, config.budget)
        self.calendar = Calendar(runner)
        self.nodes = watchable_nodes(graph)
        self._tables = {n: source_tables(graph, n) for n in self.nodes}
        self.gate = FreshnessGate(
            runner, sorted({t for ts in self._tables.values() for t in ts}), config.freshness_lookback_hours
        )
        self.north_stars = [n.id for n in graph.north_stars() if n.id in self._tables]
        self.open: dict[tuple[str, Direction], OpenAnomaly] = {}
        self.anomalies: list[Anomaly] = []
        self.notes: list[Note] = []
        self.funnel = Funnel()
        self._cursor: dict[Unit, datetime] = {}
        self._pacing_ready = all(n in self._tables for n in (PACING_NODE, SPEND_NODE, PLAN_NODE))
        self._drivers = {n: d for n in self.nodes if (d := noise_drivers(graph, n))}
        self._anomaly_seq = 0
        self._note_seq = 0

    def update_graph(self, graph: Graph) -> None:
        """Adopt a new graph version (after edge tests or onboarding); keeps what attention has seen so far."""
        self.graph = graph
        self.store.graph = graph
        old = self.attention
        self.attention = AttentionBudget(graph, self.config.budget)
        self.attention.last_look.update(old.last_look)
        self.attention.last_abs_z.update(old.last_abs_z)
        self.nodes = watchable_nodes(graph)
        self._tables = {n: source_tables(graph, n) for n in self.nodes}
        self.north_stars = [n.id for n in graph.north_stars() if n.id in self._tables]
        self._drivers = {n: d for n in self.nodes if (d := noise_drivers(graph, n))}

    # ------------------------------------------------------------------ loop

    def run(
        self, start: datetime, end: datetime, open_incidents: Callable[[], int] | None = None
    ) -> Iterator[TickReport]:
        """Tick every hour with as_of from `start` to `end` (inclusive)."""
        as_of = floor_hour(start)
        while as_of <= end:
            yield self.tick(as_of, open_incidents() if open_incidents else 0)
            as_of += HOUR

    def tick(self, as_of: datetime, open_incidents: int = 0) -> TickReport:
        hour = floor_hour(as_of) - timedelta(hours=self.config.lag_hours)
        fresh = self.gate.check(as_of, hour)
        self.calendar.refresh(as_of)
        notes = self._freshness_notes(fresh)
        # held: some hour up to the scored hour is still incomplete, so the node waits to stay in order
        pending = sorted(n for n in self.nodes if not self._ready(n, fresh, hour))

        # 1. always-on: north-star totals and open anomaly series, with backlog
        always = sorted(
            {Unit(n) for n in self.north_stars} | {o.unit for o in self.open.values() if o.anomaly.rule != "pacing"},
            key=lambda u: u.key,
        )
        self._cursor = {u: h for u, h in self._cursor.items() if u in always}
        looks: list[Look] = []
        for unit in always:
            looks += self._look(unit, as_of, hour, fresh, backlog=True)

        z_now = {
            lk.unit.node: abs(lk.z) for lk in looks if lk.unit.is_total and lk.hour == hour and math.isfinite(lk.z)
        }

        # 2. attention over everything else
        open_nodes = {node for node, _ in self.open}
        held = set(pending)
        scores = {
            u: self.attention.terms(
                u, hour, z_now, 0.0 if u.node in held else fresh.confidence(self._tables[u.node], hour), open_nodes
            )
            for u in self.attention.units
            if u not in always
        }
        chosen = self.attention.choose(scores)
        for unit in chosen:
            looks += self._look(unit, as_of, hour, fresh, backlog=False)
        for unit in [*always, *chosen]:
            if unit.node in held:
                continue
            seen = [abs(lk.z) for lk in looks if lk.unit == unit and lk.hour == hour and math.isfinite(lk.z)]
            self.attention.mark(unit, hour, max(seen) if seen else None)

        # 3. rules
        opened, triggers = self._open_from_looks(looks, as_of, fresh)
        pacing_opened, pacing_triggers, pacing_resolved = self._pacing(as_of, hour, fresh)
        opened += pacing_opened
        resolved = self._resolve(looks) + pacing_resolved

        current = [lk for lk in looks if lk.hour == hour and math.isfinite(lk.z)]
        max_abs: dict[str, float] = {}
        for lk in current:
            max_abs[lk.unit.node] = max(max_abs.get(lk.unit.node, 0.0), round(abs(lk.z), 3))
        funnel = Funnel(
            series=len(current),
            wiggles=sum(1 for lk in current if abs(lk.z) > self.config.rules.onset_z),
            triggers=triggers + pacing_triggers,
            opened=len(opened),
        )
        self.funnel = self.funnel + funnel
        tick = TickPayload(
            as_of=as_of,
            hour=hour,
            freshness=fresh.table_freshness(self.gate.tables),
            scored_nodes=sorted({lk.unit.node for lk in looks if lk.hour == hour}),
            pending_nodes=pending,
            max_abs_z=dict(sorted(max_abs.items())),
            open_incidents=open_incidents,
        )
        report = TickReport(
            as_of=as_of,
            hour=hour,
            tick=tick,
            attention=AttentionBudget.payload(scores),
            looked=[u.key for u in [*always, *chosen]],
            opened=opened,
            resolved=resolved,
            notes=notes,
            funnel=funnel,
            looks=looks,
        )
        if self.emit:
            for payload in report.payloads():
                self.emit(as_of, payload)
        return report

    # ------------------------------------------------------------------ scoring

    def _series(
        self, node_id: str, dims: tuple[str, ...], end: datetime, as_of: datetime, fresh: FreshnessState
    ) -> NodeSeries:
        start = end - timedelta(hours=self.config.window_hours)
        return self.store.node_series(node_id, dims, start, end, as_of, fresh.settled_through)

    def _ready(self, node_id: str, fresh: FreshnessState, hour: datetime) -> bool:
        """Every hour up to `hour` of every table the node reads is complete."""
        return min(fresh.settled_through[t] for t in self._tables[node_id]) >= hour

    def _look(self, unit: Unit, as_of: datetime, hour: datetime, fresh: FreshnessState, backlog: bool) -> list[Look]:
        """Score a unit's slices at the hours it is due: the backlog for always-on units, else the scored hour."""
        last_ready = min(min(fresh.settled_through[t] for t in self._tables[unit.node]), hour)
        if backlog:
            first = self._cursor.get(unit, last_ready - HOUR) + HOUR
            first = max(first, last_ready - timedelta(hours=self.config.tail_hours - 1))
            hours = (
                [first + k * HOUR for k in range(int((last_ready - first) / HOUR) + 1)] if first <= last_ready else []
            )
        else:
            hours = [hour] if self._ready(unit.node, fresh, hour) else []
        if not hours:
            return []
        series = self._series(unit.node, unit.dims, hours[-1], as_of, fresh)
        method = _method(self.graph, unit.node)
        drivers = self._driver_series(unit, hours[-1], as_of, fresh) if method == "log" else None
        out: list[Look] = []
        n = len(series.hours)
        for key in series.slices():
            num, den = series.arrays(key)
            segment = series.segment(key)
            uplift = self.calendar.uplift(unit.node, segment, series.hours)
            poisson_x = _poisson_x(drivers, key)
            for h in hours:
                end = n - int((hours[-1] - h) / HOUR)
                score = score_series(
                    num[:end],
                    None if den is None else den[:end],
                    method,
                    tail=self.config.tail_hours,
                    uplift=None if uplift is None else uplift[:end],
                    params=self.config.score,
                    poisson_x=None if poisson_x is None else poisson_x[:end],
                )
                if score is not None:
                    out.append(Look(unit, key, segment, h, score))
        if backlog:
            self._cursor[unit] = hours[-1]
        return out

    def _driver_series(
        self, unit: Unit, end: datetime, as_of: datetime, fresh: FreshnessState
    ) -> list[NodeSeries] | None:
        drivers = self._drivers.get(unit.node)
        if not drivers or any(not set(unit.dims) <= set(self.graph.node(d).dims) for d in drivers):
            return None
        return [self._series(d, unit.dims, end, as_of, fresh) for d in drivers]

    # ------------------------------------------------------------------ rules

    def _open_from_looks(self, looks: list[Look], as_of: datetime, fresh: FreshnessState) -> tuple[list[Anomaly], int]:
        opened: list[Anomaly] = []
        triggers = 0
        for hour in sorted({lk.hour for lk in looks}):
            best: dict[tuple[str, Direction], tuple[Look, Trigger]] = {}
            at_hour = [lk for lk in looks if lk.hour == hour]
            family: dict[Unit, int] = {}
            for lk in at_hour:
                family[lk.unit] = family.get(lk.unit, 0) + 1
            for lk in at_hour:
                trig = open_trigger(lk.score.z, family_params(self.config.rules, family[lk.unit]))
                if trig is None:
                    continue
                triggers += 1
                key = (lk.unit.node, trig.direction)
                if key in self.open:
                    continue
                rank = (len(lk.segment), -abs(lk.z))
                if key not in best or rank < (len(best[key][0].segment), -abs(best[key][0].z)):
                    best[key] = (lk, trig)
            for key, (lk, trig) in sorted(best.items()):
                anomaly = self._make_anomaly(lk, trig.rule, trig.direction, trig.onset_index, as_of, fresh)
                self.open[key] = OpenAnomaly(anomaly, lk.unit, lk.slice_key)
                opened.append(anomaly)
        return opened, triggers

    def _resolve(self, looks: list[Look]) -> list[Anomaly]:
        resolved = []
        for key, item in list(self.open.items()):
            if item.anomaly.rule == "pacing":
                continue
            mine = [lk for lk in looks if lk.unit == item.unit and lk.slice_key == item.slice_key]
            if mine and is_calm(max(mine, key=lambda lk: lk.hour).score.z, self.config.rules):
                resolved.append(item.anomaly)
                del self.open[key]
        return resolved

    def _make_anomaly(
        self,
        look: Look,
        rule: str,
        direction: Direction,
        onset_index: int,
        as_of: datetime,
        fresh: FreshnessState,
    ) -> Anomaly:
        score = look.score
        node = self.graph.node(look.unit.node)
        tables = self._tables[node.id]
        receipts = []
        if rule == "pacing":
            receipts.append(self._pacing_receipt(look, as_of))
        else:
            weeks = [look.hour - k * timedelta(hours=HOURS_PER_WEEK) for k in range(self.config.score.weeks + 1)]
            sql = hourly_sql(self.graph, node.id, points_condition(weeks), look.segment)
            _, receipt = self.runner.query(
                sql,
                as_of,
                purpose=f"{node.id} {look.segment or 'total'}: scored hour and its same-hour-of-week baseline",
            )
            receipts.append(receipt.id)
        names = ", ".join(quote(t) for t in tables)
        _, fr = self.runner.query(
            "SELECT table_name, ts, SUM(share) AS completeness FROM log_ingestion "
            f"WHERE table_name IN ({names}) AND ts = {sql_ts(look.hour)} GROUP BY table_name, ts ORDER BY table_name",
            as_of,
            purpose=f"freshness of {', '.join(tables)} for the scored hour",
        )
        receipts.append(fr.id)
        self._anomaly_seq += 1
        anomaly = Anomaly(
            id=f"an_{self._anomaly_seq:04d}",
            node=node.id,
            segment=look.segment,
            direction=direction,
            hour=look.hour,
            detected_at=as_of,
            onset=look.hour + (onset_index + 1) * HOUR,
            observed=float(score.observed[-1]),
            expected=float(score.expected[-1]),
            band=(float(score.lo[-1]), float(score.hi[-1])),
            z=round(float(score.z[-1]), 3),
            rule=rule,  # type: ignore[arg-type]
            data_confidence=round(fresh.confidence(tables, look.hour), 4),
            receipts=receipts,
        )
        self.anomalies.append(anomaly)
        return anomaly

    # ------------------------------------------------------------------ pacing

    def _pacing(
        self, as_of: datetime, hour: datetime, fresh: FreshnessState
    ) -> tuple[list[Anomaly], int, list[Anomaly]]:
        if not self._pacing_ready:
            return [], 0, []
        if not (self._ready(SPEND_NODE, fresh, hour) and self._ready(PLAN_NODE, fresh, hour)):
            return [], 0, []
        start = hour.replace(hour=0) - timedelta(days=self.config.pacing.days)
        spend = self.store.node_series(SPEND_NODE, LINE_DIMS, start, hour, as_of, fresh.settled_through)
        plan = self.store.node_series(PLAN_NODE, LINE_DIMS, start, hour, as_of, fresh.settled_through)
        scores = burn_scores(spend, plan, tail=self.config.tail_hours, params=self.config.pacing)
        unit = Unit(PACING_NODE, LINE_DIMS)
        opened: list[Anomaly] = []
        resolved: list[Anomaly] = []
        triggers = 0
        key_open: tuple[str, Direction] = (PACING_NODE, "up")
        breaches = []
        for key, score in scores.items():
            onset = pacing_breach(score, hour, self.config.pacing)
            if onset is not None:
                triggers += 1
                breaches.append((Look(unit, key, spend.segment(key), hour, score), onset))
        current = self.open.get(key_open)
        if current is not None and current.anomaly.rule == "pacing":
            own = scores.get(current.slice_key)
            if own is not None and is_calm(own.z, self.config.rules):
                resolved.append(current.anomaly)
                del self.open[key_open]
        if breaches and key_open not in self.open:
            look, onset = max(breaches, key=lambda b: (float(b[0].score.observed[-1]), b[0].slice_key))
            anomaly = self._make_anomaly(look, "pacing", "up", onset, as_of, fresh)
            self.open[key_open] = OpenAnomaly(anomaly, unit, look.slice_key)
            opened.append(anomaly)
        return opened, triggers, resolved

    def _pacing_receipt(self, look: Look, as_of: datetime) -> str:
        day = look.hour.replace(hour=0)
        cond = f"ts BETWEEN {sql_ts(day)} AND {sql_ts(look.hour)} AND {segment_where(look.segment)}"
        sql = (
            f"WITH s AS (SELECT SUM(ad_spend) AS spend FROM fact_ads_hourly WHERE {cond}), "
            f"p AS (SELECT SUM(planned_spend) AS planned FROM fact_ad_plan_hourly WHERE {cond}) "
            "SELECT spend, planned, spend / NULLIF(planned, 0) AS burn FROM s CROSS JOIN p"
        )
        _, receipt = self.runner.query(sql, as_of, purpose=f"budget burn since 00:00 for {look.segment}")
        return receipt.id

    # ------------------------------------------------------------------ notes

    def _freshness_notes(self, fresh: FreshnessState) -> list[Note]:
        notes = []
        for table in fresh.went_late + fresh.caught_up:
            late = table in fresh.went_late
            hours = fresh.late_hours.get(table, [])
            start = hours[0] if hours else fresh.hour
            sql = self.gate.receipt_sql(table, start, fresh.hour)
            rows, receipt = self.runner.query(sql, fresh.as_of, purpose=f"delivery of {table}")
            affected = sorted(n for n, ts in self._tables.items() if table in ts)
            worst = min((float(r["completeness"] or 0.0) for r in rows), default=0.0)
            if late:
                reason = (
                    f"{table} is late: {len(hours)} h incomplete since {start:%Y-%m-%d %H:%M} "
                    f"(lowest completeness {worst:.0%}). Holding {', '.join(affected)} until it lands; "
                    "nothing is paged on partial data."
                )
            else:
                reason = f"{table} caught up; the held hours of {', '.join(affected)} are scored now."
            self._note_seq += 1
            note = Note(
                id=f"note_{self._note_seq:04d}",
                kind="data_issue",
                sim_ts=fresh.as_of,
                reason=reason,
                numbers=[Quantity(value=round(worst, 4), unit="share", receipt=receipt.id)],
                receipts=[receipt.id],
            )
            self.notes.append(note)
            notes.append(note)
        return notes


def summarize(anomaly: Anomaly) -> str:
    seg = ",".join(f"{k}={v}" for k, v in sorted(anomaly.segment.items())) or "total"
    return (
        f"{anomaly.id} {anomaly.node}[{seg}] {anomaly.direction} z={anomaly.z:+.1f} rule={anomaly.rule} "
        f"hour={anomaly.hour:%m-%d %H:%M} onset={anomaly.onset:%m-%d %H:%M} detected={anomaly.detected_at:%m-%d %H:%M} "
        f"observed={anomaly.observed:.4g} expected={anomaly.expected:.4g}"
    )
