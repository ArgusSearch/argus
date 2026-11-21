# Argus — Autonomous Monitoring Built for Almedia (C8 build plan, v2)

**Track:** Eye of the System: Fully Agentic Monitoring (HackLab Berlin, sponsor: Almedia, €700)
**Deadline:** Sun 22 Nov 16:30. Submit by 16:00.
**Rubric:** 40% metric graph + automatic extension · 40% autonomous monitoring + investigation · 20% demo.

This document is written so that a teammate or an AI coding agent can build from it without asking. Section 13 holds direct rules for agents.

**What changed in v2:**
- The world now has an **advertising business with budget pacing**, which is Almedia's core money flow and also one of the track's own scenarios.
- A **scorecard** and a **blind test** prove the system works.
- When the fixed steps run out, the **LLM proposes the next hypothesis**, which makes the system more agentic. The math still checks every hypothesis.
- A section on **tailoring to Almedia**.

---

## 1. What we are building, in plain words

A robot analyst for a marketplace that also sells advertising. Nobody asks it anything. Every simulated hour it:

1. checks whether the data arrived complete (late data is a *data problem*, not a business problem);
2. checks whether a change was planned (a campaign or a budget increase is *expected*, not an incident);
3. otherwise follows a **map of how the business works** to the cause: for example, ad spend is running too fast because the pacer is ignoring its schedule;
4. writes a short report: what broke, how much money it costs, how sure it is, and what it ruled out;
5. tracks the problem until it is gone, without repeating alerts;
6. when someone adds a new metric (name + SQL), works out where it belongs on the map and checks that against history.

**The math finds the answers. The LLM writes the prose and suggests what to check next. It never makes up numbers.** That is the pitch: *"Argus shows its work, so a data team can trust it, and it knows when not to wake you."*

## 2. Why this plan

### 2.1 Simulation result
We scored 8 candidate concepts plus the earlier Argus vision doc with 3 simulated judges (data scientist, founder, AI-agent engineer) and ran 200k Monte Carlo trials (`strategy/`). The staged plan (C8) ranked first: it scored 8.67/10 when finished, with about a 70% chance of winning against 10 teams. The full Argus vision scored higher when finished, but had only about an 8% chance of being done in time.

The percentages are rough; the ranking is the reliable part. v2 adds the Almedia fit and the three upgrades on top. It was **not re-simulated**.

### 2.2 Why it fits Almedia
Almedia (Berlin, ad tech, runs **Freecash**) earns money from advertisers, mostly mobile game publishers and retailers, who pay when users complete actions in their apps. Users get rewards. They report a $1B revenue run rate and more than $500M paid out to users. Their daily concerns are ad spend and **budget pacing**, cost per action, ROAS, retention, payouts, **data quality and freshness**, and **fraud**. The earlier vision doc's research, not re-verified here, found 100M+ events a day, BigQuery, dbt and Datadog in their stack, and "anomaly detection" and "data quality framework" in their job ads.

So we:
- keep the **marketplace the brief asks for**, but make its **advertising side** first-class: advertisers, daily budgets, a pacing controller, CPA and ROAS;
- make the pacing bug a headline scenario: it is in the brief and it is Almedia's business;
- lead with *fewer false alarms* and *data freshness*, which are their pain points at their scale;
- speak their tooling: dbt-style metric YAML, BigQuery-style SQL, alerts formatted for Slack/Datadog.

## 3. Goals, non-goals, anti-goals

**Goals**
- The full loop runs on its own: observe → detect → investigate → report → track.
- Every number in a report can be traced to a query.
- Innocent changes (a planned budget increase, a planned promo, a mix shift) and data problems (late tables) are **not** reported as business incidents.
- A new metric, given only as name + description + SQL, places itself in the graph with validated links.
- A **scorecard** shows on randomized faults how often Argus finds the right cause.

**Non-goals**
- Real data, real infrastructure, authentication, scale.
- Covering all five scenarios from the brief.
- A chat interface. Nobody asks Argus questions.

