# Morning report and autonomy

## Try it

Run `make api SCENARIO=s1 PORT=8000` in the repository root.
Advance the replay to the end and fetch the report.

```bash
curl -fsS -X POST http://localhost:8000/replay \
  -H 'Content-Type: application/json' -d '{"action":"end"}'
curl -fsS http://localhost:8000/report/morning
curl -fsS 'http://localhost:8000/report/morning?format=markdown'
curl -fsS http://localhost:8000/autonomy
```

Substitute `SCENARIO=s2`, `s3`, `s4`, or `s5` to see the other recordings.
Use `make demo SCENARIO=s1 SEED=1` for a live run with warehouse receipt re-runs enabled.

## GET /report/morning

Returns the run so far as JSON.
The report follows the live or replay position, starting at the first tick of this run.
`activity.since` and `activity.until` are inclusive monitoring data-hour bounds and are both null before the first tick.
`through_seq` is the last included event sequence, or the stream base before any events.
A tick is one simulated monitoring hour and a metric-hour is one metric scored during one tick.
An anomaly check may end as an expected change without creating an incident.
`investigations` counts distinct anomaly IDs with a published verdict, and `resolved_incidents` counts incidents whose latest published state is resolved.

Every entry in `lines` has at least one evidence link.
The `section` values are `happened`, `decided`, and `asks`.
Group by section and use `id` as the row key within the stream.
The nullable `incident_id` and `note_id` fields let the UI associate lines with their records.
An approval line describes a recommendation recorded in the investigation, which can predate resolution.
Published incident updates support state and verdict.
Business measurements and estimates use their original SQL receipts when available.

The Markdown in `markdown` has the same claim lines with clickable evidence.
`GET /report/morning?format=markdown` returns that string as `text/markdown`.
JSON is the default and remains available as `?format=json`.

Example S3 response excerpt after the orders loader stall.

```json
{
  "title": "While you slept",
  "stream": "a1b2c3d4",
  "through_seq": 155,
  "activity": {
    "since": "2026-11-18T00:00:00",
    "until": "2026-11-22T23:00:00",
    "ticks": 120,
    "series_hours": 831,
    "anomalies": 0,
    "investigations": 0,
    "incidents": 0,
    "resolved_incidents": 0,
    "expected_notes": 0,
    "data_issue_notes": 1,
    "suppressed_notes": 0
  },
  "lines": [
    {
      "id": "note:note_0001",
      "section": "decided",
      "text": "Data issue - fact_orders_hourly 21:00 is only 55% delivered at 23:00 (normal lag 2 h); dependent nodes are not scored until it arrives",
      "incident_id": null,
      "note_id": "note_0001",
      "receipts": [
        {
          "id": "event-128",
          "source": "run",
          "href": "/report/morning/queries/event-128?stream=a1b2c3d4&through_seq=155",
          "rerun_href": "/report/morning/queries/event-128?stream=a1b2c3d4&through_seq=155",
          "rerun_method": "GET"
        },
        {
          "id": "event-129",
          "source": "run",
          "href": "/report/morning/queries/event-129?stream=a1b2c3d4&through_seq=155",
          "rerun_href": "/report/morning/queries/event-129?stream=a1b2c3d4&through_seq=155",
          "rerun_method": "GET"
        }
      ]
    }
  ],
  "investigations": []
}
```

The full response also contains `activity_receipt`, a link for the structured activity counts, and `markdown`.
`investigations` contains the named playbook run for each visible investigation trail, including S2, which has no incident.

### Receipt links

- `source: "semantic"` opens the original C4 receipt at `GET /receipts/{id}`.
  Use `POST /receipts/{id}/rerun` with a live run or a replay backed by the matching world.
  A recording on its own can show the SQL and expected hash.
- `source: "run"` executes a read-only SQL query over the published C5 event prefix or the visible C4 findings.
  Use `GET /report/morning/queries/{id}?stream=…&through_seq=…` to inspect and re-run it.
  The response contains `id`, `stream`, `through_seq`, `sql`, `parameters`, `rows`, and `result_hash`.
  `activity` returns the summary counts. `event-{seq}` returns the exact event record.
  `findings-{seq}` returns the C4 findings the report used at that incident update, including the recorded recommendation.
  A run query needs no warehouse.
  It stays pinned as the stream advances and returns 404 if the run has restarted or the selected prefix or query is unavailable.
  For S3, the note event preserves the decision and the tick event provides the recorded completeness value.

## GET /autonomy

Returns `decides_alone` and `asks_first` as arrays of policy rules with stable `id` values, a `when` condition, and a `behavior` description.
`probation` contains visible graph nodes and edges marked PROBATION.
It identifies cases that need evidence or review before promotion.
Every bundled recording serves an empty list.
A node appears once metric onboarding places it on probation, for example `{"kind": "node", "id": "app_crash_rate", "status": "PROBATION"}`.
Actual recorded recommendations and uncertainty appear in the report's `asks` section.

Example response excerpt.

```json
{
  "decides_alone": [
    {
      "id": "defer_late_data",
      "when": "Required source data is incomplete.",
      "behavior": "Record a data issue and wait for complete data before scoring dependent metrics."
    }
  ],
  "asks_first": [
    {
      "id": "review_probation",
      "when": "A graph placement is ambiguous or an edge is supported only by correlation.",
      "behavior": "Keep it on PROBATION and ask for stronger evidence or a human decision before promotion."
    }
  ],
  "probation": [],
  "playbooks": [
    {
      "id": "revenue_drop",
      "name": "Revenue drop playbook",
      "steps": [
        {
          "id": "data_freshness",
          "label": "Data freshness",
          "question": "Did all source data arrive?"
        }
      ]
    }
  ]
}
```

### Playbook mapping

The registry uses the investigator's existing `ads_drop`, `ads_spike`, `revenue_drop`, `revenue_spike`, `traffic_drop`, and `traffic_spike` IDs.
Each registry entry lists all steps in order.
Join `investigations[].playbook_id` to `playbooks[].id` and join each `step_id` to its definition.
`trail_steps` lists the original `TrailStep.step` numbers within that anomaly's C5 investigation events or C4 findings trail.
Multiple trail steps can implement one named step.
Step status is `done` where trail entries exist, `pending` during an unfinished investigation, or `skipped` after a verdict.
`incident_id` is null when the investigation has not filed an incident or ended without one.

Example mapping excerpt for an in-progress investigation.

```json
{
  "anomaly_id": "an_0001",
  "incident_id": null,
  "playbook_id": "revenue_drop",
  "finished": false,
  "steps": [
    {"step_id": "data_freshness", "status": "done", "trail_steps": [1]},
    {"step_id": "identities", "status": "pending", "trail_steps": []}
  ]
}
```

## Demo playback

[Demo playback](demo.md) serves this report for its own recording at `GET /demo/report/morning`, linked from the morning-report beat.
The lines, playbooks and queries are the same; links start with `/demo/` instead of `/`.

## Optional narration

The deterministic path runs without a model or API credentials.
`argus.narrator.narration.MorningNarrator` is an optional prose adapter interface over the completed report.
Implementations return the model and input and output token counts for per-call logging.
A future caller must read provider keys from environment variables and preserve the verified claim text and receipts as the canonical output.
