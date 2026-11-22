# Lanes: how four people build in parallel

> Historical build plan. The rubric below describes the track. The first packages and ownership reflect the initial implementation plan. See the [README](../README.md) for current entry points.

Each lane owns a set of folders.
Agents and people change only files in their own lane; a contract change (`src/argus/contracts/`) needs the producer and the consumers to agree (see `docs/contracts.md`).
Every package of work ends with a named test and `make check` green.

| Lane | Rubric weight | Owns | Starts from |
| --- | --- | --- | --- |
| G Graph | 40% graph and self-extension | `graph/`, `metrics/`, `src/argus/graph/`, `src/argus/semantic/`, `src/argus/cartographer/` | seed graph with passing edge tests, `parse_metric` |
| W World and proof | foundation, demo | `src/mockmart/`, `src/bench/`, chaos and challenge routes | S1 with truth, the bench grader |
| B Brain | 40% autonomy | `src/argus/watcher/`, `src/argus/decompose/`, `src/argus/investigator/`, `src/argus/incidents/`, `src/argus/runtime/`, `src/argus/skeptic/`, `src/argus/llm/` | the fixed opening that solves S1 |
| U Surface and pitch | 20% demo | `web/`, `src/argus/api/`, `src/argus/narrator/`, `src/argus/mcp/` | API with SSE, fixtures, template report |

## What already works (use it, do not rebuild it)

- `make s1` runs the whole loop once and grades it: simulate, deliver late micro-batches, test edges, detect, investigate, file one incident, report, resolve.
- `uv run argus run --world <world.duckdb>` runs Argus on any world and writes `graph.json`, `incidents.json`, `notes.json`, `anomalies.json`, `receipts.json`, `events.jsonl` and markdown reports.
- `make demo` serves the live run over HTTP; `make api` replays `fixtures/` through the same SSE path.

## First packages per lane

### G Graph

1. Onboard metric definitions with parsing, a fan-out guard, candidate edges, formula and dimension checks, a `Certificate` and a `GraphChange`.
2. Expose placement through the API. See the [implemented graph extension](ext/graph-extension.md) for `POST /graph/metrics` and its recorded cases.
3. Cause edges: the lagged-correlation test with Benjamini-Hochberg for `cause` edges (`EdgeTestKind.LAGGED_CORR_BH` is defined, `EdgeTester` marks it not run).
4. Graph drift: a BROKEN edge already lands in the changelog; emit `graph_changed` events and a drift notice.

### W World and proof

1. S2 (planned budget increase, EXPECTED) and S3 (orders table stalls, DATA_ISSUE) in `src/mockmart/scenarios/`, each writing its truth in the same step as its data change.
   Hooks exist: `WorldParams.ad_budget` (budgets), `WorldParams.extra_delay_min[table]` (late batches), `log_calendar` rows with `planned_uplift`.
2. Bench graders for S2 and S3 next to `src/bench/s1.py`, plus `tests/e2e/test_s2.py` and `test_s3.py` (one test per exit criterion, three seeds).
3. S4 pacer bug: `WorldParams.ad_delivery` is the pacer's delivered/planned ratio per hour and budget line.
4. Chaos console and blind challenge routes (`POST /chaos/inject`, `/challenge/commit`, `/challenge/reveal`, `GET /bench/results` are 501 stubs owned by W).

### B Brain

1. EXPECTED: `planned_uplift` in `src/argus/watcher/detect.py` is a stub returning 0; read `log_calendar.planned_uplift` and add the band check in the calendar step of `src/argus/investigator/procedure.py`.
2. DATA_ISSUE path for S3: the freshness gate already marks nodes pending and logs one note; add the re-check after the backfill.
3. Mix vs rate verdict for S5 (`src/argus/decompose/mix_rate.py` is done and tested; wire it as the `mix_rate_split` tool).
4. Hypothesis ledger with the LLM planner (only C6 tools, prediction before query), then the skeptic.

### U Surface and pitch

1. Mission Control in `web/` against `fixtures/events.jsonl` first (see `web/README.md`), then live via `make demo`.
2. Incident page: report, LMDI bars, trail, receipt drawer with `POST /receipts/{id}/rerun` showing the matching hash.
3. LLM prose in `src/argus/narrator/` that must pass `unbacked_numbers`, with the template as fallback.

## Integration rules

- Build against fixtures and contracts until the producer lane lands its part.
- Re-record fixtures with `make fixtures` when a payload shape changes, in the same PR as the contract change.
- The bench is the integration test: a failing bench run becomes a test that reproduces it.
- Argus code never imports `mockmart` or `bench`, and never reads the truth (enforced by `tests/unit/test_boundaries.py`).
