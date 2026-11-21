# Demo API robustness

Run the socket-level suite and the startup profiler from the repository root with the locked development environment.

```sh
uv run pytest tests/robust -rx
uv run python -m scripts.robust.profile
```

The profiler writes JSON to stdout and accepts `--scenario s1`, `--mode live`, and `--repetitions 3` for narrower or repeated runs.
The suite launches the normal `argus api` CLI on an OS-assigned loopback port, generates live worlds in temporary directories, and uses no external APIs or LLMs (zero tokens).

Proposed one-line Makefile target for `make robust`.

```make
robust: ; uv run pytest tests/robust -rx
```

## HTTP contract

| Endpoint | What Mission Control can use |
| --- | --- |
| `GET /health` | `stream` identifies the current run, `last_seq` is its newest published event, and `run.finished` indicates completion. `run.position` counts events in replay and ticks in live mode. |
| `GET /graph` | Complete C3 `Graph`, including `version`, `nodes`, `edges`, and `logs`. Edge results can change after startup. |
| `GET /events?since=33&limit=1` | SSE history and tail. Each C5 event has a wire `id` matching its JSON `seq`. `limit` counts C5 events only. |
| `POST /replay` | `{"action":"end"}` advances the current run at full speed. `{"action":"pause"}` holds replay at its current position. `{"action":"restart"}` starts a new replay and returns HTTP 409 in live mode. |
| `GET /incidents`, `GET /notes` | C4 JSON snapshots of the run so far. Incident reports are Markdown at `GET /incidents/{id}/report`. |
| `GET /receipts/{id}`, `POST /receipts/{id}/rerun` | Receipt as C4 JSON. Rerun returns a `result_hash` in live mode and HTTP 409 when the replay has no world. |

The schemas define the full payloads. [C3 graph](../../contracts/c3_graph.schema.json), [C4 findings and receipts](../../contracts/c4_findings.schema.json), [C5 events](../../contracts/c5_events.schema.json)

### `GET /health` at the end of S1 replay

```json
{
  "status": "ok",
  "mode": "replay",
  "contract_version": "1.0.0",
  "stream": "e3a39710",
  "events": 173,
  "last_seq": 173,
  "sim_ts": "2026-11-23T01:00:00",
  "run": {
    "playing": false,
    "finished": true,
    "speed": 1.0,
    "position": 173,
    "total": 173,
    "sim_ts": "2026-11-23T01:00:00",
    "loop": true
  },
  "thresholds": {"alarm_z": 5.0, "pair_z": 3.5, "wiggle_z": 2.0},
  "source": "/path/to/argus/fixtures",
  "world_start": "2026-10-12T00:00:00",
  "rerun": false
}
```

### `GET /events?since=33&limit=1` during S1 replay

```text
event: edge_status
data: {"seq":34,"type":"edge_status","sim_ts":"2026-11-18T02:00:00","payload":{"edge":"b_pacing_ratio_country","old_status":null,"new_status":"VALID","result":{"ran_at":"2026-11-18T02:00:00","passed":true,"median_rel":null,"p95_rel":null,"max_rel_err":0.0,"hours":672,"receipts":["r55","r56"],"note":""}}}
id: 34
```

Save the health `stream` and last processed `seq` together.
On a dropped connection, refresh health and send `Last-Event-ID: <seq>` when the stream ID still matches.
When it changes, discard the old cursor and cached run state, reload the graph and snapshots, and reconnect from the start of the new stream.
A replay restart within one process can also send an SSE `stream` message with `data: {"stream":"7c9553ce","mode":"replay"}` and no `id`.
Apply the same state reset when that message arrives on an open connection.

## Demo matrix

Each scenario checks 120 consecutive simulated hours, a structurally complete graph, a contiguous event sequence, and the expected final API state.
Replay matches every recorded envelope and payload.
Live mode matches the recorded event types and simulated timestamps while independently verifying incidents, notes, and the evidence behind the incident verdicts.