**Anti-goals (would lose even if it technically works)**
- The LLM computes or invents numbers.
- One scripted demo: faults must have random start time, segment, and size.
- Alert spam: the same problem reported again every hour.
- A pretty UI over a shallow engine.
- Anything in the pitch about news or controversies around Almedia's apps. Stay on the engineering.

## 4. The world: MockMart (a marketplace with an ads business)

Hourly data. Six weeks of history (1,008 hours) plus a live clock that keeps adding hours.

**Dimensions**
- `country`: DE, FR, UK, ES, NL
- `platform`: android, ios, web
- `category`: electronics, fashion, home, beauty
- `provider` (payments only): PayCo, CardHub, WalletGo
- `advertiser_id` (ads only): 6 advertisers, each with a daily budget per country

**Shop funnel, built bottom-up so the formulas hold by construction:**

```
sessions → product_views → carts → checkouts → payment_attempts → payment_successes (= orders) → gmv = orders × aov
```

**Ads funnel, built the same way:**

```
ad_impressions → ad_clicks (ctr) → ad_spend = ad_clicks × cpc → ad_conversions (= attributed orders)
cpa = ad_spend / ad_conversions        roas = attributed_gmv / ad_spend
pacer: each advertiser's planned spend for each hour = daily_budget × the expected share of daily traffic in that hour
```

Ad clicks bring sessions with `channel = ads`. Each funnel step is a binomial draw from the step before it. Rates have a daily and weekly shape plus noise.

**Tables (DuckDB, BigQuery-style SQL):**

```sql
fact_funnel_hourly   (ts, country, platform, category, channel, sessions, product_views, carts, checkouts)
fact_payments_hourly (ts, country, platform, provider, attempts, successes)
fact_orders_hourly   (ts, country, platform, category, orders, gmv)
fact_ads_hourly      (ts, advertiser_id, country, platform, impressions, clicks, spend, conversions, attributed_gmv)
dim_advertiser       (advertiser_id, country, daily_budget, pacer_version)
event_log            (ts, kind, scope_json, description, planned BOOLEAN, expected_uplift DOUBLE)
                     -- kind: deploy | promo | budget_change | provider_status | holiday
ingestion_log        (table_name, ts, loaded_at, completeness DOUBLE)   -- 0..1 per table-hour
```

**Observation layer:** recent hours arrive late (normal lag 1–2 h). During a data fault, a table can stay partial for several hours. Argus sees only these tables.

**Hidden ground truth:** `truth.duckdb` records every injected fault and innocent change with exact start, segment, and size. **Argus code never reads it.** Only `bench/` (the scorecard) reads it.

**Scenarios. Each takes random start, size and seed parameters:**

| ID | Kind | What happens | What Argus must conclude | Stage |
|---|---|---|---|---|
| S1 | fault | PayCo success rate for android in DE drops from about 95% to about 68%. In the **same hour** the android app 8.3.0 is released in **all** countries (red herring). This is the track brief's own example. | SUPPORTED CAUSE: PayCo failure in DE-android. Release ruled out, because android in other countries is normal. | 1 |
| S2 | innocent | A planned budget increase (+40%) for a big advertiser in FR, logged in `event_log`. Spend and clicks rise as planned. | EXPECTED, no page. If delivery is far below plan, report "campaign underdelivering its plan". | 1 |
| S3 | data | `fact_orders_hourly` stalls for 3 h (completeness < 0.5). Payments stay normal. | DATA ISSUE, not a business incident. The identity orders = payment_successes is broken. Re-check after the backfill. | 1 |
| **S4** | **fault (Almedia)** | Pacer v1.7 is deployed for DE and FR advertisers and stops respecting the hourly schedule. Their daily budgets are spent by about 10:00. Daily total spend looks normal; the intraday shape does not. | SUPPORTED CAUSE: pacer v1.7. "Traffic increased" ruled out, because sessions and impressions per session are normal. Holdout: advertisers still on the old pacer are normal. Impact: afternoon conversions lost, CPA up. | 2 |
| S5 | innocent | Traffic surge from ES, which converts worse. Blended conversion falls, but each country's own rate is flat (Simpson's paradox). | EXPECTED: mix shift. | 3 |
| S6 | fault (Almedia, stretch) | Click fraud: one advertiser's clicks jump from a single platform/country while conversions stay flat. | HYPOTHESIS "invalid traffic", with CTR and conversion-rate evidence. Suggest holding that traffic source, pending human approval. | 3, only if time |

