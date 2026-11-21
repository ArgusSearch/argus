# Argus

The analyst that never sleeps.
Argus watches a business's metrics every hour, and when something breaks it says where, why, what it cost, how sure it is, and what it ruled out.
Nobody asks it anything.
Every number it reports comes from a SQL query with a reproducible receipt, and it knows when not to wake you.

Built for the HackLab Berlin track "Eye of the System: Fully Agentic Monitoring" (sponsor: Almedia).
All code in this repository was written during the hackathon.

## Quickstart

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.13 and the locked dependencies on demand) and `make`.

```bash
make s1
```

This one command simulates a fresh world, runs Argus over it hour by hour, and grades the result against the hidden ground truth:

```
S1 seed 7: PayCo DE-android success 0.95 -> 0.62 from 2026-11-20 21:00 to 06:00 (hidden truth, read by the bench only)
  PASS  supported_cause        INC-0001 SUPPORTED_CAUSE payment_success_rate DE/android/PayCo
  PASS  release_ruled_out      dep_android-app_8.3.0: holdout normal: +0.3% (z +0.7) outside the segment vs -34.6% inside
  PASS  detected_within_3h     opened 0 h after onset (data hour), 2 h wall clock
  PASS  quiet_hours_silent     69 quiet hours, 0 anomalies before onset
  PASS  one_incident           1 incident(s), 1 anomalies, 0 suppressed, state resolved
  PASS  receipts_reproducible  21 receipts re-run, 0 mismatched, 0 unbacked numbers, 0 untagged lines
  report: runs/s1-7/argus/reports/INC-0001.md   (6.7 s)
ALL PASS
```

Use another seed with `make s1 SEED=3`.
The report is plain markdown; open the path it prints.

## What scenario S1 shows

PayCo's payment success rate for Android users in Germany drops from about 95% to 60-72% at a random hour.
In the same hour an Android app release ships to every country: an obvious suspect that is wrong.
The total payment success rate moves only 2-3%.

Argus:

1. checks that the data arrived complete and that the identity `orders = payment_successes` holds (data before business);
2. finds no planned event that would make the change expected;
3. localises the drop to `DE / android / PayCo` (89% of the deviation) instead of stopping at `DE`;
4. tests both logged changes near the onset: the release is ruled out because Android outside the segment is normal (holdout), the PayCo status entry is kept;
5. returns `SUPPORTED_CAUSE`, the exact LMDI split of the orders drop (payment success carries about 90%), the EUR impact and a suggested action that needs human approval;
6. files one incident, silences downstream symptoms, monitors the root segment and resolves the incident after three normal hours.

## Commands

| Command | What it does |
| --- | --- |
| `make setup` | install the locked environment |
| `make s1 [SEED=n]` | S1 end to end, graded against the hidden truth |
| `make bench` | the scorecard: quiet, S1-S4 x 3 seeds, Argus against a threshold baseline, truth sealed first |
| `make world [SCENARIO=s1] [SEED=n]` | generate a world into `runs/<scenario>-<seed>/` (world.duckdb, truth.duckdb, manifest.json); scenarios: quiet, s1, s2, s3, s4 |
| `uv run argus run --world runs/s1-7/world.duckdb` | run Argus over a world and write its outputs next to it (`--stage 1` for the Stage-1 investigator) |
| `make demo [SCENARIO=s1]` | API and Mission Control on port 8000 running Argus live over a fresh world, streaming events |
| `make api [SCENARIO=s1]` | API and Mission Control replaying a recorded run: `fixtures/` for S1, `fixtures/<scenario>/` for the others (no world needed) |
| `make check` | lint, format check, mypy, contract freshness, Mission Control tests and build, all tests (what CI runs) |
| `make contracts` | regenerate `contracts/` from the pydantic models |
| `make fixtures` | re-record `fixtures/` (S1) and `fixtures/<scenario>/` (quiet, S2, S3, S4), each graded after it is written |

## Architecture

```
 MockMart (simulator)                Argus (one process: runtime + API)                     surfaces
+--------------------+  world   +-----------------------------------------------------+  SSE  +-----------------+
| sim  scenarios     |--------->| semantic (receipts, as_of)   graph (edges + tests)  |------>| Mission Control |
| delivery  truth    | .duckdb  | watcher -> investigator -> incidents -> narrator    | REST  | (lane U)        |
+--------------------+          | runtime tick loop  ->  event bus  ->  api           |       +-----------------+
          |                     +-----------------------------------------------------+
          | truth.duckdb (hidden)                     | findings, receipts
          +------------------------------> bench (grades verdicts against the truth)
```

