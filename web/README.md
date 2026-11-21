# Mission Control

One page over the C5 event stream: the live metric graph, attention, the investigation, incidents with their reports, and receipts you can re-run.

## Run it

```sh
npm --prefix web install
npm --prefix web run build   # the API serves web/dist at /
make api                     # http://127.0.0.1:8000, replays the recorded S1 run
```

During development, run `make api` and `npm --prefix web run dev` (port 5173); Vite proxies the API routes to port 8000 (`ARGUS_API` overrides the target).

`npm --prefix web run typecheck` and `npm --prefix web test` check the page; `make test` runs both when `web/node_modules` exists.

## What it reads

| route | used for |
| --- | --- |
| `GET /events` (SSE) | everything live: ticks, attention, edge tests, anomalies, the trail, incidents, notes |
| `GET /graph` | the metric graph (nodes, typed edges, logs) |
| `GET /incidents/{id}` | the full findings behind an incident card |
| `GET /incidents/{id}/report` | the Markdown report ("Copy report") |
| `GET /receipts/{id}`, `POST /receipts/{id}/rerun` | the SQL behind a number, re-run at its pinned `as_of` |
| `GET /digest` | "While you slept" |
| `GET /health`, `POST /replay` | mode, replay position and controls |

The page folds the stream with one pure reducer (`src/lib/store.ts`), so a replay and a live run look the same.
When the stream id changes (a replay restart) the page drops its state and reconnects.

## Conventions the page relies on

- An investigation step may name what it touches in `step.data.focus = {nodes, edges, logs}`; the graph animates exactly those.
- `step.data.path` (segment step), `step.data.series` (impact step) and `Findings.decomposition` feed the report's segment path, chart and LMDI bars.
- A note whose reason says "symptom of INC-…" marks its node as a silenced symptom on the graph.