## 5. The metric graph

### 5.1 Schema (`graph.json`, versioned: every change appends to `graph_changelog.jsonl`)

```json
{
  "nodes": [
    {"id": "orders", "kind": "additive", "table": "fact_orders_hourly", "sql": "SUM(orders)",
     "dims": ["country", "platform", "category"], "north_star": true},
    {"id": "cvr", "kind": "ratio", "numerator": "orders", "denominator": "sessions",
     "dims": ["country", "platform", "category"]},
    {"id": "budget_burn", "kind": "ratio", "numerator": "cum_ad_spend", "denominator": "cum_planned_spend",
     "dims": ["advertiser_id", "country"], "north_star": true}
  ],
  "edges": [
    {"id": "e1", "type": "formula", "to": "orders", "from": ["sessions", "cvr"], "expr": "sessions * cvr",
     "test": {"kind": "identity_residual", "median_max": 0.005, "p95_max": 0.02},
     "status": "valid", "confidence": 1.0, "last_test": {"ts": "...", "median": 0.0001, "p95": 0.0004}},
    {"id": "e2", "type": "breakdown", "to": "orders", "dim": "country",
     "test": {"kind": "children_sum", "max_rel_err": 0.005}, "status": "valid"},
    {"id": "e3", "type": "cause", "from": "ad_clicks", "to": "sessions", "lag_hours": [0, 1],
     "test": {"kind": "lagged_corr_bh", "alpha": 0.05}, "status": "supported", "confidence": 0.8},
    {"id": "e4", "type": "evidence", "source": "event_log", "filter": {"kind": "deploy"},
     "attaches_to": ["payment_success_rate", "budget_burn", "sessions"]}
  ]
}
```

### 5.2 Link types

| Type | Meaning | Its test | Used for |
|---|---|---|---|
| **formula** | Parent = arithmetic of children (`ad_spend = ad_clicks × cpc`) | Identity holds on history: median relative residual < 0.5%, p95 < 2% | Exact split of a change (LMDI, §6.4) |
| **breakdown** | Parent split by a dimension | Children sum to the parent. For ratios, numerator and denominator are each additive. | Finding the segment (§6.5) |
| **cause** | X can drive Y with a lag | Lagged correlation on de-seasonalised residuals, both directions, Benjamini–Hochberg corrected | Next hop when formulas run out |
| **evidence** | A log of state changes attached to the nodes it can affect | Onset alignment + segment match (§6.6) | Finding first causes |

**Status values:** `valid` / `supported` (passed its test), `probation` (new or ambiguous: monitored, half weight), `proposed` (LLM suggestion only: zero weight in attribution), `broken` (test stopped passing).

### 5.3 Edges are contracts

Argus re-runs every formula and breakdown test on each new day of data. A failing test sets `status = broken` and raises a **graph drift** notice. A broken identity also feeds detection: in S3, `orders = payment_successes` stops holding. That tells Argus the drop is a data problem, not a business problem.

### 5.4 Seed graph (hand-written at the start, about 22 nodes)

```
Shop:  gmv = orders × aov
       orders = sessions × cvr
       cvr = view_rate × cart_rate × checkout_rate × payment_success_rate
       payment_success_rate — breakdown by provider
       orders, sessions, gmv — breakdown by country, platform, category, channel
Ads:   ad_spend = ad_clicks × cpc
       ad_clicks = ad_impressions × ctr
       ad_impressions = sessions × impressions_per_session
       budget_burn = cum_ad_spend / cum_planned_spend      (pacing health)
       cpa = ad_spend / ad_conversions ;  roas = attributed_gmv / ad_spend
       ads metrics — breakdown by advertiser_id, country, platform
Links: cause ad_clicks → sessions[channel=ads]
       evidence event_log(deploy, promo, budget_change, provider_status, holiday), ingestion_log, dim_advertiser.pacer_version
```

