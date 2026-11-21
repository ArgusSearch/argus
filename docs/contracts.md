# The six contracts

Four people build Argus in parallel.
They code against these contracts and against the recorded fixtures, not against each other's half-finished code.
The pydantic models in `src/argus/contracts/` are the single source of truth.
`make contracts` writes the JSON Schemas and `schema.sql` into `contracts/`; CI fails when they are stale.

**Changing a contract** needs the agreement of its producer and its consumers (table below).
Make the change in `src/argus/contracts/`, run `make contracts`, update the fixtures with `make fixtures` if their shape changed, and say so in the PR description.
Adding an optional field is cheap; renaming or removing one breaks other lanes.

| Id | Contract | Producer | Consumers |
| --- | --- | --- | --- |
| C1 | world tables | W (simulator) | G, B |
| C2 | metric definition | G (contributors) | all |
| C3 | metric graph | G | B, U |
| C4 | findings, receipts, notes, incidents | B | U, W (bench) |
| C5 | event stream and REST routes | U | all |
| C6 | investigation tools | B with G | B, U (MCP, planner) |

## C1 world tables

Source: `src/argus/contracts/world.py`, generated DDL: `contracts/schema.sql`, machine-readable: `contracts/c1_world.json`.

- Raw tables `raw_*` hold micro-batches with `batch` and `ingested_at`.
- Argus queries only the views `fact_*`, `log_*`, `log_events` and the table `dim_advertiser`.
  A view shows exactly the rows with `ingested_at <= getvariable('as_of')`, summed over batches.
- `ts` is the start of the hour, naive UTC.
- Dimensions are named and valued identically everywhere: `country` (DE, FR, UK, ES, NL), `platform` (android, ios, web), `channel` (organic, paid, email, direct), `category` (electronics, fashion, home, beauty, toys, grocery), `provider` (PayCo, CardHub, WalletGo), `advertiser_id` (adv_01 to adv_06).

| View | Grain | Measures |
| --- | --- | --- |
| `fact_funnel_hourly` | ts, country, platform, channel, category | sessions, product_views, carts, checkouts |
| `fact_payments_hourly` | ts, country, platform, provider | payment_attempts, payment_successes |
| `fact_orders_hourly` | ts, country, platform, channel, category | orders, gmv |
| `fact_ads_hourly` | ts, advertiser_id, country, platform | ad_impressions, ad_clicks, ad_spend, ad_conversions, attributed_gmv |
| `fact_ad_plan_hourly` | ts, advertiser_id, country | planned_spend |

Logs share `id, ts, kind, scope, description` (plus their own columns) and are unioned in `log_events`:

| View | kinds | extra columns |
| --- | --- | --- |
| `log_deploys` | deploy, release, config | service, version |
| `log_provider_status` | degraded, resolved, maintenance | provider |
| `log_calendar` | promo, holiday, campaign | end_ts, planned_uplift (JSON: node id to relative uplift) |
| `log_ad_budgets` | budget_set, budget_change, pacer_change | advertiser_id, country, daily_budget, pacer_version |
| `log_ingestion` | (loader log) | table_name, ts, batch, share; completeness of a table-hour = SUM(share) |

`scope` is a JSON object from dimension to a list of values, for example `{"platform": ["android"]}`.
A missing dimension means all values; `{}` means global.

Delivery: every live hour arrives in four batches (55, 25, 15, 5% of the events) 5, 20, 40 and 55 minutes after the hour ends.
The newest complete hour at `as_of = T` is therefore `T - 2h`.

The hidden truth is a separate `truth.duckdb` (`injected_events`, `world_params`) that only `src/bench/` reads.
`manifest.json` next to the world is public (world start and end, live start, delivery lag) and never names the scenario.

Reserved for later lanes (add them through a contract change): `fact_refunds_hourly`, `fact_app_health_hourly` (with `app_version`), `seller_type` on orders, `fact_rewards_hourly`, `log_experiments`, `log_purchase_orders`.

## C2 metric definition

Source: `src/argus/contracts/metric.py`, schema: `contracts/c2_metric.schema.json`, examples: `metrics/*.yml`.

```yaml
name: roas_by_advertiser
description: Return on ad spend per advertiser and country, attributed GMV per EUR of spend
sql: |
  SELECT ts, advertiser_id, country,
         SUM(attributed_gmv) / NULLIF(SUM(ad_spend), 0) AS value
  FROM fact_ads_hourly
  GROUP BY ALL
```

