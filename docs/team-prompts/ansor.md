# Argus team prompt for Ansor (TheWingTheWong): end-to-end QA of Mission Control

You are the coding agent of Ansor (GitHub `TheWingTheWong`), one of three human teammates on the Argus hackathon team.
Read this whole prompt before you run anything.
Everything below was checked against the repository on Saturday 2026-11-21 around 15:50 CET; if a command or path does not match what you see, trust the repository, say so in your PR, and do not invent files.

## 1. What Argus is and how it is judged

Argus is "the analyst that never sleeps": an autonomous metric-graph monitoring analyst.
It watches a business's metrics every simulated hour, and when something breaks it says where, why, what it cost, how sure it is, and what it ruled out, without anybody asking.
Every number it reports comes from a SQL query with a reproducible receipt (re-run it and you get the same hash), and it knows when not to wake you ("didn't wake you" notes).
It runs over MockMart, a simulated marketplace with a hidden ground truth that only the bench reads.

Hackathon: HackLab Berlin, track "Eye of the System: Fully Agentic Monitoring", sponsor Almedia.
Rubric:

- 40% metric graph: a typed metric graph (formula, breakdown, cause and evidence edges, each with a live test) that extends itself when a new metric is dropped in.
- 40% autonomy: monitoring and investigation with no human in the loop (detect, localise, test causes, rule out decoys, file one incident, resolve).
- 20% demo: the 3-minute video, the live demo and the pitch.

Your work is mostly in the 20% demo block and in making sure the 80% is visible and actually works in the web app.
The web app is called Mission Control.

Deadline: submission Sunday 2026-11-22 16:30 (the team submits at 15:30 to keep a buffer).

## 2. Hard rules (read twice)

1. **No code from before Saturday 2026-11-21 11:00.**
   Every line in the repository must be written during the hackathon.
   Do not copy or paste code from earlier projects, your own older repositories, gists, snippets or earlier agent sessions.
   Never use anything from Kairos (`kairos-studio`), not even its charts.
   Published libraries from npm or PyPI under an open-source license are fine; add one only when it is clearly worth it and write one line about it in `docs/decisions.md` in the same PR.
   Algorithms may be implemented from published descriptions; name the source in the PR description.
2. **No secrets, no personal data.**
   Never commit `.env`, API keys, tokens, real names of customers or emails; `.env.example` holds only empty keys.
   All MockMart company names (PayCo, CardHub, WalletGo, ...) are fictional and must stay fictional.
3. **Stay in your folders** (section 7) and never edit the contracts on your own (section 5).
4. **Never push to a `fm/*` branch and never merge a PR yourself.**
   The `fm/*` branches belong to the team's coding-agent workers; Batu merges.
5. **Every PR keeps the checks green** (section 4).

## 3. Repository, setup, run

Repository (private): https://github.com/ArgusSearch/argus
You already have access. Check it with `gh auth status` (log in with `gh auth login` if needed) and `git ls-remote https://github.com/ArgusSearch/argus.git`, which must list the `fm/*` branches below.

```bash
git clone https://github.com/ArgusSearch/argus.git
cd argus
git fetch origin
git switch -c team/ansor/qa origin/fm/argus-api
```

