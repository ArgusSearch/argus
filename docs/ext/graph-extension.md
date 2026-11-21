# Graph extension: a new metric places itself

A contributor writes a metric as a C2 YAML file with three keys: `name`, `description` and `sql`.
Argus works out on its own where the metric belongs in the running graph, and proves it.
The classifier (`src/argus/graph/classify.py`) does the work: lineage, the fan-out guard, the definition check, alias detection, candidate edges with tests, and a certificate.
This extension makes the classifier reachable while Argus runs, over HTTP, in live mode and in replay.

The routes are an extension router mounted by plain import, like `/demo` and `/counterfactual`.
They are not part of the frozen C5 route table, and `POST /metrics` stays a C5 stub.

## Routes

| Route | What it does |
| --- | --- |
| `POST /graph/metrics` | Place one metric in the running graph and return a `PlacementResult` |
| `GET /graph/metrics` | Every placement of the current stream, the `version` counter and the recorded demo pack |
| `GET /graph/metrics/{name}` | One placement of the current stream (404 when there is none) |

The body of `POST /graph/metrics` is the C2 metric as JSON, or the YAML file itself with `content-type: application/yaml`.
Every verdict, `REJECTED` included, returns 200 with a `PlacementResult`.
A body that is not a valid C2 metric returns 422.
409 means the placement cannot run here: a replay received a metric it has no recording of, or a recorded metric whose prerequisites are missing.
Posting the same metric (same name and SQL) twice returns the first placement and does not place it again.

```bash
curl -s localhost:8000/graph/metrics -H 'content-type: application/yaml' \
  --data-binary @fixtures/graph_extension/metrics/1_cost_per_impression.yml | jq .placed_as
# "EXACT"
```

To onboard the whole demo pack in order, run `uv run python -m argus.graph.extension post fixtures/graph_extension/metrics/*.yml` (add `--api URL` for another server).

## PlacementResult

| Field | Meaning |
| --- | --- |
| `placed_as` | `EXACT`, `NEW_DIMENSION`, `ALIAS`, `AMBIGUOUS` or `REJECTED` |
| `summary`, `definition` | The verdict in one sentence; the definition check (your SQL against Argus' compiled form) |
| `mode`, `world`, `as_of` | `live` or `recorded`; the world the classifier ran on; the data cut (the 28 complete days before it are tested) |
| `certificate` | C3 `Certificate`: what was tried, what passed, what is still uncertain, the edges added, the receipts |
| `node` | The new C3 node (`state` is `watching`, or `probation` when ambiguous); null for an alias or a rejection |
| `parents`, `alternatives` | Sources of the chosen decomposition of the node; equally simple decompositions kept aside |
| `candidates` | Every candidate edge with `lifecycle` (`proposed`, `tested`, `accepted`, `rejected`), its test `result` and the `verdict` |
| `added_edges` | The C3 edges that entered the graph |
| `repair` | For a join fan-out: the `factor`, the repaired `sql` and a unified `diff` |
| `cards` | Before/after cards for the UI (`classify_cards.Card`) |
| `changes` | The C3 changelog entries of the placement |
| `receipts` | Every query the placement ran (C4 `Receipt`) |
| `requires` | Nodes placed earlier that this placement relies on |

## Live and replay

In live mode (`make demo`), the classifier runs against the live world at the runtime's current `as_of`, under the runtime lock.
The placed graph replaces the runtime's graph the same way the daily edge re-test does, so the next re-test covers the new edges too.
The placement's changelog entries and edge tests are published on the event stream as C5 `graph_changed` and `edge_status` events.
`GET /receipts/{id}` serves the placement's receipts, and they re-run against the world.

A replay (`make api`) has no world.
It serves the recorded demo pack in `fixtures/graph_extension/`, matched by name and SQL, and adds the recorded node and edges to the replayed graph.
The replayer owns the event seq space, so a replay publishes no event for a placement.
Clients poll `GET /graph/metrics` and refetch `GET /graph` when `version` moves.
Recorded receipt ids carry the prefix `gx-`, and `GET /receipts/gx-…` serves them.
A replay restart starts a new stream and resets the graph, and the placements of the old stream are dropped.

## The demo pack

`fixtures/graph_extension/metrics/` holds five ad metrics built from fields the world already has.
Placed in file order on the S4 world, seed 1, at the first live tick:

| Metric | Verdict | Why |
| --- | --- | --- |
| `cost_per_impression` | `EXACT` | `ad_spend / ad_impressions = ctr × cpc` by lineage, residual 0.00 % over 672 h; it also splits `ad_spend = ad_impressions × cost_per_impression`; CPM is 1000 times this metric |
| `conversions_per_impression` | `EXACT` | It also factors `cost_per_impression = conversions_per_impression × cpa` |
| `revenue_per_conversion` | `EXACT` | `cpa × roas` by lineage |
| `revenue_per_impression` | `AMBIGUOUS` | Two equally simple parents fit exactly: the price path `cost_per_impression × roas` and the conversion path `conversions_per_impression × revenue_per_conversion`. The first is kept on probation at half weight, the second as a zero-weight alternative, and the node is on probation |
| `ad_spend_per_session` | `REJECTED` | The join of ads and funnel on `(ts, country, platform)` misses `advertiser_id` and `channel, category`, so the SQL as written is 6.72 times the true value. The repair diff aggregates each side before dividing |

`fixtures/graph_extension/placements.json` is the recording.
After changing the classifier, the pack or the world, re-record it:

```bash
make world SCENARIO=s4 SEED=1
uv run python -m argus.graph.extension record --world runs/s4-1/world.duckdb
```

`tests/graph_extension/test_api.py` re-records on a fresh world and fails when the checked-in recording is stale.

## Demo beat (for lane F)

Beat kind `new_metric_placed`, about 12 s, after the fault and the harmless change.

| Field | Content |
| --- | --- |
| `placements` | The five `PlacementResult`s of `load_recorded()` (from `argus.graph.extension`) in order |
| `highlight` | `["cost_per_impression", "revenue_per_impression", "ad_spend_per_session"]`: the EXACT, the AMBIGUOUS and the REJECTED one |
| `sim_ts` | `as_of` of the recording |

Narration: "A contributor drops five ad metrics into the repo. Nobody tells Argus where they go. Cost per impression lands exactly, CTR times CPC, with a lineage certificate. Revenue per impression fits two parents equally, price or conversion, so Argus keeps it on probation and says why. Ad spend per session double-counts rows 6.7 times, so Argus refuses it and attaches the fix."

On screen, Mission Control shows the "New metric placed" card (`web/src/graph-extension/`), and the new node appears in the graph and the tree.
In a replay, `POST /graph/metrics` with each pack file, about 1.4 s apart, drives the same screen.
The card's "Add the ad metric pack" button does the same.