Exactly these three keys; the contributor never says where the metric goes.
Allowed SQL: one `SELECT` with `ts`, dimension columns and exactly one aggregated expression aliased `value` (`SUM`, `COUNT`, `+ - * /`, `NULLIF`, `CAST`), `fact_*` views joined with `JOIN ... USING`, `WHERE`, `GROUP BY`.
`parse_metric` rejects anything else with a reason and extracts tables, dimensions, numerator and denominator.
The fan-out guard (joins on fewer keys than a side's grain multiply sums) is the cartographer's job in Stage 2.

## C3 metric graph

Source: `src/argus/contracts/graph.py`, schema: `contracts/c3_graph.schema.json`, seed: `graph/seed_graph.yml`, example: `fixtures/graph.json`.

```json
{"id": "payment_success_rate", "kind": "ratio", "unit": "share", "north_star": true,
 "numerator": "payment_successes", "denominator": "payment_attempts", "dims": ["country", "platform", "provider"]}
```

```json
{"id": "f_cvr", "kind": "formula", "target": "cvr",
 "sources": ["view_rate", "cart_rate", "checkout_rate", "attempt_rate", "payment_success_rate"],
 "expr": "view_rate * cart_rate * checkout_rate * attempt_rate * payment_success_rate",
 "status": "VALID", "provenance": "seed",
 "test": {"kind": "identity_residual", "window_days": 28, "median_max": 0.005, "p95_max": 0.02},
 "last_test": {"ran_at": "2026-11-18T02:00:00", "passed": true, "median_rel": 0.0, "p95_rel": 2.2e-16, "hours": 672, "receipts": ["r3", "r4"]}}
```

- Node kinds: `additive` (SUM of one measure of one view), `ratio` (numerator and denominator are additive node ids), `derived` (reserved).
- Edge kinds: `formula` (exact, LMDI), `breakdown` (one dimension, children sum to the parent), `cause` (lagged, always only possible), `evidence` (a log attached to a node).
- Status: `VALID`, `SUPPORTED`, `PROBATION` (half weight), `PROPOSED` (zero weight), `BROKEN`.
- Every status change is a `GraphChange` in the changelog; `Certificate` is the placement certificate for onboarded metrics.

## C4 findings, receipts, notes, incidents

Source: `src/argus/contracts/findings.py`, schema: `contracts/c4_findings.schema.json`, examples: `fixtures/findings.json`, `fixtures/incidents.json`, `fixtures/receipts.json`.

- `Receipt`: `id`, self-contained `sql`, pinned `as_of`, canonical `result_hash`, `rows`, `ms`, `purpose`.
- `Quantity`: a number with its unit and receipt id. Every number shown to a human is a `Quantity`.
- `Anomaly`: node, segment, direction, scored hour, onset, observed, expected, band, z, rule, receipts.
- `Findings`: verdict, headline, window, observed change, root cause (node, segment, evidence), LMDI decomposition, impact, ruled out, still uncertain, explained and unexplained share, the trail, cost, suggested action.
- `TrailStep`: step, kind, C6 tool, hypothesis, prediction (written before the query), result, decision, why, receipts, structured data.
- `Note`: `expected`, `data_issue` or `suppressed` ("didn't wake you").
- `Incident`: id, fingerprint, title, verdict, state (`open`, `investigating`, `explained`, `monitoring`, `resolved`), root node and segment, severity in EUR, history of transitions, the findings.

Verdicts: `SUPPORTED_CAUSE`, `HYPOTHESIS`, `EXPECTED`, `DATA_ISSUE`, `UNEXPLAINED`.

## C5 event stream and REST routes

Source: `src/argus/contracts/events.py`, schema: `contracts/c5_events.schema.json` (also lists every route), example stream: `fixtures/events.jsonl`.

`GET /events` is Server-Sent Events; each message is one `Event`:

```
id: 42
event: investigation_step
data: {"seq": 42, "type": "investigation_step", "sim_ts": "2026-11-20T23:00:00", "payload": {...}}
```

Query parameters: `since=<seq>` (or the `Last-Event-ID` header) skips history, `limit=<n>` ends the stream after n events.

| type | payload | emitted |
| --- | --- | --- |
| `tick` | `TickPayload`: as_of, scored hour, freshness, scored and pending nodes, abs z per node, open incidents | every tick |
| `edge_status` | `EdgeStatusPayload`: edge, old and new status, test result | first test and every status change |
| `anomaly_opened` | `Anomaly` | when an anomaly opens |
| `investigation_step` | `InvestigationStepPayload`: anomaly id, `TrailStep` | live, step by step |
| `incident_updated` | `IncidentUpdatedPayload`: summary and change (opened, updated, state, reopened) | on every incident change |
| `note_logged` | `Note` | suppressed symptoms, data issues, expected changes |
| `attention`, `skeptic_step`, `graph_changed`, `bench_progress`, `challenge_state` | reserved models | by their owner lane later |

REST: `GET /health`, `GET /routes`, `GET /graph`, `GET /incidents`, `GET /incidents/{id}`, `GET /incidents/{id}/report`, `GET /notes`, `GET /receipts/{id}`, `POST /receipts/{id}/rerun`.
Stubs that answer 501 with their owner lane: `POST /metrics`, `POST /chaos/inject`, `POST /challenge/commit`, `POST /challenge/reveal`, `GET /bench/results`, `POST /incidents/{id}/feedback`.

## C6 investigation tools

Source: `src/argus/contracts/tools.py`, schema: `contracts/c6_tools.schema.json`, implementations: `src/argus/investigator/tools.py`.

No tool accepts free SQL; each returns a typed output plus the receipts of the queries it ran.
The LLM planner and the MCP server may only call these.

| Tool | Status |
| --- | --- |
| `check_freshness`, `check_identities`, `decompose_formula`, `segment_search`, `list_events`, `holdout_check` | implemented |
| `get_series`, `counterfactual_impact` | logic runs inside the investigator (root onset scan, impact step), typed wrapper pending |
| `mix_rate_split` | pure function in `src/argus/decompose/mix_rate.py`, tool wrapper pending (S5) |
| `placebo_test`, `lag_test` | pending (skeptic, cause edges) |
