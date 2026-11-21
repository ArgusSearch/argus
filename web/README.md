# Mission Control (lane U)

One page over the C5 event stream: the live metric graph, attention, the investigation, incidents with their reports, and receipts you can re-run.

## Run it

```sh
npm --prefix web install
npm --prefix web run build   # the API serves web/dist at /
make api                     # http://127.0.0.1:8000, replays the recorded S1 run in fixtures/
make api SCENARIO=s4         # another recorded run: quiet, s2, s3 or s4 (fixtures/<scenario>/)
make demo                    # the same page over Argus running live on a fresh S1 world
make demo SCENARIO=s3        # ... or a fresh world of any scenario
```

During development, run `make api` (or `make demo`) and `npm --prefix web run dev` (port 5173); Vite proxies the API routes to port 8000 (`ARGUS_API` overrides the target).

`npm --prefix web run typecheck` and `npm --prefix web test` check the page; `make web` installs, tests and builds it, `make check` includes it, and `make test` runs the checks when `web/node_modules` exists.

Receipts re-run in live mode (`make demo`), against the world the run reads.

## What it reads

| route | used for |
| --- | --- |
| `GET /events` (SSE) | everything live: ticks, edge tests, anomalies, the investigation, incidents, notes |
| `GET /graph` | the metric graph (nodes, typed edges, logs) |
| `GET /incidents/{id}` | the full findings behind an incident card |
| `GET /incidents/{id}/report` | the Markdown report ("Copy report") |
| `GET /receipts/{id}`, `POST /receipts/{id}/rerun` | the SQL behind a number, re-run at its pinned `as_of` |
| `GET /digest` | "While you slept" |
| `GET /health`, `POST /replay` | mode, thresholds, run position; play, pause, speed, restart (replay only) |

The page folds the stream with one pure reducer (`src/lib/store.ts`), so a replay and a live run look the same.
A replay restart starts a new stream whose seqs continue after the old one: the server sends `event: stream` and the page drops its state.
In live mode the server holds each investigation step of the live tail for a moment, so the walk is watchable; the history always arrives at full speed.

## Conventions the page relies on

- An investigation step may name what it touches in `step.data.focus = {nodes, edges, logs}`; without it, the page reads the focus from the step's own data (`path`, `events`, `event`, `node`, `identities`).
- `step.data.path` (segment step), `step.data.series` (impact step, optional) and `Findings.decomposition` feed the report's segment path, chart and LMDI bars.
- A note whose reason says "symptom of INC-…" marks its node as a silenced symptom on the graph.
- The wiggle and alarm lines come from `GET /health` (`thresholds`), which reads them from the watcher.
