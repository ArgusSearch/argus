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

**Where the agent thinks, and where it cannot.**

The model chooses what to check. Argus decides what the evidence supports.

| Technique | What it does | What keeps it honest | Release eval |
| --- | --- | --- | --- |
| Competing hypotheses | Puts rival causes and their cheapest decisive checks on a board | Judged checks determine each card's status | E18 checks 8 positive board reconstructions and 3 negative scenarios |
| Self-written checks | Writes a SELECT for a cut outside the fixed tool menu | A parser limits queries to as-of views. A receipt pins the result. Stage 2 alone can grant a supported cause | E19 requires 28 SQL rejections, 10 accepted cuts and visibility at `as_of`. E20 checks both directions of a PayCo comparison |
| Counter-check | A second model in a fresh context tries to falsify a supported cause | Code judges the receipts and can downgrade the verdict | E21 requires 3 of 3 planted false causes removed and 0 of 6 true causes vetoed. E22 checks verdict safety across 18 cases |
| Case memory | Uses past denials and verified outcomes when considering another proposal | The deterministic proposal policy reads memory as advice. Evidence comes from checks | E23 checks denial and approval precedents. E24 requires identical verdicts, roots and proposals in 3 poisoned-memory trials |
| Cause chain | Links the event, root segment, formula hops and EUR impact | Every link carries a receipt that can be re-run | E25 checks 6 supported cases and 3 negative scenarios |
| Budget | Stops the detective and critic at fixed caps | Stage 2 completes in the same tick | E26 checks caps of 12 detective calls and 3 critic calls, exact recorded cost and zero replay spend |

Only the host renders numbers verified against receipts.
Only deterministic investigation rules can grant a supported cause.
Only the operator can approve an action, and the playbook derives its parameters.

The Stage 2 bench passes 18 of 18 cases with zero false alarms, with the agent off.
The default v1 profile has 17 offline agent evals. The v2 release requires the
intelligence evals and six retained live trials, with three passes each on S1
and S4. Live v2 qualification is pending. Sealed v1 investigation cassettes
replay the provider exchange and activity offline byte for byte.
See the [v2 capture and qualification guide](fixtures/agent/v2/README.md).

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

## Built on

Everything in this repository was written during the hackathon. Third-party code
enters only as the dependencies listed here, installed from PyPI and npm.
Nothing was vendored or copied.

| Library | Locked version | License | Use |
| --- | --- | --- | --- |
| Anthropic SDK | 2.12.0 | Apache-2.0 | Live model transport and typed responses |
| DuckDB | 2.0.1 | MIT | Simulator worlds, as-of queries and receipts |
| sqlglot | 30.33.0 | MIT | SQL lineage and SELECT validation |
| FastAPI | 0.165.0 | MIT | API and request handling |
| Starlette | 1.10.0 | BSD-3-Clause | ASGI routing and streaming |
| Pydantic | 2.14.4 | MIT | Typed contracts and schema export |
| NumPy | 2.5.5 | BSD-3-Clause (core) | Statistical operations and simulation |
| pandas | 3.1.1 | BSD-3-Clause | Simulation and tabular processing |
| PyYAML | 6.0.4 | MIT | Metric and playbook definition parsing |
| Uvicorn | 0.54.0 | BSD-3-Clause | ASGI server |
| pytest | 9.2.0 | MIT | Offline verification |
| Ruff | 0.17.6 | MIT | Lint and formatting |
| mypy | 2.4.1 | MIT | Python type checking |
| httpx2 | 2.16.2 | BSD-3-Clause | API tests |
| types-PyYAML | 6.0.12.20261113 | Apache-2.0 | Type stubs for YAML |
| React and React DOM | 19.3.1 | MIT | Mission Control interface |
| React Flow (`@xyflow/react`) | 13.0.2 | MIT | Metric graph interactions |
| Bot Avatars | 0.2.2 | MIT | Agent avatars |
| Three.js | 0.187.0 | MIT | Three-dimensional scene rendering |
| IBM Plex Mono via Fontsource | 5.3.0 | OFL-1.1 | Interface typography |
| TypeScript | 7.0.2 | Apache-2.0 | Web type checking |
| Vite and React plugin | 8.3.8 / 6.3.0 | MIT | Web development and build |
| Vitest | 5.1.1 | MIT | Web tests |
| React, React DOM and Three.js type stubs | 19.3.0 / 19.3.0 / 0.187.0 | MIT | Web library typings |

### Methods

Argus implements these methods from their published descriptions.

- Additive LMDI decomposition: B. W. Ang, "The LMDI approach to decomposition analysis: a practical guide", Energy Policy 33(7), 2005.
- Explanatory power and surprise for segment localisation: R. Bhagwan et al., "Adtributor: Revenue Debugging in Advertising Systems", NSDI 2014.
- Descending while children deviate unevenly, inspired by Y. Sun et al., "HotSpot: Anomaly Localization for Additive KPIs With Multi-Dimensional Attributes", IEEE Access 2018, and M. Kalander, "RiskLoc: Localization of Multi-dimensional Root Causes by Weighted Risk", arXiv 2022.
- Robust z-scores with the median absolute deviation: B. Iglewicz and D. C. Hoaglin, "How to Detect and Handle Outliers", ASQC 1993.
- Mix vs rate split with midpoint weights: E. M. Kitagawa, "Components of a Difference Between Two Rates", JASA 50(272), 1955.
- Benjamini-Hochberg false discovery rate control (planned for cause edges): Y. Benjamini and Y. Hochberg, JRSS B 57(1), 1995.

- ReAct (Yao et al.) inspired the loop that alternates between choosing a check and observing its result. [Paper](https://arxiv.org/abs/2210.03629)
- Reflexion (Shinn et al.) inspired the separate counter-check and the lessons retained in case memory. [Paper](https://arxiv.org/abs/2303.11366)
- Tree of Thoughts (Yao et al.) inspired competing hypotheses and choosing checks under a budget. [Paper](https://arxiv.org/abs/2305.10601)

### Evaluated and not used

- Merlion's evaluated release required NumPy below 2 and brought in a forecasting stack.
- PyRCA's evaluated release required scikit-learn below 1.2 and a Java bridge.
- DoWhy resolved to 45 packages in the evaluation. MockMart's untreated twin provides the comparison for action effects.

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