## 6. The algorithms

These are the Stage 1 versions: simple, but statistically sound. Do not upgrade any of them until Stage 3 is green.

### 6.1 Tick loop (one tick = one simulated hour; the demo runs at about 1 sim-hour per 2 s)

```
for each tick:
    freshness_gate()              # 6.2
    for node in monitored nodes:  # north-star nodes every tick; children only when a parent is anomalous
        score(node)               # 6.3
    for anomaly not yet covered by an open incident:
        investigate(anomaly)      # 6.4-6.8
    update incident lifecycle     # 6.9
```

North-star nodes: `orders`, `gmv`, `sessions`, `cvr`, `payment_success_rate`, `ad_spend`, `budget_burn`, `cpa`.

### 6.2 Freshness gate

If any source table of a node has `completeness < 0.8` for the current hour, the node is not scored for that hour; the hour is marked `pending`. A drop that only appears on pending data becomes a DATA ISSUE notice, never a business alert. The gate also checks the formula identities from §5.3.

### 6.3 Expected value and detection

```
expected  ŷ_t = median(y_{t−168k}, k = 1..4) × (1 + planned_uplift_t)    # same hour of week, last 4 weeks
residual  r_t = y_t − ŷ_t
counts:   z_t = r_t / (1.4826 · MAD of residuals at this hour of week)     # robust z
rates:    z_t = (p̂ − p_exp) / sqrt(p_exp (1 − p_exp) / n)                  # binomial z
open:     |z| > 4, or 2 of the last 3 hours |z| > 3
resolve:  3 consecutive hours with |z| < 2
onset:    first hour of the run where |z| > 2 (used by the cause tests)
pacing:   budget_burn > 1.5 before 12:00 local time opens a pacing anomaly, even if total daily spend looks normal
```

Planned events from `event_log` **change the expectation**; they do not mute the metric. A campaign that delivers far below its plan is itself an alert.

### 6.4 Split along formulas (LMDI, exact, zero residual)

For a product `Y = x₁ · x₂ · … · xₙ` between a baseline (0) and the current window (1):

```
contribution_i = L(Y¹, Y⁰) · ln(x_i¹ / x_i⁰),   where L(a, b) = (a − b) / (ln a − ln b)
Σ contribution_i = Y¹ − Y⁰ exactly
```

Argus follows the child with the largest |contribution| share and repeats until it reaches a node with no formula children.

Worked example from S4:
- `ad_spend` is up in the morning.
- LMDI: `cpc` is flat, `ad_clicks` is up.
- `ad_clicks` → `impressions` up while `ctr` is flat.
- `impressions` → `sessions` is flat while `impressions_per_session` is up, so **traffic did not increase; the ads system served more**.

### 6.5 Find the segment (mix vs rate + Adtributor-lite)

For a ratio `Y = Σ_k w_k · r_k` (w = segment share, r = segment rate), using midpoint averages:

```
ΔY = Σ_k Δw_k · r̄_k   (mix)   +   Σ_k w̄_k · Δr_k   (rate)        # exact
```

- If mix dominates and every segment's rate is flat (|z| < 2), the verdict is **EXPECTED: mix shift** (S5).
- Otherwise, for each single dimension value v: explanatory power `EP_v = (actual_v − expected_v) / (actual − expected)`.
- Pick the smallest set of values (at most 3) whose EP sums to ≥ 0.67. Prefer one dimension over two, and single values over pairs.
- Then repeat once inside the chosen slice on the remaining dimensions, which gives depth 2: `country = DE ∧ platform = android`.

### 6.6 Test causes: is this a symptom or a first cause?

A node or segment is a **first-cause candidate** only when all three hold:

1. It is anomalous **after** accounting for its parents: the formula residual is anomalous, or for a leaf, its own z.
2. Its onset is at or before the symptom's onset.
3. It lines up with an **event**: an `event_log` row (or a `dim_advertiser.pacer_version` change) with `ts` in [onset − 2 h, onset] whose scope covers the anomalous segment.