Requirements: [uv](https://docs.astral.sh/uv/) (installs Python 3.13 and the locked dependencies itself), `make`, Node.js with npm (checked with Node 26; Node 20 or newer should do), and Chrome for browser checks.

### 3.1 Branches on origin (main is still only the initial commit)

`main` contains nothing but `chore: initial commit`; nothing lands there until Batu approves it.
The real code lives on these branches:

| Branch | Head (Sat 15:50) | What it contains |
| --- | --- | --- |
| `fm/argus-foundation` | `d116d2f` | Stage 0 and S1 end to end: the six contracts, MockMart with scenario S1 and its hidden truth, seed graph (27 nodes, 44 typed edges) with edge tests, Stage-1 watcher (`src/argus/watcher/`), Stage-1 investigator (`src/argus/investigator/`), incidents, template report (`src/argus/narrator/`), runtime tick loop and event bus (`src/argus/runtime/`), S1 bench, CI |
| `fm/argus-api` | `437fff5` | foundation plus the C5 API (`src/argus/api/`: `app.py`, `digest.py`, `hub.py`, `recording.py`, `replay.py`, `rerun.py`, `sources.py`, `state.py`) and Mission Control (`web/`, React 19, Vite 8, TypeScript, `@xyflow/react`). **This is your base.** |
| `fm/argus-bench` | `74e2131` | scenarios S2, S3, S4 (`src/mockmart/scenarios/s2_budget.py`, `s3_orders_stall.py`, `s4_pacer.py`), bench runner, grader, scorecard, sealed envelope and blind challenge (`src/bench/`), `tests/bench/` |
| `fm/argus-investigate` | `c1d9055` | Stage-2 investigator `src/argus/investigate/` (ledger, planner, playbook, procedure, walk, weekly, report, tools); also carries an older copy of the `fm/argus-bench` commits |
| `fm/argus-detect` | `2c234b7` | new watcher `src/argus/detect/` (freshness, expectation, attention budget, pacing check, rules) |
| `fm/argus-graph` | `d56d92e` | metric self-classification `src/argus/graph/classify*.py` and `tests/graph_classify/` |

Important: the API and the web app on `fm/argus-api` run the Stage-1 runtime (`src/argus/runtime/loop.py` imports `argus.investigator` and `argus.watcher`).
Scenarios S2 to S4 and the new `detect` and `investigate` modules live on the other branches and are not wired into the runtime yet; the coding agents and Batu do that integration.
Apart from one bench test file (handled in section 3.4), no two of these branches change the same file, so a local merge is clean.
The heads above are from Saturday 15:50 and keep moving; always work from `origin/<branch>` after `git fetch origin`.

### 3.2 Setup and checks

```bash
make setup                      # uv sync: the locked Python environment
make check                      # ruff lint + format check, mypy, contract freshness, pytest (what CI runs)
make s1                         # S1 end to end, graded against the hidden truth; must end with ALL PASS
npm --prefix web install
npm --prefix web run build      # tsc --noEmit + vite build into web/dist (the API serves it at /)
npm --prefix web run typecheck
npm --prefix web test           # vitest
```

Verified on `fm/argus-api` (437fff5): `make check` gives `79 passed, 2 skipped` without `web/node_modules` (the 2 skipped are the web checks, which run inside pytest once `web/node_modules` exists), `make s1` prints six PASS lines and `ALL PASS` in about 8 s, the web build and its 8 vitest tests pass.
The build warns that the main JS chunk is larger than 500 kB; that is known.

### 3.3 Run the app locally

```bash
make api                        # http://127.0.0.1:8000 replays the recorded S1 run in fixtures/ (no world needed)
make demo                       # generates the S1 world (seed 7) and runs Argus live over it on port 8000
make demo SEED=3                # another S1 world
npm --prefix web run dev        # dev server on http://127.0.0.1:5173 with hot reload; proxies the API routes to port 8000
```

- Run `make api` or `make demo` in one terminal and `npm --prefix web run dev` in another while you develop; `ARGUS_API=http://127.0.0.1:8001 npm --prefix web run dev` points Vite at another port.
- `make api PORT=8001` and `uv run argus api --port 8001` change the port; `uv run argus api --world <world.duckdb> --tick-seconds 0.5` runs live over any world faster (default 2 wall seconds per simulated hour).
- The page header shows `Replay · recorded run` or `Live · <world>` and has play, pause, speed and restart controls (`POST /replay`).
- Receipt re-runs (`POST /receipts/{id}/rerun`) only work in live mode; in replay mode they answer 409 by design.

Recorded test data: `fixtures/` holds one recorded S1 run (seed 1, 171 events): `events.jsonl` (C5 stream), `graph.json`, `incidents.json`, `findings.json`, `anomalies.json`, `notes.json`, `receipts.json`, `report.md`, `manifest.json`.
`make api` streams exactly that file through the same SSE path as a live run.
Fresh worlds: `make world SEED=n` writes `runs/s1-<n>/` (`world.duckdb`, `truth.duckdb`, `manifest.json`); `runs/` is gitignored.

API routes the page uses: `GET /health`, `GET /events` (SSE), `POST /replay`, `GET /graph`, `GET /incidents`, `GET /incidents/{id}`, `GET /incidents/{id}/report`, `GET /notes`, `GET /digest`, `GET /receipts/{id}`, `POST /receipts/{id}/rerun`, `GET /routes`, and FastAPI docs at `/docs`.
These answer `501 not built yet` today: `POST /metrics` (graph lane), `POST /chaos/inject`, `POST /challenge/commit`, `POST /challenge/reveal`, `GET /bench/results` (bench lane), `POST /incidents/{id}/feedback`.

### 3.4 Local integration branch for scenarios S2 to S4 (never push it)

To see S2, S3 and S4 you need the scenario code from the other branches.
Build a throwaway local branch; never push it and never base a PR on it:

```bash
git switch -c local/integration origin/fm/argus-api
git merge --no-edit origin/fm/argus-investigate origin/fm/argus-detect origin/fm/argus-graph
git checkout origin/fm/argus-bench -- tests/bench/test_bench_scenarios.py   # newer bench test file (DECIMAL fix, see below)
git commit -m "local: take the bench lane's newer scenario tests"
make setup
uv run mockmart generate --scenario s2 --seed 7 --out runs/s2-7     # also s3, s4; scenarios: quiet s1 s2 s3 s4
uv run argus api --world runs/s2-7/world.duckdb --port 8000         # Mission Control live over that world
uv run python -m argus.investigate --world runs/s2-7/world.duckdb   # the Stage-2 investigator in the terminal
uv run argus-bench                                                   # scorecard: every built scenario x 3 seeds, Argus vs the threshold baseline
uv run argus-bench case s3 --seed 7                                  # one sealed case, verbose
uv run argus-bench blind --seed 11                                   # blind challenge in the terminal: commit, run, reveal
uv run argus-bench verify runs/bench/<case>                          # recompute a case's commitment from its reveal
git switch team/ansor/qa                                                # back to your own branch
```

If the merge reports a conflict, abort it (`git merge --abort`) and tell Batu instead of resolving it.
Why the extra checkout: `fm/argus-investigate` carries an older copy of the bench lane's commits, and without the newer `tests/bench/test_bench_scenarios.py` from `fm/argus-bench` six S2/S4 signature tests fail on a DECIMAL-vs-float comparison (test-only; checked: with the newer file those tests pass).
Checked on an equivalent local integration copy: `uv run mockmart generate` works for s2, s3, s4; `python -m argus.investigate` finishes on all three (S4: `INC-0001 SUPPORTED_CAUSE pacing_ratio`, evidence `dep_ad-pacer_1.7.0`); `uv run argus-bench case s2 --seed 7` grades Argus FAIL (0 pages but no EXPECTED note) and the threshold baseline FAIL (1 false alarm); `uv run argus-bench blind --seed 11` revealed s3 and graded PASS.
Remember that the browser still shows the Stage-1 runtime on that branch; the terminal `python -m argus.investigate` shows the Stage-2 investigator.

## 4. Definition of green (before every push)

```bash
make check
npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build
```

Both must pass.
Python: ruff (line length 120), mypy over `src/`, pytest; TypeScript: strict `tsc --noEmit`, vitest.
If `make check` was already red on your base before your change, say so in the PR with the failing output instead of hiding it.

## 5. The six contracts (read, do not change)

The pydantic models in `src/argus/contracts/` are the single source of truth; `make contracts` regenerates `contracts/`, and CI fails when they are stale.
Read `docs/contracts.md` for the full description.

| Id | Contract | Code | Generated artifact |
| --- | --- | --- | --- |
| C1 | world tables (facts, logs, as_of views) | `src/argus/contracts/world.py` | `contracts/schema.sql`, `contracts/c1_world.json` |
| C2 | metric definition YAML (`name`, `description`, `sql`) | `src/argus/contracts/metric.py` | `contracts/c2_metric.schema.json` |
| C3 | metric graph (`graph.json`: nodes, typed edges, status VALID/SUPPORTED/PROBATION/PROPOSED/BROKEN) | `src/argus/contracts/graph.py` | `contracts/c3_graph.schema.json` |
| C4 | findings, receipts, quantities, anomalies, notes, incidents, verdicts | `src/argus/contracts/findings.py` | `contracts/c4_findings.schema.json` |
| C5 | event stream (`tick`, `attention`, `edge_status`, `anomaly_opened`, `investigation_step`, `skeptic_step`, `incident_updated`, `note_logged`, `graph_changed`, `bench_progress`, `challenge_state`) and REST routes (`ROUTES`) | `src/argus/contracts/events.py` | `contracts/c5_events.schema.json` |
| C6 | investigation tools | `src/argus/contracts/tools.py` | `contracts/c6_tools.schema.json` |

The web app mirrors these types by hand in `web/src/lib/types.ts`.
Verdicts are `SUPPORTED_CAUSE`, `HYPOTHESIS`, `EXPECTED`, `DATA_ISSUE`, `UNEXPLAINED`; incident states are `open`, `investigating`, `explained`, `monitoring`, `resolved`.
The UI never computes a number itself: every number shown comes from the API as a `Quantity` with a receipt id (`web/src/components/Receipts.tsx` exports `Num`, `ReceiptChips`, `useOpenReceipt`).
If you need a field or route that does not exist, do not add it: open an issue `[contract] ...` or `[api] ...` describing the shape you need, tell Batu, and build against a sample JSON file in your own folder until it exists.

## 6. The scenarios and what Argus must conclude

| Scenario | What happens (hidden) | Correct outcome |
| --- | --- | --- |
| S1 `s1` | PayCo payment success for Android in Germany drops from about 95% to 60-72%; an Android app release ships in the same hour as a red herring | one incident, verdict `SUPPORTED_CAUSE` on `payment_success_rate` segment `DE / android / PayCo`, the release ruled out by holdout, LMDI split, EUR impact, resolved after three normal hours |
| S2 `s2` | a big FR advertiser raises its daily budget by 30-50%, planned and logged ahead | `EXPECTED`, no incident, a "didn't wake you" note citing the change in `log_ad_budgets` |
| S3 `s3` | the orders loader stalls for 3-5 hours and then backfills; a checkout hotfix deploys just before (decoy) | `DATA_ISSUE`, no business incident, identity `orders = payment_successes` broken for the stalled hours, re-check after the backfill |
| S4 `s4` | ad pacer 1.7 rolls out for DE and FR budget lines and burns budgets by about 10:00; UK, ES, NL stay on 1.6 | `SUPPORTED_CAUSE` on the pacing ratio in DE or FR citing the pacer rollout, UK/ES/NL as holdout, "traffic increased" ruled out |
| `quiet` | nothing | zero incidents |

Current measured state (bench lane, Saturday afternoon): Stage-1 Argus detects every fault with 0 false alarms but stays silent on S2 and names the wrong node on S4; the Stage-2 investigator raises the cause hit rate.
So in the browser on the integration branch, S2 and S4 may not show the correct outcome yet; that is a finding to report, not something to fake in the UI.

The demo has three "moments" that must play on one page without a human touching anything: (1) a real fault found and explained (S1), (2) a harmless change that Argus deliberately does not alarm on (S2 or S3), (3) a new metric dropped into `metrics/` that places itself in the graph with a certificate.
Plus: "click the SQL" (open a receipt, re-run it, same hash) and the blind challenge (a judge picks a hidden scenario, its truth is committed by hash before the run and revealed after).

## 7. Who owns which files (coordination rule)

Four parties change the web app at the same time: three humans and the team's coding agent `argus-api`, which keeps building on `fm/argus-api`.
To avoid stepping on each other, every file has exactly one owner:

| Owner | Owns (may change freely) |
| --- | --- |
| Youssef (`youssef-110`) | `web/src/views/**` (new screens and demo mode), `web/test/views/**` |
| Alan (`Lumberj3ck`) | `web/src/challenge/**` (blind challenge flow), `web/src/ui/**` (shared loading, error, empty states, responsive CSS), `docs/demo/**` (click path, video script support) |
| Ansor (`TheWingTheWong`) | `e2e/**` (Playwright smoke tests as their own npm package), `docs/qa/**` (test matrix, bug log, handover) |
| coding agent `argus-api` | `src/argus/api/**`, `web/src/App.tsx`, `web/src/main.tsx`, `web/src/components/**`, `web/src/lib/**`, `web/src/styles.css`, `web/package.json`, `web/package-lock.json`, `web/vite.config.ts`, `web/index.html`, `web/test/store.test.ts`, `web/README.md` |
| other coding agents (never touch) | `src/argus/contracts/`, `contracts/`, `src/argus/watcher/`, `src/argus/detect/`, `src/argus/decompose/`, `src/argus/investigator/`, `src/argus/investigate/`, `src/argus/incidents/`, `src/argus/runtime/`, `src/argus/skeptic/`, `src/argus/llm/`, `src/argus/graph/`, `src/argus/semantic/`, `src/argus/cartographer/`, `src/argus/narrator/`, `src/argus/mcp/`, `src/mockmart/`, `src/bench/`, `graph/`, `metrics/`, `fixtures/`, `tests/` outside your own folder, `.github/workflows/`, `Makefile`, `pyproject.toml`, `uv.lock`, `README.md` |

Rules:

1. Change only files you own.
2. **Hook edits.**
   When your feature needs a small change in a file someone else owns (one import, one mount point, one CSS import, one npm script), make it a separate, tiny PR titled `hook: <what>` with at most about 10 changed lines, and tell Batu in the team chat before you push, so Batu can tell the coding agent to rebase.
   Your owned files must still build without the hook.
   The hooks you are expected to need are listed in your own task section; anything bigger is a request, not an edit.
3. **Bug fixes in other people's files** are allowed only for a filed issue, one bug per PR, titled `fix(<area>): <bug> (#<issue>)`, touching only the lines of that bug, and only after Batu confirms in the chat that nobody else is on it.
4. **Never** edit generated files (`contracts/`, `web/dist/`, `fixtures/`), lock files of folders you do not own, or the CI workflow.
5. Need something the API does not serve yet? Open an issue `[api] need <route> returning <shape>` and build against a sample JSON committed in your own folder; switch to the real route when it lands.
6. Rebase on the shared base every 60 to 90 minutes and before each PR: `git fetch origin && git rebase origin/fm/argus-api`.
   Force-push only your own branch, and only with `git push --force-with-lease`.

## 8. Commits, PRs, handover

- Branch: `team/ansor/qa` from `origin/fm/argus-api`; use one branch per topic (`team/ansor/<topic>`), small PRs over one big one.
- Commits: Conventional Commits in English (`feat(web): ...`, `fix(api): ...`, `test(e2e): ...`, `docs(qa): ...`); never add an AI agent as co-author.
- Push: `git push -u origin <your-branch>`.
- PR: `gh pr create --base fm/argus-api --head <your-branch> --title "<conventional title>" --body-file <file>`.
  The base is `fm/argus-api` until Batu announces that `main` has landed; then change the base with `gh pr edit <url> --base main`.
  If the PR shows commits that are not yours, rebase onto the latest `origin/fm/argus-api`.
- PR body: what and why, how you tested it (exact commands and their result), screenshots or a short screen recording for every visible change, what is still open, and `Closes #<n>` for issues.
- Do not merge; Batu merges.
- Handover: at the end of every time box (section 10) push, open or update the PR, and post one message in the team chat with the PR URL, what works, what does not, and how to try it.
  Keep your handover note current in `docs/qa/HANDOVER.md` so someone else (or a fresh agent) can continue from the file alone.

## 9. "Does everything work?" checklist (run it before every handover)

- [ ] Fresh clone of your branch: `make setup && make check` green, `make s1` prints `ALL PASS`.
- [ ] `npm --prefix web install && npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build` green.
- [ ] `make api`, open http://127.0.0.1:8000: header says `Replay · recorded run`, the graph shows the seed graph (27 metrics), the feed fills, `INC-0001` appears with verdict `SUPPORTED_CAUSE` on `DE / android / PayCo`, the release appears as ruled out.
- [ ] Clicking a number opens its receipt with the SQL and `as_of`; in `make demo` the re-run shows the same hash.
- [ ] Play, pause, speed and restart work; after restart the page resets cleanly (no duplicated cards).
- [ ] "While you slept" (digest) opens and every line has receipts.
- [ ] Stop the API: the page shows the offline banner; start it again: the page recovers without a reload.
- [ ] No errors in the browser console, no failed network requests other than the documented 501 stubs.
- [ ] 1920x1080 (the video) and 1440x900 (laptop) look clean; nothing overlaps, nothing is cut off.
- [ ] Your own feature works in replay and in live mode, and the checklist items of your task section pass.

## 10. Time box

Times are CET (local Berlin time).

| When | Checkpoint | What you deliver |
| --- | --- | --- |
| Sat 18:45 | C1 running skeleton | setup done, first PR open (even small), your section's first item working |
| **Sat ~20:00** | **first demoable state** | your first-priority items demoable on `make api`; handover message in the chat |
| Sat 22:30 | C2 two moments | the fault (S1) and a harmless change visible in the UI without an LLM; screen recording "backup 1" of the app |
| Sun 08:00 | C4 proof, stand-up | bench table and blind challenge working over Wi-Fi; read the bug list, take your share |
| Sun 10:30 | go/no-go | is the blind challenge the opener? live or replay? |
| **Sun 11:00** | **feature freeze** | after this only bug fixes with a test and a second pair of eyes, no new features |
| Sun 12:00 | rehearsal 1 | full run with a stopwatch, someone plays jury |
| Sun 12:30-14:00 | video | 3-minute video recorded and cut |
| Sun 14:30 | rehearsal 2 | with failure drill (Wi-Fi off, API key off) |
| Sun 15:30 | submit | 60 minutes buffer before the 16:30 deadline |

If an item will not make its checkpoint, cut scope rather than sleep, and say so in the chat.

## 11. Your task: end-to-end QA of Mission Control

You are the team's QA owner.
Goal: by the feature freeze the team knows, with evidence, which of the scenarios play correctly in the browser, every bug is filed with a reproduction, the small ones are fixed, and a Playwright smoke suite catches regressions in one command.
You do not build features and you do not touch the backend lanes; you find the truth and make it visible.

Your folders: `e2e/` and `docs/qa/`.
Your branch prefix: `team/ansor/`, first branch `team/ansor/qa`.

### 11.1 Baseline (first 30 minutes)

1. Clone, set up, and run everything in section 3.2 and 3.3 on `origin/fm/argus-api`; record the exact output (pass counts, timings, warnings) in `docs/qa/baseline.md`.
2. Run the checklist in section 9 by hand in Chrome and note every deviation.
3. Build the local integration branch from section 3.4 and confirm `uv run mockmart generate --scenario <s> --seed 7 --out runs/<s>-7` works for `quiet`, `s1`, `s2`, `s3`, `s4`.

Acceptance: `docs/qa/baseline.md` lists every command, its result, and the commit hash it ran on.

### 11.2 Scenario matrix in the browser

For each row, run it, watch the page until the run ends, and record observed versus expected (section 6):

| Run | How |
| --- | --- |
| S1 replay | `make api` |
| S1 live, seeds 7, 3, 11 | `make demo SEED=<n>` |
| quiet live | integration branch: `uv run mockmart generate --scenario quiet --seed 7 --out runs/quiet-7`, then `uv run argus api --world runs/quiet-7/world.duckdb --tick-seconds 0.5` |
| S2, S3, S4 live, seed 7 | integration branch, same pattern with `--scenario s2` / `s3` / `s4` |
| S2, S3, S4 in the terminal | integration branch: `uv run python -m argus.investigate --world runs/<s>-7/world.duckdb` and `uv run argus-bench case <s> --seed 7` |

For every run note: verdict and segment shown, number of incidents, notes ("didn't wake you", data issue), whether the investigation trail is readable, whether receipts open and (live) re-run to the same hash, time until the incident appears, console errors, anything confusing for a judge.
Write it as one table in `docs/qa/matrix.md`, one row per run, columns: run, expected, observed in UI, observed in terminal, verdict ok (yes/no), bugs (issue links).

Acceptance: all rows filled; every "no" links to an issue.

### 11.3 File bugs as GitHub issues with a reproduction

Use `gh issue create --repo ArgusSearch/argus --title "<area>: <one-line symptom>" --body-file <file>`; areas: `web`, `api`, `brain` (detection or investigation verdicts), `graph`, `bench`, `docs`.
If the labels `bug`, `qa` and the area exist, add them with `--label`; do not create or rename labels.
Body template:

```
Branch and commit: fm/argus-api @ <sha>   (or local/integration = fm/argus-api + ... @ <shas>)
Command: <exact command(s)>
Steps: 1. ... 2. ... 3. ...
Expected: <what the scenario's truth or the UI contract says>
Observed: <what happened, with the exact text, numbers, console error>
Evidence: <screenshot or recording, the relevant event lines from GET /events or fixtures/events.jsonl>
Severity: P0 breaks the demo / P1 visible to a judge / P2 polish
Suspected area: <file path if you know it>
```

One bug per issue; search open issues first (`gh issue list --repo ArgusSearch/argus --search "<words>"`) to avoid duplicates.
Post every P0 in the team chat immediately with the issue URL.
Verdict bugs in `brain` or `graph` are reported, not fixed by you; the coding agents own those folders.

### 11.4 Fix what is small and in the UI or API

You may fix P0 and P1 bugs in `web/src/**` and `src/argus/api/**` under rule 3 of section 7: issue first, Batu confirms nobody else is on it, one bug per PR, `fix(web|api): ... (#n)`, a test that fails before and passes after (vitest in `web/test/` for pure logic, pytest in `tests/api/` for API behaviour, or a Playwright spec in `e2e/`).
Do not refactor while fixing.

### 11.5 Playwright smoke tests (`e2e/`, its own npm package)

Keep Playwright out of `web/package.json` so you never collide with the web owners: create `e2e/package.json` (`"private": true`, devDependency `@playwright/test`, scripts `"test": "playwright test"`), `e2e/playwright.config.ts`, `e2e/tests/*.spec.ts`, and `e2e/README.md`.
Install with `npm --prefix e2e install && npx --prefix e2e playwright install chromium`.

The config's `webServer` starts the API from the repository root on a free port, for example `command: "uv run argus api --port 8010"`, `cwd: ".."`, `url: "http://127.0.0.1:8010/health"`, `reuseExistingServer: !process.env.CI`; the tests require `web/dist` to exist, so the README says to run `npm --prefix web run build` first and the first test fails with a clear message when `/` still serves the "Mission Control is not built yet" page.
Add a second project or env switch for live mode (`uv run argus api --port 8011 --world runs/s1-7/world.duckdb --tick-seconds 0.2` after `make world SEED=7`).

Smoke specs (use role and text selectors; if you really need `data-testid`, request it as a hook edit):

1. `health.spec.ts`: `GET /health` is `status: ok`, `mode: replay`; `GET /routes` marks the not-yet-built routes `status: stub`, and each of them answers 501.
2. `load.spec.ts`: the page title is `Argus · Mission Control`, the header shows `Replay · recorded run`, the graph renders nodes, no console errors.
3. `s1-replay.spec.ts`: set speed to the fastest option, wait for `INC-0001`, open it, assert `SUPPORTED_CAUSE` (or its display label), `DE`, `android`, `PayCo`, and that the release is ruled out; "Copy report" or the report view contains the markdown report.
4. `receipt.spec.ts`: clicking a number opens the receipt drawer with SQL and `as_of`; in live mode the re-run shows the same hash.
5. `controls.spec.ts`: pause stops the ticker, restart clears the feed and refills it without duplicates.
6. `offline.spec.ts`: with the API stopped the offline banner appears.
7. `digest.spec.ts`: "While you slept" opens and shows lines.

Acceptance: `npm --prefix e2e test` runs all specs green twice in a row on a fresh `make api` in under 3 minutes; flaky specs are fixed, not retried.
Wiring it into CI touches `.github/workflows/ci.yml`, which you do not own: propose it in an issue for Batu instead.

### 11.6 Your checklist

- [ ] `docs/qa/baseline.md`, `docs/qa/matrix.md`, `docs/qa/HANDOVER.md` exist and are current.
- [ ] Every "no" in the matrix links to an issue with a reproduction.
- [ ] `npm --prefix e2e test` green twice in a row.
- [ ] Re-run the matrix after every merge into `fm/argus-api` that touches the UI, and before the Sunday 11:00 freeze and 12:00 rehearsal.

Priority order if time runs short: 11.1, 11.2 for S1 and S2, 11.3, 11.5 specs 1-3, 11.2 for S3 and S4, 11.4, the rest of 11.5.
By Saturday ~20:00: baseline, S1 rows of the matrix, first issues filed, specs 1-3 green.
