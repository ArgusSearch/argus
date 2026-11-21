# Argus team prompt for Alan (Lumberj3ck): demo flow and polish

You are the coding agent of Alan (GitHub `Lumberj3ck`), one of three human teammates on the Argus hackathon team.
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
You have been invited: accept the invitation first (from the GitHub email, from https://github.com/ArgusSearch/argus/invitations, or from https://github.com/orgs/ArgusSearch/invitation if it came as an organization invite). Then check access with `gh auth status` (log in with `gh auth login` if needed) and `git ls-remote https://github.com/ArgusSearch/argus.git`, which must list the `fm/*` branches below.

```bash
git clone https://github.com/ArgusSearch/argus.git
cd argus
git fetch origin
git switch -c team/alan/polish origin/fm/argus-api
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
git switch team/alan/polish                                                # back to your own branch
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

- Branch: `team/alan/polish` from `origin/fm/argus-api`; use one branch per topic (`team/alan/<topic>`), small PRs over one big one.
- Commits: Conventional Commits in English (`feat(web): ...`, `fix(api): ...`, `test(e2e): ...`, `docs(qa): ...`); never add an AI agent as co-author.
- Push: `git push -u origin <your-branch>`.
- PR: `gh pr create --base fm/argus-api --head <your-branch> --title "<conventional title>" --body-file <file>`.
  The base is `fm/argus-api` until Batu announces that `main` has landed; then change the base with `gh pr edit <url> --base main`.
  If the PR shows commits that are not yours, rebase onto the latest `origin/fm/argus-api`.
- PR body: what and why, how you tested it (exact commands and their result), screenshots or a short screen recording for every visible change, what is still open, and `Closes #<n>` for issues.
- Do not merge; Batu merges.
- Handover: at the end of every time box (section 10) push, open or update the PR, and post one message in the team chat with the PR URL, what works, what does not, and how to try it.
  Keep your handover note current in `docs/demo/HANDOVER.md` so someone else (or a fresh agent) can continue from the file alone.

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

## 11. Your task: demo flow and polish

You own how Argus looks and feels in front of a judge: the blind challenge flow, every loading and error state, responsiveness, performance, the English copy, and the exact click path the video is recorded from.
The coding agent `argus-api` keeps building the page on `fm/argus-api` at the same time, so new code goes into your folders and changes to existing components are small, announced PRs.

Your folders: `web/src/challenge/`, `web/src/ui/`, `docs/demo/`.
Your branch prefix: `team/alan/`, first branch `team/alan/polish`.

### 11.1 Read first

- `web/README.md` (run modes, conventions), `web/src/App.tsx`, `web/src/components/Header.tsx` (mode badge, play, pause, speeds 1/2/4/8, restart), `web/src/lib/api.ts` (`api.*`, `ApiError`, the `follow()` SSE client with `connecting | open | offline`), `web/src/styles.css` (2026 lines of CSS variables and classes).
- Today the only media query is `prefers-reduced-motion`; there is no layout for narrow screens yet.
- Loading and error handling today is a plain "Loading…" text in `IncidentSheet.tsx`, `Overlays.tsx`, `Receipts.tsx` and an offline banner in `App.tsx`.
- `npm --prefix web run build` warns that the main chunk is 521 kB (gzip 169 kB).

### 11.2 Tasks, in priority order

**A1 Click path for the video and the live demo** (`docs/demo/click-path.md`), start now, refine all night.
The video is 3 minutes: cold open on the finished incident report, then three beats (fault S1, harmless change S2 or S3, new metric placing itself), then the bench, then the closing line.
Write the exact sequence: commands to start (`make api` for replay, or `make demo SEED=<n>`), browser and window size (1920x1080, zoom 100%), which URL (Youssef's demo mode is `http://127.0.0.1:8000/?demo=1`), every click with the screen it lands on, the seconds it takes, what the narrator says (one line per beat), and the fallback if something fails live (replay instead of live, recorded backup video).
Time every step with a stopwatch on `make api` and note which steps are not built yet as `MISSING:` lines with an issue link.
Acceptance: someone who has never seen the app can record the video from the file alone.

**A2 Loading, empty and error states** (`web/src/ui/`).
Build small primitives: `Spinner`, `Skeleton` (for cards, graph, sheets), `EmptyState` (for example "No incidents. Argus is watching 27 metrics." in the feed before the first incident), `ErrorState` (message, the failed route, a retry button), `OfflineBanner` (connecting vs offline, auto-retry visible).
Then apply them in existing components through small PRs under section 7 rule 3 (one component per PR, announced), starting with the places listed in 11.1.
Every error state names the cause in plain English (for example "Receipt re-runs need live mode: start `make demo`" for the 409 in replay).
Acceptance: start the page with the API stopped, then start it: no blank screen, no raw JSON, no stack trace at any moment; vitest for any pure helper.

**A3 Blind challenge flow** (`web/src/challenge/`).
The judge picks a hidden scenario; Argus commits to the truth by hash before it runs; after the run the truth is revealed and anyone can recompute the hash on their phone.
What exists: the terminal flow `uv run argus-bench blind --seed <n>` on the local integration branch (section 3.4) writes `runs/bench/blind-<n>/challenge.jsonl` with three C5 `challenge_state` payloads (`committed`, `running`, `revealed`; fields `state`, `commitment`, `reveal`), where the `revealed` payload's `reveal` has `scenario`, `seed`, `nonce`, `payload`, `verified`, `grade`.
The commitment is `"sha256:" + hex(SHA-256(nonce + "\n" + payload))` over the UTF-8 string (`src/bench/sealed.py` on `fm/argus-bench`; checked: recomputing it from `reveal.json` matches).
The API routes `POST /challenge/commit` and `POST /challenge/reveal` still answer 501 (bench lane); the `challenge_state` event type is reserved in C5.
Build against recorded samples first: run `uv run argus-bench blind --seed 11` on the integration branch and copy its `challenge.jsonl` into `web/src/challenge/fixtures/`.
Screens:
1. Big-screen card: "A judge picks a number" (seed input or "random"), then the commitment hash shown large with a QR code linking to the phone page.
2. Running: the normal Mission Control page with a small banner "Hidden scenario, committed sha256:…".
3. Reveal: scenario name, seed, Argus's verdict versus the truth, the grade, and "verified" recomputed in the browser.
4. Phone page (`/?challenge=verify` or similar, mobile layout at 390 px width): paste or scan the commitment, then the nonce and payload after the reveal, recompute and show match or mismatch.
Pitfall: `crypto.subtle` exists only in secure contexts (https or `localhost`); a phone opening `http://192.168.x.x:8000` has no `crypto.subtle`, so ship a fallback SHA-256 (write it yourself from FIPS 180-4, about 80 lines with a vitest against known vectors, or add a small MIT library such as `@noble/hashes` with a line in `docs/decisions.md`).
For the QR code, a small MIT library is fine (note it in `docs/decisions.md`).
The phone reaches the laptop only if the API listens on the LAN: `uv run argus api --host 0.0.0.0 --port 8000` (the `--host` flag exists in `src/argus/cli.py`); test it on a real phone in the venue Wi-Fi and over a hotspot.
Open an issue `[api] blind challenge routes: commit, state stream, reveal` with the shapes you need so Batu can route it to the bench lane; when the routes land, swap your sample loader for them.
The single hook you may need: one entry in `web/src/App.tsx` (or Youssef's `ViewHost` once it exists) that renders your challenge screens when the URL asks for them, announced as a `hook:` PR.
Acceptance: with the sample, the full flow works on the big screen and on a real phone, the hash check passes for the real reveal and fails visibly when one character of the payload changes (vitest).

**A4 Responsiveness** (`web/src/ui/responsive.css`, imported once).
Breakpoints: 1920x1080 (video and projector, the most important), 1440x900 (laptop), 1280x720 (low projector), 768 (tablet), 390 (phone: only the challenge and the morning report need to work there).
The hook: one `import "./ui/responsive.css";` line in `web/src/main.tsx`, announced.
Acceptance: screenshots at all five sizes in the PR, nothing overlaps or is cut off, text stays readable from 3 metres on the projector size.

**A5 Performance.**
Measure first: Chrome Performance panel while `make api` replays at speed 8, React Profiler, `npm --prefix web run build` chunk sizes.
Targets: no frame over 50 ms during the S1 walk, the graph pans smoothly, first paint under 1.5 s on the laptop, main chunk under 500 kB (for example by lazy-loading the incident page, receipts and your challenge screens with `React.lazy`; that edit in `App.tsx` is a hook PR).
Acceptance: before and after numbers in the PR description.

**A6 English copy.**
Walk every visible string (headers, buttons, card texts, legends, tooltips, empty and error states, the digest) and make the terms consistent: "incident", "note", "didn't wake you", "receipt", "re-run", "ruled out"; verdicts shown as readable labels (`SUPPORTED_CAUSE` as "Supported cause", `DATA_ISSUE` as "Data issue", and so on) without changing the API values.
Deliver as one PR per component with only string changes, or as a list in an issue if the component is being changed by someone else right now.
Acceptance: a native-level English reader finds no typo, no German, no internal jargon (no "lane", "fixture", "C5").

### 11.3 Your checklist

- [ ] `docs/demo/click-path.md` timed end to end; every `MISSING:` line has an issue.
- [ ] With the API stopped and restarted, the page never shows a blank screen or raw error.
- [ ] Blind challenge sample flow works on the big screen and on a real phone (Wi-Fi and hotspot), hash check verified both ways.
- [ ] Screenshots at 1920x1080, 1440x900, 1280x720, 768 and 390 in the PRs.
- [ ] Build chunk size and frame times measured before and after.
- [ ] `docs/demo/HANDOVER.md` (your handover note) is current.

By Saturday ~20:00: A1 first draft timed on `make api`, A2 primitives built and the first one applied.
By Saturday 22:30: A1 used for the backup recording, A4 at 1920x1080 and 1440x900.
A3 by Sunday 08:00 (the blind challenge go/no-go is Sunday 10:30); A5 and A6 before the 11:00 freeze.