**Holdout check, which rejects red herrings:** take the event's scope minus the anomalous segment. If that holdout is normal (|z| < 2), the event does **not** explain the pattern. Conversely, a group the event did *not* touch should be normal if the event is the cause. In S4, advertisers still on the old pacer are normal.

- **S1:** the android 8.3.0 release covers android in every country. Android in FR/UK/ES/NL is normal, so the release is rejected. Only PayCo is down, so the provider failure is supported.
- **S4:** pacer v1.7 covers DE/FR advertisers. Exactly those are over-burning, while advertisers on the old pacer are normal, so the cause is supported.

### 6.7 When the fixed steps run out: the LLM proposes, the math checks

If §6.4–6.6 leave more than 20% of the change unexplained and no candidate remains, Argus asks the LLM for up to 3 new hypotheses. It gives the LLM the graph neighbourhood, the trail so far and the event log, and asks for JSON only. Each hypothesis must name a **typed check** from a fixed menu:

```
query_metric(node, segment, window) · decompose(node) · localize(node, dims) · event_lookup(kind, scope, window)
lag_test(x, y) · holdout(event_id)
```

Before each check runs, Argus writes the hypothesis and its prediction into the trail. Deterministic code runs the check, and the result is marked `validated` / `refuted` / `inconclusive`. The LLM picks *what to check*; it never produces a number or a verdict. Budget: 3 hypotheses per incident. Without an API key this step is skipped and the remainder is reported as UNEXPLAINED.

### 6.8 Verdicts and stopping rule

| Verdict | Rule |
|---|---|
| **SUPPORTED CAUSE** | Passes the first-cause test **and** the holdout check, and explains ≥ 20% of the change |
| **HYPOTHESIS** | Consistent but not confirmed. The report says which evidence would upgrade it. |
| **EXPECTED** | A planned event inside its expected band, or an innocent mix shift. Logged under "didn't wake you". |
| **DATA ISSUE** | Freshness or identity failure. Re-checked after the backfill. |
| **UNEXPLAINED** | The remainder after stopping, stated as a number rather than hidden |

**Stop** when the selected explanations cover ≥ 80% of the change, **or** no open candidate is worth more than 5% of the change, **or** after 12 steps.

Every step is appended to the incident's **trail**: `{step, action, hypothesis, prediction, query_sql, result_summary, decision, why}`. The SQL is the "receipt".

### 6.9 Incident lifecycle (no alert spam)

- **Fingerprint** = (root-cause node, segment, direction). A repeat firing updates the open incident instead of creating a new one.
- Child symptom alerts are silenced while their parent cause is open.
- States: `open → investigating → explained → monitoring → resolved`. An incident reopens if it fires again within 24 h.
- Severity = cumulative € impact against the expected value, not z.

### 6.10 Report

The LLM receives **only** the structured findings JSON (verdicts, numbers, trail) and writes the prose. A check extracts every number from the text. If any number is not in the JSON, the report fails and Argus falls back to a template report. If the LLM API is down, Argus uses the template report.

Report sections: What happened · Impact (€, orders, wasted ad budget) · Where the change came from (contribution split) · Ruled out · Still uncertain · Suggested action (requires human approval) · Investigation trail. The output is also posted in Slack/Datadog webhook format; printing the payload is enough.

## 7. Automatic extension: new metric onboarding (Stage 2)

The contributor provides only a dbt-style YAML file. They never say where the metric goes.

```yaml
# metrics/refund_rate.yml
name: refund_rate
description: Share of orders refunded within the hour
sql: |
  SELECT ts, country, category,
         SUM(refunds)::DOUBLE / NULLIF(SUM(orders), 0) AS refund_rate
  FROM fact_refunds_hourly JOIN fact_orders_hourly USING (ts, country, category)
  GROUP BY ALL
```

**Pipeline**

