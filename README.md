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
  PASS  release_ruled_out      dep_android-app_8.3.0: holdout normal: +0.9% (z +1.8) outside the segment vs -35.8% inside
  PASS  detected_within_3h     opened 0 h after onset (data hour), 2 h wall clock
  PASS  quiet_hours_silent     69 quiet hours, 0 anomalies before onset
  PASS  one_incident           1 incident(s), 1 anomalies, 0 suppressed, state resolved
  PASS  receipts_reproducible  21 receipts re-run, 0 mismatched, 0 unbacked numbers, 0 untagged lines
  report: runs/s1-7/argus/reports/INC-0001.md   (6.7 s)
ALL PASS
```

Use another seed with `make s1 SEED=3`.
The report is plain markdown; open the path it prints.

### Watch it live

Mission Control needs [Node.js](https://nodejs.org/) 22.12 or newer.

```bash
make setup   # the locked Python environment
make web     # once: install, test and build Mission Control into web/dist
make demo    # Argus live over a fresh S1 world, Mission Control on http://127.0.0.1:8000
```

`make demo SCENARIO=s4` runs another scenario (quiet, s1 to s5).
`make api` replays a recorded run from `fixtures/` instead, with no world to generate.
`make bench` grades every scenario on three seeds against the hidden truth and a threshold baseline.

## What scenario S1 shows

PayCo's payment success rate for Android users in Germany drops from about 95% to 60-72% at a random hour.
In the same hour an Android app release ships to every country: an obvious suspect that is wrong.
The total payment success rate moves only 2-3%.

Argus:

1. checks that the data arrived complete and that the identity `orders = payment_successes` holds (data before business);
2. finds no planned event that would make the change expected;
3. localises the drop to `DE / android / PayCo` (100% of the deviation on seed 7) instead of stopping at `DE`;
4. tests both logged changes near the onset: the release is ruled out because Android outside the segment is normal (holdout), the PayCo status entry is kept;
5. returns `SUPPORTED_CAUSE`, the exact LMDI split of the orders drop (payment success carries 82% on seed 7), the EUR impact and a suggested action that needs human approval;
6. files one incident, silences downstream symptoms, monitors the root segment and resolves the incident after three normal hours.

## Commands

| Command | What it does |
| --- | --- |
| `make setup` | install the locked environment |
| `make s1 [SEED=n]` | S1 end to end, graded against the hidden truth |
| `make bench` | the scorecard: quiet, S1-S5 x 3 seeds, Argus against a threshold baseline, truth sealed first |
| `make world [SCENARIO=s1] [SEED=n]` | generate a world into `runs/<scenario>-<seed>/` (world.duckdb, truth.duckdb, manifest.json); scenarios: quiet, s1, s2, s3, s4, s5 |
| `uv run argus run --world runs/s1-7/world.duckdb` | run Argus over a world and write its outputs next to it (`--stage 1` for the Stage-1 investigator) |
| `make web` | install, test and build Mission Control into `web/dist` (Node.js 22.12+); the API serves it at `/` |
| `make demo [SCENARIO=s1]` | API and Mission Control on port 8000 running Argus live over a fresh world, streaming events |
| `make api [SCENARIO=s1]` | API and Mission Control replaying a recorded run: `fixtures/` for S1, `fixtures/<scenario>/` for the others (no world needed) |
| `make check` | lint, format check, mypy, contract freshness, Mission Control tests and build, all tests (what CI runs) |
| `make contracts` | regenerate `contracts/` from the pydantic models |
| `make fixtures` | re-record `fixtures/` (S1) and `fixtures/<scenario>/` (quiet, S2, S3, S4, S5), each graded after it is written |
| `uv run argus demo [--scenario s4]` | print the 90-second demo cue timeline that `POST /demo/start` plays ([docs/ext/demo.md](docs/ext/demo.md)) |
| `uv run argus counterfactual --scenario s4` | replay an incident with its named cause switched off and verify the paired receipts ([docs/ext/counterfactual.md](docs/ext/counterfactual.md)) |

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
fixtures/             recorded runs for replay: S1 at the top level, quiet, s2, s3, s4, s5 in fixtures/<scenario>/
src/argus/contracts/  the six contracts as pydantic models (single source of truth)
src/argus/semantic/   SQL compiler for graph nodes, query runner, receipts with canonical hashes      lane G
src/argus/graph/      seed graph loader, edge tests, changelog                                      lane G
src/argus/cartographer/  metric onboarding (Stage 2 placeholder)                                    lane G
src/argus/watcher/    freshness gate, expectation, robust z, open and resolve rules                 lane B
src/argus/detect/     watcher with attention budget, pacing and planned-change looks (the runtime uses the last)  lane B
src/argus/decompose/  LMDI, mix vs rate, segment search (pure functions)                            lane B
src/argus/investigator/  typed tools (C6) and the fixed opening procedure (Stage 1, the fallback)   lane B
src/argus/investigate/   Stage-2 investigator the runtime uses: hypothesis ledger, placebo, claims   lane B
src/argus/incidents/  fingerprints, symptom silencing, lifecycle, severity                          lane B
src/argus/runtime/    tick loop and event bus                                                       lane B
src/argus/skeptic/, src/argus/llm/  Stage 2 placeholders                                            lane B
src/argus/narrator/   template report, the number check, morning report, autonomy and playbooks     lane U
src/argus/market/     S5 market control: metric against an independent demand index
src/argus/counterfactual/  paired MockMart replay with the named cause switched off
src/argus/demo/       90-second demo playback over the recorded S1 and S4 runs
src/argus/api/        FastAPI REST routes and the SSE stream                                         lane U
src/argus/mcp/        MCP server (Stage 3 placeholder)                                               lane U
src/mockmart/         simulator: causal world, micro-batch delivery, decoy logs, scenarios, truth   lane W
src/bench/            sealed scorecard, S1 criteria, recordings (the only code that reads truth.duckdb)  lane W
web/                  Mission Control: React page over the SSE stream                               lane U
tests/unit, tests/e2e one test per S1 exit criterion on three seeds, plus unit tests per module
docs/                 ALGORITHM.md (how Argus decides), contracts.md, lanes.md, decisions.md; docs/ext/ for the extension contracts
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

Four choices make Argus an analyst rather than an alert: what it watches, which edges it follows, which groups it checks, and when the evidence is enough.
Each answer is a fixed rule in the code; [docs/ALGORITHM.md](docs/ALGORITHM.md) is the one-page version with a diagram.

**1. What it watches.**
Every simulated hour Argus scores the 7 north-star metrics (sessions, orders, GMV, payment success rate, conversion rate, ad spend, CPA) and opens an anomaly at |z| > 5, or at |z| > 3.5 in 2 of the last 3 hours.
A planned budget or calendar change adds a look at exactly the segment it names for 24 hours.
Everything below the north stars is examined only when a north star moves, so about 7 statistical tests run per hour instead of hundreds of slices that would page on noise.
The attention budget that would add 6 more looks per tick (`src/argus/detect/attention.py`, business weight x surprise x data confidence x novelty) is built and unit-tested but not used by the runtime yet.

**2. Which edges it follows.**
Formula edges first: an exact LMDI split, hop by hop (`gmv -> orders -> cvr -> payment_success_rate`), following the factor that moved beyond its week-to-week spread (|z| >= 3) rather than the largest share.
For a ratio, a mix shift with every group's own rate flat is EXPECTED.
Breakdown edges give the dimensions to search and evidence edges name the logs that can move a node; cause edges are not followed (the seed graph's one cause edge is PROPOSED and untested).
Formula and breakdown edges are re-tested against the data once per simulated day; a BROKEN formula edge is not used for the split, and a broken identity marks a data problem.

**3. Which groups it checks.**
The smallest set of at most 3 values of one dimension that explains at least 67% of the deviation, descending into a single value while it carries 25 points more of the deviation than of the volume and |z| >= 3 (`DE / android / PayCo`, not just `DE`).
The suspects are log entries from 3 hours before to 1 hour after the segment's own onset whose scope covers it.
Each suspect gets a holdout: if its scope outside the segment stays normal, it is ruled out; when the scope is exactly the segment, untouched neighbouring groups are the control.
A placebo looks for the same deviation in up to 8 earlier weeks.

**4. When the evidence is enough.**
Every check is a hypothesis with its prediction written first, judged by code, at most 12 per investigation.
Late data or a broken identity stops early as a DATA_ISSUE; a plan that delivery follows, an outside market index that moves the same way, or a mix shift stops as EXPECTED; none of them pages anyone.
A planner is asked for more checks only while less than 80% of the deviation is explained and checks remain; without one, the remainder is reported as unexplained.
The verdict:

- **Supported cause (evidenced)** (`SUPPORTED_CAUSE`): a suspect aligned with the onset that its holdout or control validates, a root with |z| >= 3, at least 20% explained, and a placebo that does not recur.
- **Hypothesis** (`HYPOTHESIS`): localised and significant, but no logged change is validated.
- **Unexplained** (`UNEXPLAINED`): nothing localises and no logged change lines up.

The unexplained share is always stated, and every claim is labelled evidence or hypothesis.

**Where the language model fits.**
The deterministic path needs none: the S1 investigation makes 0 LLM calls.
A model may only propose the next check: the `Planner` interface (`src/argus/investigate/planner.py`) accepts typed checks from the C6 tool menu with a prediction, the investigator runs them, and the ledger judges them, so a model never produces a number or a verdict.
Prose with numbers must pass the number check against the run's receipts.
Every suggested action needs human approval (`needs_approval`, `GET /autonomy`); Argus files and closes incidents on its own but does not act on the business.

**Underneath.**

- **Receipts.**
  Every query runs with `as_of` pinned, against views that only show micro-batches ingested by then.
  The result hash is canonical (rows sorted, floats at 10 significant digits, SHA-256), so re-running a receipt returns the same hash even after late data arrived.
- **Expectation and z.**
  Same hour of the week over the last four weeks (median for counts, pooled ratio for rates), log residuals, scale from the MAD of the last 168 hours, floored by Poisson or binomial sampling noise of the hour and of the baseline.
- **Freshness first.**
  A node whose source table is incomplete for the hour is pending, not scored; a lagging table produces one DATA_ISSUE note.
- **No alert spam.**
  Fingerprint (root node, segment, direction), symptom silencing for every node whose formula contains the root, reopen within 24 h, severity in EUR.

## Status

Done (Stage 0 and the S1 skeleton): repo layout, the six contracts with generated schemas, MockMart with S1 and hidden truth, seed graph with edge tests, freshness gate and detection, investigator, incidents, template report, API with SSE, bench and tests, CI.

Integrated since: the Stage-2 investigator in the runtime, the detect lane's planned-change looks, scenarios S2-S4 with the sealed scorecard and blind challenge, metric self-classification as a command (`uv run python -m argus.graph.classify <metric.yml> --world <world.duckdb>`), and Mission Control over live and recorded runs of every scenario.

Extensions (contracts in `docs/ext/`): S5 with a market control group, the receipt-backed morning report with the autonomy boundary and playbooks (`GET /report/morning`, `GET /autonomy`), counterfactual replay (`GET /incidents/{id}/counterfactual`), one-click demo playback (`/demo/*`) and the API robustness suite.

Next (see `docs/lanes.md`): metric onboarding through the runtime and the API, the attention budget in the runtime, an LLM planner behind the `Planner` interface, cause-edge tests, scenario S6.

## Source attributions

Algorithms and methods (implemented from the published descriptions; no third-party code was copied):

- Additive LMDI decomposition: B. W. Ang, "The LMDI approach to decomposition analysis: a practical guide", Energy Policy 33(7), 2005.
- Explanatory power and surprise for segment localisation: R. Bhagwan et al., "Adtributor: Revenue Debugging in Advertising Systems", NSDI 2014.
- Descending while children deviate unevenly, inspired by Y. Sun et al., "HotSpot: Anomaly Localization for Additive KPIs With Multi-Dimensional Attributes", IEEE Access 2018, and M. Kalander, "RiskLoc: Localization of Multi-dimensional Root Causes by Weighted Risk", arXiv 2022.
- Robust z-scores with the median absolute deviation: B. Iglewicz and D. C. Hoaglin, "How to Detect and Handle Outliers", ASQC 1993.
- Mix vs rate split with midpoint weights: E. M. Kitagawa, "Components of a Difference Between Two Rates", JASA 50(272), 1955.
- Benjamini-Hochberg false discovery rate control (planned for cause edges): Y. Benjamini and Y. Hochberg, JRSS B 57(1), 1995.

Product research that shaped the design (ideas only, from public documentation): Datadog Bits AI SRE, Resolve.ai, Causely, Traversal, Anodot, Outlier, Sisu, ThoughtSpot SpotIQ, Power BI key influencers, Amplitude, Mixpanel, Tableau Pulse, Monte Carlo, Anomalo, Uber uVitals, LinkedIn ThirdEye, Airbnb Minerva, Netflix Kayenta, Meta's fast dimensional analysis, and the Flow-of-Action and ORCA-bench papers on root-cause agents.

Built on / inspired by: [T3 Code](https://github.com/pingdotgg/t3code) (MIT).
The agent surfaces in `web/src/agent-ui/` (runs folded to one line with a live "doing now" line and runtime, approvals inline in the activity, follow-tail scrolling with "Jump to latest", arrow-up question history, stop while waiting) follow T3 Code's timeline and composer behaviour.
They are rewritten for Argus' React and CSS; the follow-tail state machine and the first-sentence rule of the live line are adapted from T3 Code's `timelineViewport.ts` and `work-log/presentation.ts`, so its notice applies to them:

<details>
<summary>T3 Code license (MIT)</summary>

```
MIT License

Copyright (c) 2026 T3 Tools Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

</details>

Libraries (see each project's license): DuckDB (MIT), sqlglot (MIT), FastAPI (MIT), Starlette (BSD-3-Clause), pydantic (MIT), NumPy (BSD-3-Clause), pandas (BSD-3-Clause), PyYAML (MIT), uvicorn (BSD-3-Clause); for development pytest, ruff, mypy and httpx2.

All company, advertiser and provider names in MockMart (PayCo, CardHub, WalletGo, Nimbus Games and the others) are fictional.

## License

MIT, see `LICENSE`.