One tick is one simulated hour:

1. freshness gate for the newest hour that should be complete (`as_of` minus the 2 h delivery lag);
2. once per simulated day, every formula and breakdown edge is re-tested against the data;
3. the north-star nodes are scored; an anomaly opens on `|z| > 5` or on 2 of the last 3 hours `|z| > 3.5`; the planned-change looks (`src/argus/detect/`) open one when delivery does not follow a budget or calendar plan in force;
4. an anomaly that no open incident covers is investigated with the Stage-2 investigator (`src/argus/investigate/`: hypothesis ledger, placebo, claim labels on top of the fixed opening in `src/argus/investigator/procedure.py`, which stays the fallback);
5. findings become an incident (by fingerprint) or a note ("didn't wake you", data issue);
6. open incidents are monitored on their root segment until they resolve;
7. every step is published as an event (contract C5) and streamed on `GET /events`.

## Repository layout

```
contracts/            generated contract artifacts: schema.sql and JSON Schemas (do not edit, run make contracts)
graph/seed_graph.yml  hand-written seed metric graph: 27 nodes (shop funnel and ads business), 44 typed edges
metrics/              C2 metric definitions (name, description, sql); new metrics are dropped here
fixtures/             recorded runs for replay: S1 at the top level, quiet, s2, s3, s4 in fixtures/<scenario>/
src/argus/contracts/  the six contracts as pydantic models (single source of truth)
src/argus/semantic/   SQL compiler for graph nodes, query runner, receipts with canonical hashes      lane G
src/argus/graph/      seed graph loader, edge tests, changelog                                      lane G
src/argus/cartographer/  metric onboarding (Stage 2 placeholder)                                    lane G
src/argus/watcher/    freshness gate, expectation, robust z, open and resolve rules                 lane B
src/argus/detect/     watcher with attention budget, pacing and planned-change looks                lane B
src/argus/decompose/  LMDI, mix vs rate, segment search (pure functions)                            lane B
src/argus/investigator/  typed tools (C6) and the fixed opening procedure (Stage 1, the fallback)   lane B
src/argus/investigate/   Stage-2 investigator the runtime uses: hypothesis ledger, placebo, claims   lane B
src/argus/incidents/  fingerprints, symptom silencing, lifecycle, severity                          lane B
src/argus/runtime/    tick loop and event bus                                                       lane B
src/argus/skeptic/, src/argus/llm/  Stage 2 placeholders                                            lane B
src/argus/narrator/   template report and the number check                                          lane U
src/argus/api/        FastAPI REST routes and the SSE stream                                         lane U
src/argus/mcp/        MCP server (Stage 3 placeholder)                                               lane U
src/mockmart/         simulator: causal world, micro-batch delivery, decoy logs, scenarios, truth   lane W
src/bench/            sealed scorecard, S1 criteria, recordings (the only code that reads truth.duckdb)  lane W
web/                  Mission Control: React page over the SSE stream                               lane U
tests/unit, tests/e2e one test per S1 exit criterion on three seeds, plus unit tests per module
docs/                 contracts.md, lanes.md, decisions.md
```

`docs/lanes.md` explains how the four people build in parallel from here.

## The six contracts

| Id | Contract | Code | Generated artifact |
| --- | --- | --- | --- |
| C1 | world tables (facts, logs, as_of views) | `src/argus/contracts/world.py` | `contracts/schema.sql`, `contracts/c1_world.json` |
| C2 | metric definition YAML | `src/argus/contracts/metric.py` | `contracts/c2_metric.schema.json` |
| C3 | metric graph (`graph.json`) | `src/argus/contracts/graph.py` | `contracts/c3_graph.schema.json` |
| C4 | findings, receipts, notes, incidents | `src/argus/contracts/findings.py` | `contracts/c4_findings.schema.json` |
| C5 | event stream and REST routes | `src/argus/contracts/events.py` | `contracts/c5_events.schema.json` |
| C6 | investigation tools | `src/argus/contracts/tools.py` | `contracts/c6_tools.schema.json` |

Details and examples: `docs/contracts.md`.

## How Argus decides