1. **Parse** with `sqlglot`: tables, columns, aggregates, GROUP BY dimensions, column lineage.
2. **Propose candidate links** in three ways:
   - lineage overlap with existing nodes;
   - brute-force arithmetic over related nodes (`a·b`, `a/b`, `a+b`, `a−b`);
   - an LLM call that returns typed edges as JSON, using the description.
3. **Check formulas** on 28 days of history. A candidate is exact if the median residual is < 0.5%.
   - If several fit, the simplest wins. The others are stored as alternatives, and the edge gets `probation` with an AMBIGUOUS flag.
   - A near-constant ratio to an existing metric means the metric is an **alias**, not a new node.
4. **Check dimensions:** rewrite the SQL with an extra `GROUP BY dim` and confirm the parts sum to the total.
5. **Test causes:** lagged correlation on residuals, lags 0–6 h, both directions, BH-corrected. Links backed only by the LLM stay `proposed` with zero weight.
6. **Register** the node with a **placement certificate**: what was tried, what passed, what remains uncertain. Append it to the changelog. Monitoring starts at the next tick.

**Three demo metrics:**

| Metric | Expected outcome |
|---|---|
| `roas_by_advertiser` (Almedia-flavoured) | EXACT: placed as `attributed_gmv / ad_spend`. Inherits the advertiser and country breakdowns. |
| `gmv_by_seller_type` | New BREAKDOWN: discovers dimension `seller_type` (1P/3P). The parts sum to `gmv`. |
| `app_crash_rate` | AMBIGUOUS: steps up in the same hour as the S1 release. Gets only a `probation` cause edge, and the certificate says "correlated, not causal for the payment incident". |

## 8. The three stages, with exit criteria

Rule: **do not start a stage until the previous stage's exit criteria pass.** If a checkpoint passes with a stage still red, cut the rest of that stage and polish what works.

### Stage 0 — Contracts (Sat ~12:00–13:00)
Agree on the table schemas (§4), `graph.json` (§5.1), the event-stream schema (§10.2) and the repo layout (§10.3). Create the repo skeleton. After this, all streams can build in parallel.

### Stage 1 — The loop (checkpoint: Sat 23:00)
- Simulator with 6 weeks of history for **both the shop and the ads tables**, plus the live clock, plus S1, S2, S3.
- Seed graph with edge tests.
- Freshness gate, detection, LMDI, segment finder, cause tests with holdout, verdicts, stopping rule, incidents, template report.
- A simple web page that lists incidents with their trails.
- `bench/run.py` replays S1–S3 on random seeds and prints the scorecard (§9).

**Exit criteria (all must pass on 3 random seeds):**
- S1 → SUPPORTED CAUSE "PayCo, DE-android"; the release is listed under "Ruled out".
- S2 → EXPECTED, no incident opened.
- S3 → DATA ISSUE, no business incident.
- No alerts during 48 quiet simulated hours.
- The same incident is not reported twice.

**At this point we have a submittable project.**

### Stage 2 — Almedia scenario + self-extension (checkpoint: Sun 06:00), in this order
1. **S4 pacing bug.** The ads data already exists, so this step only injects the fault and adds its test.
2. Onboarding pipeline (§7) + edge re-testing (§5.3) + graph changelog.
3. LLM report writing with the number check (§6.10) + LLM hypothesis proposals (§6.7).

**Exit criteria:**
- S4 → SUPPORTED CAUSE "pacer v1.7, DE/FR"; "traffic increase" is ruled out; the report states the wasted budget and the CPA change.
- The 3 demo YAMLs place as in the §7 table, each with a certificate.
- A broken identity raises a drift notice.
- Reports pass the number check.

### Stage 3 — Live show (checkpoint: Sun 12:00, freeze 13:00)
- Mission Control UI:
  - the live graph, colored by state;
  - the investigation walk, animated hop by hop;
  - the incident feed, including "noticed but didn't wake you" entries;
  - a trail panel with receipts;
  - the scorecard panel.
- Chaos console with:
  - one button per scenario;
  - **"Random hidden problem"**, the blind test (§9);
  - "Drop metric YAML".