| Scenario | Replay | Live | Events per mode | Observed story |
| --- | --- | --- | ---: | --- |
| Quiet | Pass | Pass | 154 | No anomaly, note, or incident |
| S1 | Pass | Pass | 173 | PayCo DE Android incident resolves and the holdout rules out the Android release |
| S2 | Pass | Pass | 163 | Planned spending change produces one `expected` note |
| S3 | Pass | Pass | 155 | Delayed data produces one `data_issue` note, holds scoring on orders, and recovers |
| S4 | Pass | Pass | 170 | Ad pacer deployment produces one `SUPPORTED_CAUSE` incident |
| S5 | Pass | Pass | 193 | Market-wide dip produces three `expected` notes; the checkout-routing fault produces one `SUPPORTED_CAUSE` incident that resolves |

## Fault injection

| Injection | Expected behavior | Result |
| --- | --- | --- |
| Close an SSE client after event 5 | `Last-Event-ID: 5` resumes at 6 and delivers all remaining events | Pass |
| Restart a replay with an old cursor | SSE emits a `stream` reset, then starts at the next process-wide sequence number | Pass |
| Kill the API with an SSE request open | Client sees the dropped response. New API advertises a different stream ID and serves from 1 after the client resets its cursor | Pass |
| Stall a client on an 8 MiB synthetic replay with a 64 KiB TCP receive buffer | Fast subscriber and REST complete first. Slow subscriber then drains the same sequence | Pass |
| Remove `events.jsonl` | CLI exits nonzero before listening and identifies the missing file | Pass |
| Corrupt JSON or send an invalid C5 event payload in the recording | CLI rejects the recording before listening | Pass |
| Duplicate a sequence number in the recording | CLI rejects the recording before listening and reports the order violation | Pass |
| Remove receipts from S1 | A replay with missing evidence should report degraded health | Expected failure. `/health` reports `ok` and the incident links to a receipt that returns HTTP 404 |

## Issues for triage

1. **Partial replay reports healthy.** Copy the S1 fixture without `receipts.json`, start `argus api --replay <copy>`, finish the replay, and open the incident's `findings.root.change_pct.receipt` link.
   The receipt returns 404 while health reports `ok`.
2. **Startup diagnostics omit the recording line.** A malformed second record exits before listen, but the CLI prints a parser traceback without identifying line 2 in `events.jsonl`.
   Report the recording path and line with a concise error so operators can repair the right record.
3. **An SSE cursor alone cannot survive a process restart.** Sequence numbers restart at 1 and `Last-Event-ID` carries only a number.
   A client that reconnects with an old ID without checking `/health` can silently skip events or wait for a larger sequence.

## Startup measurements

A fresh API subprocess starts at the default demo cadence with graph and SSE requests issued concurrently.
Timings start at process launch and stop when the client validates the first C5 event or receives and parses the full graph.
The profiler then advances the run at full speed and clocks receipt of the last event.
Peak RSS is the largest API process sample from listen through stream completion, polled every 100 ms with `ps`.
The measurements exclude world generation and browser rendering.

One run per row on an Apple Silicon Mac Studio with 32 GiB RAM, macOS 27.0.1, Python 3.13.16, and seed 1. All times are seconds from process launch.

| Scenario | Mode | First event (s) | Full graph (s) | Full stream (s) | Peak RSS (MiB) |
| --- | --- | ---: | ---: | ---: | ---: |
| Quiet | Replay | 0.780 | 0.782 | 0.818 | 105.0 |
| Quiet | Live | 1.697 | 1.791 | 9.605 | 313.1 |
| S1 | Replay | 1.027 | 1.029 | 1.070 | 106.2 |
| S1 | Live | 2.608 | 2.730 | 15.336 | 309.9 |
| S2 | Replay | 0.997 | 0.998 | 1.059 | 105.6 |
| S2 | Live | 1.539 | 1.597 | 7.627 | 317.0 |
| S3 | Replay | 0.703 | 0.704 | 0.737 | 105.9 |
| S3 | Live | 1.554 | 1.661 | 10.998 | 296.2 |
| S4 | Replay | 0.746 | 0.747 | 0.778 | 105.2 |
| S4 | Live | 1.671 | 1.743 | 9.178 | 302.2 |
| S5 | Replay | 1.029 | 1.032 | 1.080 | 108.6 |
| S5 | Live | 1.733 | 1.802 | 10.034 | 297.5 |
