# Demo playback API v1

Mission Control can start one 90-second run with `POST /demo/start` and follow its cues with `GET /demo/events`.
The server uses the checked-in S1 and S4 recordings of the Argus runtime.
S1 shows the PayCo failure and S4 shows the ad pacer overburn.

## Start and controls

`POST /demo/start` accepts `{"scenario":"s4","speed":1}`.
Both fields are optional and default to `s4` and `1`.
`scenario` accepts `s1` or `s4`.
`speed` is a finite number from `0.25` to `100`.

`GET /demo/state`, start, and the controls return the same state shape:

```json
{
  "version": 1,
  "run_id": "ea2441c2148e4382ba0703d8b8657318",
  "scenario": "s4",
  "status": "playing",
  "speed": 1.0,
  "elapsed_ms": 0,
  "duration_ms": 90000,
  "beat_index": 0,
  "beat_count": 9
}
```

Before the first start, `status` is `idle`, `elapsed_ms` and `beat_count` are zero, and `run_id`, `scenario`, `speed`, `duration_ms`, and `beat_index` are null.
After start, `status` is `playing`, `paused`, or `completed`.
Times are in milliseconds on the unscaled demo timeline.
At 2× speed, a 12,000 ms cue arrives in six wall-clock seconds of playback.
`beat_index` is the zero-based index of the most recent due beat.

Send `POST /demo/control` with `{"action":"pause"}`, `{"action":"resume"}`, `{"action":"skip"}`, or `{"action":"restart"}`.
Pause freezes elapsed time and resume continues from the same position.
Skip jumps to the next beat, keeps the playing or paused state, and completes the run if the last beat is current.
Restart plays the same scenario and speed from zero with a new run ID.
Starting again replaces the previous run.
The controls return HTTP 409 from idle, and only restart can change a completed run.
A single run is shared by all clients of one API process.

## Beat stream

Read the `run_id` from the start or state response and open `GET /demo/events?run_id=<run_id>`.
The connection delivers any already-due beats in order, then follows the clock.
Every `beat` SSE frame carries an ID of the form `<run_id>:<index>`.
Reconnect with the same URL and `Last-Event-ID` to receive only later beats.
A client creating a fresh connection to the current run can omit `run_id` and recover the full sequence of due beats.
The stream returns HTTP 409 before the first start and HTTP 204 for a replaced run.
Completion emits a `complete` event with the final state and closes the stream.
Close your EventSource when you get `complete`.
After a start or restart, open a new stream using the returned run ID.

```text
id: ea2441c2148e4382ba0703d8b8657318:2
event: beat
data: {"version":1,"run_id":"ea2441c2148e4382ba0703d8b8657318","scenario":"s4","index":2,"kind":"attention_shifts","title":"Attention shifts","at_ms":21000,"duration_ms":9000,"sim_ts":"2026-11-20T02:00:00","data":{"metric":"ad_spend","attention":null}}
```

`at_ms` is the start offset and `duration_ms` is the time until the next cue or completion.
`sim_ts` is a timestamp from the source recording.
Use `kind` to choose what to render and `data.phase` to distinguish investigation beats.

| At (ms) | Kind | Data |
| ---: | --- | --- |
| 0 | `quiet_world` | `tick`: preceding C5 tick event; `quiet_hours`: count of recorded ticks before detection |
| 12000 | `anomaly_appears` | `anomaly`: C5 anomaly event |
| 21000 | `attention_shifts` | `metric`: node receiving focus; `attention`: matching C5 attention event or null |
| 30000 | `investigation_steps` | `phase: "opening"`; `steps`: C5 investigation events for freshness, identity, and calendar |
| 40000 | `investigation_steps` | `phase: "localize"`; `steps`: C5 decomposition and segment investigation events |
| 50000 | `investigation_steps` | `phase: "hypotheses"`; `steps`: C5 candidate event investigation steps |
| 60000 | `evidence` | `steps`: C5 holdout, placebo, and impact investigation events |
| 72000 | `verdict` | `outcome`: C4 verdict; `decision`: C5 verdict event; `calendar_check`: C5 investigation event; `incident`: C4 incident snapshot at the verdict |
| 82000 | `morning_report` | `digest`: the existing Argus morning digest shape (title, since, until, lines, markdown) |

The verdict pairs the recorded calendar check with the resulting classification.
In both supported recordings the calendar check proceeds to an investigation, and the resulting verdict is `SUPPORTED_CAUSE`.
The morning digest folds the recording through the first scored 08:00 after detection.
The recorded attention score is optional.
A null value cues focus on the detected metric using the anomaly that Argus actually selected.

`GET /demo/graph?run_id=<run_id>` returns the scenario's C3 metric graph.
`GET /demo/receipts/<id>?run_id=<run_id>` returns a C4 receipt referenced by the graph or by a due beat.
A receipt that is absent or has yet to be revealed returns HTTP 404.
These routes return HTTP 409 before start or for a replaced run.

## Headless dry run

`uv run argus demo --scenario s4` prints the same cue timeline and exits immediately.
It supports `--scenario s1` and `--speed 2`.
The shared CLI registers the command in `src/argus/cli.py`, and the shared API mounts these routes in `src/argus/api/app.py`.

For a quick HTTP smoke test, start the API with `make api`, then run:

```sh
curl -sS http://127.0.0.1:8000/demo/start -H 'Content-Type: application/json' -d '{"scenario":"s4","speed":100}'
curl -NsS http://127.0.0.1:8000/demo/events
```