- Then S5 (Simpson's paradox).

**Only if all of that is green**, in this order: S6 click fraud → attention heat overlay on the graph.

### Sun 13:00–16:00 — Ship
Record the 3-minute video, make slides including the Almedia slide (§12), write the README (architecture, algorithms, how to run, scenario docs), make the repo public, submit by 16:00.

## 9. Proof: scorecard and blind test

**Scorecard (`bench/run.py`).** The script replays every built scenario N times with random start, segment, size and seed. It compares Argus's verdicts with `truth.duckdb` and prints:

| Measure | Meaning |
|---|---|
| Detection recall | Faults detected / faults injected |
| Root-cause accuracy | Supported cause matches the truth |
| Time to detect | Hours from fault start to incident open (median) |
| False alarms | Incidents opened on innocent changes or quiet hours |
| Data-issue precision | Data faults labelled DATA ISSUE, not business |

Almedia's data team thinks in false-positive rate and mean time to detect. One table with those numbers answers "does it actually work?".

**Blind test (demo).** A judge presses "Random hidden problem". The simulator picks a random scenario and parameters, and the UI hides which one. Argus detects, investigates and reports. Then we press "Reveal" and the truth appears next to Argus's verdict. This uses the same code as the bench.

## 10. Architecture

### 10.1 Stack

| Module | Tech | Owns |
|---|---|---|
| `sim/` | Python, numpy, DuckDB | MockMart generator (shop + ads), scenarios, observation lag, live clock, chaos hooks |
| `argus/graph/` | networkx, JSON, sqlglot | Graph store, edge tests, re-testing, onboarding pipeline |
| `argus/detect/` | pandas | Freshness gate, expectation, z-scores, onset, pacing check |
| `argus/investigate/` | Python | LMDI, mix/rate, segment finder, cause tests, verdicts, stopping rule, trail, check menu |
| `argus/incidents/` | SQLite | Fingerprints, silencing, lifecycle |
| `argus/llm/` | Claude API (default `claude-sonnet-5-5`; any LLM works) | Edge proposals, hypothesis proposals, report prose. Optional at runtime. |
| `bench/` | Python | Scorecard, blind-test picker |
| `api/` | FastAPI + SSE | Event stream, chaos endpoints, graph, incidents, receipts, scorecard |
| `web/` | React + Vite + React Flow + Tailwind | Mission Control. Stage 1 can be a single static HTML page. |

### 10.2 Event stream (SSE `GET /stream`), one JSON object per event

```json
{"type": "tick" | "anomaly" | "investigation_step" | "incident_update" | "metric_onboarded" | "edge_status" | "bench_result",
 "sim_ts": "2026-11-20T14:00:00", "payload": {}}
```

**Endpoints:** `GET /graph` · `GET /incidents` · `GET /incidents/{id}` (trail + receipts) · `POST /chaos/{scenario_id}` · `POST /chaos/random` · `POST /chaos/reveal` · `POST /metrics` (YAML body) · `POST /clock/speed` · `GET /bench`.

### 10.3 Repo layout

```
sim/                generator.py  ads.py  scenarios.py  clock.py
argus/graph/        store.py  tests.py  onboarding.py  seed_graph.json
argus/detect/       freshness.py  expectation.py  pacing.py
argus/investigate/  lmdi.py  segments.py  causes.py  checks.py  verdicts.py  loop.py
argus/incidents/    lifecycle.py
argus/llm/          propose_edges.py  propose_hypotheses.py  write_report.py
bench/              run.py
api/                main.py
web/                (Vite app)
metrics/            roas_by_advertiser.yml  gmv_by_seller_type.yml  app_crash_rate.yml
tests/              one test per scenario exit criterion (§8)
```

### 10.4 Work streams (split by team size)

| Stream | Owns | Needs first |
|---|---|---|
| A · Simulator | `sim/`, scenarios, `truth.duckdb`, `bench/` | table schemas |
| B · Graph | `argus/graph/`, seed graph, edge tests, onboarding | table schemas, `graph.json` |
| C · Detect + incidents | `argus/detect/`, `argus/incidents/` | graph schema |
| D · Investigator | `argus/investigate/`, `argus/llm/` | graph + incident schemas |
| E · API + UI | `api/`, `web/`; builds against a recorded mock event stream first | event-stream schema |

With fewer people, merge A+B and C+D and run AI agents per stream in separate git worktrees. **Integration is the biggest risk, so integrate by Sat 20:00 at the latest, even with stubs.**

## 11. Demo script (3 minutes)

| Time | What happens |
|---|---|
| 0:00–0:15 | "At 100M events a day nobody watches every chart. Argus does, and it knows when not to wake you." |
| 0:15–0:35 | The graph: the shop and the ads business, typed links, each with a live test. |
| 0:35–0:55 | Press **planned budget increase**: noticed, checked against the plan, filed under "didn't wake you". Press **ETL delay**: DATA ISSUE notice, not a page. |
| 0:55–1:35 | Press **pacer bug**: walk ad_spend → clicks → impressions → "traffic is flat, the pacer over-served" → pacer v1.7 supported by holdout. The report shows wasted budget and CPA. |
| 1:35–1:55 | **Blind test**: a judge presses "Random hidden problem", Argus reports, we press Reveal. |
| 1:55–2:20 | Drop 3 metric YAMLs: exact (ROAS), breakdown (seller type), ambiguous (crash rate), each with its certificate. |
| 2:20–2:40 | Scorecard: root-cause accuracy, time to detect, false alarms. |
| 2:40–3:00 | Architecture in one frame. "Statistics decide where to look and compute every number. The graph decides what to test next. The LLM only proposes and writes." Repo link. |

If the blind test picks S1 (PayCo + red herring), even better: it shows the release being ruled out live.

## 12. Tailoring to Almedia (pitch slide + talking points)

**One slide: "Our marketplace is your business"**

| MockMart | Almedia / Freecash |
|---|---|
| Advertiser budgets + pacer | Advertiser (game publisher) budgets + campaign pacing |
| Ad conversions, CPA, ROAS | User actions in advertiser apps, CPA, ROAS |
| Orders | Completed offers / rewarded actions |
| PayCo outage | An ad partner or payout provider going down |
| Late `fact_orders_hourly` | A late BigQuery load |
| Click fraud (stretch) | Invalid traffic, which their fraud team handles daily |

**Talking points:**
- Built in their tooling's shape: dbt-style metric YAML, BigQuery-style SQL, alerts formatted for Slack/Datadog webhooks.
- At their scale the cost is **false alarms**, so lead with the "didn't wake you" feed and the false-alarm number.
- **Data freshness** before business conclusions: their job ads ask for a data quality framework.
- Every suggested action (pause a campaign, hold a traffic source) **waits for human approval**.
- Frame Argus as "an analyst you'd hire". Do not mention news about Almedia's apps.

## 13. Rules for AI agents building this

1. Read §4–§7 before writing code. The formulas in §6 are the spec, not suggestions.
2. **No LLM call may produce a number or a verdict.** Numbers come from DuckDB queries and the §6 math. The LLM only proposes links, proposes hypotheses (as typed checks from §6.7), and writes prose.
3. Argus code must never import or read `truth.duckdb`. Only `bench/` may.
4. Every investigation step logs its SQL to the trail (receipts).
5. Each scenario exit criterion in §8 gets one automated test in `tests/`. A stage is done when its tests pass on 3 seeds.
6. Keep the LLM optional: if `ANTHROPIC_API_KEY` is missing or a call fails, fall back to the template report, non-LLM edge proposals, and UNEXPLAINED remainders.
7. Do not add scenarios, features or abstractions beyond the current stage. Finish the current stage first.
8. Stick to the schemas in §4, §5.1 and §10.2. Changing a schema needs agreement from the stream owners who depend on it.

## 14. Open decisions (team must answer)

- **Team:** how many people, who owns which stream, and who is on camera for the video.
- **LLM access:** an `ANTHROPIC_API_KEY` (or another provider).
- **Repo:** public GitHub repo, and under whose account.
- **Stage 1 UI:** a static page first (faster), or straight to React Flow (better demo, riskier)?
