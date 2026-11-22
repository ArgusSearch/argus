"""Rerunnable queries over the published event log and incident findings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote, urlencode

import duckdb
from pydantic import BaseModel

from argus.agent.types import ReceiptLink as AgentReceipt
from argus.contracts.events import Event
from argus.contracts.findings import Findings
from argus.semantic.runner import canonical_hash


class ReceiptLink(BaseModel):
    id: str
    source: Literal["semantic", "run", "agent"]
    href: str
    rerun_href: str | None
    rerun_method: Literal["GET", "POST"] | None


def semantic_link(receipt_id: str, prefix: str = "") -> ReceiptLink:
    href = f"{prefix}/receipts/{quote(receipt_id, safe='')}"
    return ReceiptLink(id=receipt_id, source="semantic", href=href, rerun_href=f"{href}/rerun", rerun_method="POST")


@dataclass(frozen=True)
class RunWindow:
    stream: str
    through_seq: int
    events: tuple[Event, ...]
    # Where the receipt and report-query routes are mounted: "" on the main API, "/demo" for demo playback.
    prefix: str = ""

    def link(self, query_id: str) -> ReceiptLink:
        scope = urlencode({"stream": self.stream, "through_seq": self.through_seq})
        href = f"{self.prefix}/report/morning/queries/{query_id}?{scope}"
        return ReceiptLink(id=query_id, source="run", href=href, rerun_href=href, rerun_method="GET")

    def semantic_link(self, receipt_id: str) -> ReceiptLink:
        return semantic_link(receipt_id, self.prefix)

    def agent_link(self, ref: AgentReceipt) -> ReceiptLink:
        path = "/".join(quote(part, safe="") for part in (ref.run_id, ref.world_revision, ref.receipt_id))
        href = f"/agent/receipts/{path}"
        return ReceiptLink(id=ref.key(), source="agent", href=href, rerun_href=None, rerun_method=None)

    def event_link(self, event: Event) -> ReceiptLink:
        return self.link(f"event-{event.seq}")


class Activity(BaseModel):
    since: datetime | None
    until: datetime | None
    ticks: int
    series_hours: int
    anomalies: int
    investigations: int
    incidents: int
    resolved_incidents: int
    expected_notes: int
    data_issue_notes: int
    suppressed_notes: int


class RunQueryResult(BaseModel):
    id: str
    stream: str
    through_seq: int
    sql: str
    parameters: dict[str, int]
    rows: list[dict[str, Any]]
    result_hash: str


_ACTIVITY_SQL = """
WITH current_incidents AS (
    SELECT
        payload->>'id' AS id,
        arg_max(payload->>'state', seq) AS state
    FROM events
    WHERE type = 'incident_updated'
    GROUP BY 1
)
SELECT
    min(CAST(payload->>'hour' AS TIMESTAMP)) FILTER (WHERE type = 'tick') AS since,
    max(CAST(payload->>'hour' AS TIMESTAMP)) FILTER (WHERE type = 'tick') AS until,
    count(*) FILTER (WHERE type = 'tick') AS ticks,
    coalesce(sum(json_array_length(payload, '$.scored_nodes')) FILTER (WHERE type = 'tick'), 0)
        AS series_hours,
    count(*) FILTER (WHERE type = 'anomaly_opened') AS anomalies,
    count(DISTINCT payload->>'anomaly_id')
        FILTER (WHERE type = 'investigation_step' AND payload->>'$.step.kind' = 'verdict') AS investigations,
    (SELECT count(*) FROM current_incidents) AS incidents,
    (SELECT count(*) FROM current_incidents WHERE state = 'resolved') AS resolved_incidents,
    count(*) FILTER (WHERE type = 'note_logged' AND payload->>'kind' = 'expected') AS expected_notes,
    count(*) FILTER (WHERE type = 'note_logged' AND payload->>'kind' = 'data_issue') AS data_issue_notes,
    count(*) FILTER (WHERE type = 'note_logged' AND payload->>'kind' = 'suppressed') AS suppressed_notes
FROM events
""".strip()

_EVENT_SQL = "SELECT seq, sim_ts, type, payload FROM events WHERE seq = $seq"
_FINDINGS_SQL = "SELECT seq, findings FROM published_findings WHERE seq = $seq"


def run_query(window: RunWindow, query_id: str, finding: tuple[int, Findings] | None = None) -> RunQueryResult | None:
    """Execute a named SELECT over the selected prefix, with no warehouse or network required."""
    parameters: dict[str, int] = {}
    events = window.events
    if finding is not None:
        sql = _FINDINGS_SQL
        parameters = {"seq": finding[0]}
    elif query_id == "activity":
        sql = _ACTIVITY_SQL
    elif query_id.startswith("event-") and (suffix := query_id.removeprefix("event-")).isascii() and suffix.isdecimal():
        # The same prefix can serve an individual record without materializing unrelated events.
        events = tuple(event for event in events if query_id == f"event-{event.seq}")
        if not events:
            return None
        parameters = {"seq": events[0].seq}
        sql = _EVENT_SQL
    else:
        return None

    with duckdb.connect(":memory:", config={"threads": 1}) as con:
        if finding is not None:
            seq, snapshot = finding
            con.execute("CREATE TABLE published_findings (seq BIGINT, findings JSON)")
            con.execute("INSERT INTO published_findings VALUES (?, ?)", [seq, snapshot.model_dump_json()])
        else:
            con.execute("CREATE TABLE events (seq BIGINT, sim_ts VARCHAR, type VARCHAR, payload JSON)")
            if events:
                records = [event.model_dump(mode="json") for event in events]
                con.executemany(
                    "INSERT INTO events VALUES (?, ?, ?, ?)",
                    [(e["seq"], e["sim_ts"], e["type"], json.dumps(e["payload"], sort_keys=True)) for e in records],
                )
        result = con.execute(sql, parameters)
        columns = [column[0] for column in result.description]
        rows = result.fetchall()
    records = [dict(zip(columns, row, strict=True)) for row in rows]
    json_column = "findings" if finding is not None else "payload"
    if json_column in columns:
        for record in records:
            record[json_column] = json.loads(record[json_column])
    return RunQueryResult(
        id=query_id,
        stream=window.stream,
        through_seq=window.through_seq,
        sql=sql,
        parameters=parameters,
        rows=records,
        result_hash=canonical_hash(rows),
    )


def measure_activity(window: RunWindow) -> Activity:
    result = run_query(window, "activity")
    assert result is not None  # The registry always contains the activity query.
    return Activity.model_validate(result.rows[0])