- **Receipts.**
  Every query runs with `as_of` pinned, against views that only show micro-batches ingested by then.
  The result hash is canonical (rows sorted, floats at 10 significant digits, SHA-256), so re-running a receipt returns the same hash even after late data arrived.
- **Expectation and z.**
  Same hour of the week over the last four weeks (median for counts, pooled ratio for rates), log residuals, scale from the MAD of the last 168 hours, floored by Poisson or binomial sampling noise of the hour and of the baseline.
- **Freshness first.**
  A node whose source table is incomplete for the hour is pending, not scored; a lagging table produces one DATA_ISSUE note.
- **Exact split.**
  Product formulas are flattened (`orders = sessions x view_rate x cart_rate x checkout_rate x attempt_rate x payment_success_rate`) and split with additive LMDI, which has zero residual.
- **Segment search.**
  Explanatory power per dimension value; the smallest set of at most 3 values explaining at least 67%; descend into a single value while it explains clearly more than its volume share and the deviation is significant.
- **First cause.**
  Log entries in the 3 hours before the root segment's own onset whose scope covers the segment are candidates; an event is ruled out when its scope outside the segment is normal (holdout check).
- **Verdicts.**
  SUPPORTED_CAUSE needs an aligned event that survives the holdout and at least 20% explained; otherwise HYPOTHESIS; the unexplained share is always stated.
- **No alert spam.**
  Fingerprint (root node, segment, direction), symptom silencing for every node whose formula contains the root, reopen within 24 h, severity in EUR.
- **No LLM in the loop yet.**
  Stage 1 runs fully without a language model; Stage 2 adds one only to propose and to write prose that must pass the number check.

## Status

Done (Stage 0 and the S1 skeleton): repo layout, the six contracts with generated schemas, MockMart with S1 and hidden truth, seed graph with edge tests, freshness gate and detection, investigator, incidents, template report, API with SSE, bench and tests, CI.

Integrated since: the Stage-2 investigator in the runtime, the detect lane's planned-change looks, scenarios S2-S4 with the sealed scorecard and blind challenge, metric self-classification (`src/argus/graph/classify.py`), and Mission Control over live and recorded runs of every scenario.

Next (see `docs/lanes.md`): metric onboarding through the API, the LLM planner and the skeptic, scenarios S5 and S6.

## Source attributions

Algorithms and methods (implemented from the published descriptions; no third-party code was copied):

- Additive LMDI decomposition: B. W. Ang, "The LMDI approach to decomposition analysis: a practical guide", Energy Policy 33(7), 2005.
- Explanatory power and surprise for segment localisation: R. Bhagwan et al., "Adtributor: Revenue Debugging in Advertising Systems", NSDI 2014.
- Descending while children deviate unevenly, inspired by Y. Sun et al., "HotSpot: Anomaly Localization for Additive KPIs With Multi-Dimensional Attributes", IEEE Access 2018, and M. Kalander, "RiskLoc: Localization of Multi-dimensional Root Causes by Weighted Risk", arXiv 2022.
- Robust z-scores with the median absolute deviation: B. Iglewicz and D. C. Hoaglin, "How to Detect and Handle Outliers", ASQC 1993.
- Mix vs rate split with midpoint weights: E. M. Kitagawa, "Components of a Difference Between Two Rates", JASA 50(272), 1955.
- Benjamini-Hochberg false discovery rate control (planned for cause edges): Y. Benjamini and Y. Hochberg, JRSS B 57(1), 1995.

Product research that shaped the design (ideas only, from public documentation): Datadog Bits AI SRE, Resolve.ai, Causely, Traversal, Anodot, Outlier, Sisu, ThoughtSpot SpotIQ, Power BI key influencers, Amplitude, Mixpanel, Tableau Pulse, Monte Carlo, Anomalo, Uber uVitals, LinkedIn ThirdEye, Airbnb Minerva, Netflix Kayenta, Meta's fast dimensional analysis, and the Flow-of-Action and ORCA-bench papers on root-cause agents.

Libraries (see each project's license): DuckDB (MIT), sqlglot (MIT), FastAPI (MIT), Starlette (BSD-3-Clause), pydantic (MIT), NumPy (BSD-3-Clause), pandas (BSD-3-Clause), PyYAML (MIT), uvicorn (BSD-3-Clause); for development pytest, ruff, mypy and httpx2.

All company, advertiser and provider names in MockMart (PayCo, CardHub, WalletGo, Nimbus Games and the others) are fictional.

## License

MIT, see `LICENSE`.
