"""Planned business events from `log_calendar`: they change the expectation instead of muting the metric.

A calendar row carries `planned_uplift = {node_id: relative uplift}` between `ts` and `end_ts` for its
`scope`. The uplift applies to a series when the event's scope covers the series' segment (every scope
dimension is pinned by the segment to one of the scope's values, and a global scope covers everything).
A series wider than the scope (the whole business during a DE-only promo) keeps its plain expectation:
the investigator then classifies the bump as EXPECTED with the calendar row as evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from argus.contracts.findings import Segment
from argus.semantic.runner import Runner


@dataclass(frozen=True)
class PlannedEvent:
    id: str
    start: datetime
    end: datetime
    scope: dict[str, list[str]]
    uplift: dict[str, float]

    def covers(self, segment: Segment) -> bool:
        return all(dim in segment and segment[dim] in values for dim, values in self.scope.items())


def _json(value: object) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value) if value else {}
    return dict(value)  # type: ignore[call-overload]


class Calendar:
    def __init__(self, runner: Runner):
        self.runner = runner
        self.events: list[PlannedEvent] = []

    def refresh(self, as_of: datetime) -> None:
        rows = self.runner.fetch("SELECT id, ts, end_ts, scope, planned_uplift FROM log_calendar ORDER BY ts", as_of)
        self.events = [
            PlannedEvent(
                id=str(r["id"]),
                start=r["ts"],
                end=r["end_ts"] or r["ts"],
                scope={k: [str(v) for v in vals] for k, vals in _json(r["scope"]).items()},
                uplift={k: float(v) for k, v in _json(r["planned_uplift"]).items()},
            )
            for r in rows
        ]

    def uplift(self, node_id: str, segment: Segment, hours: pd.DatetimeIndex) -> np.ndarray | None:
        """Relative planned uplift per hour for one series, or None when no event applies."""
        relevant = [e for e in self.events if node_id in e.uplift and e.covers(segment)]
        if not relevant:
            return None
        out = np.zeros(len(hours))
        for event in relevant:
            # an hour is inside the event when it overlaps [start, end)
            inside = (hours + pd.Timedelta(hours=1) > pd.Timestamp(event.start)) & (hours < pd.Timestamp(event.end))
            out = np.where(inside, (1.0 + out) * (1.0 + event.uplift[node_id]) - 1.0, out)
        return out
