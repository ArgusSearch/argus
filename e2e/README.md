# Argus e2e smoke suite

Playwright smoke tests for Mission Control (the page in `web/dist`, served by `argus api`). They drive a real
Chromium against a real API and check what a judge would see in the demo.

Base: `main` (every lane merged: Stage-2 runtime, detect, a recording per scenario under `fixtures/`). Work on
`team/ansor/qa` rebased onto `origin/main`; PRs target `main`. Edit only `e2e/**` and `docs/qa/**`.

## What it covers

| Spec | What it checks | Replay | Live |
| --- | --- | --- | --- |
| `health.spec.ts` | `GET /health` is ok in the expected mode; every route `GET /routes` marks `stub` answers 501; every implemented plain `GET` answers < 400 | runs | runs |
| `load.spec.ts` | the page loads with the header mode, the seed graph (one box per metric and per log, edges drawn), the clock starts ticking, no console errors or failed requests | runs | runs |
| `controls.spec.ts` | Pause freezes the run and the clock, Play resumes it | runs | runs |
| `controls.spec.ts` | Restart empties the feed and refills it to the same count, one INC-0001, no duplicate cards | runs | skipped (replay control) |
| `s1-replay.spec.ts` | the S1 story: INC-0001 becomes SUPPORTED CAUSE in DE / android / PayCo, the release `android-app 8.3.0` is ruled out, "Copy report (Markdown)" and `/incidents/INC-0001/report` carry it | runs | skipped (replay-only) |
| `receipt.spec.ts` | a number in the incident sheet opens its receipt (SQL, pinned `as_of`); "Re-run SQL" shows `✓ Same hash` in live and the documented 409 message in replay | runs | runs |
| `digest.spec.ts` | "While you slept" opens, has lines, "Copy as Markdown" is enabled, Escape closes it | runs | runs |
| `offline.spec.ts` | stopping the API shows the offline banner and "API offline"; starting it again recovers without a reload | expected failure (see below) | expected failure |
| `graph-restart.spec.ts` | the metric graph never goes blank (`visibility: hidden`) in the 4 s after each of three replay restarts | runs (#33 fixed on main) | skipped (replay-only) |
| `graph-nodes.spec.ts` | on every metric node the unit text (COUNT/RATE/EUR) ends before the sparkline starts | expected failure until #14 is fixed (PR #40) | runs |
| `checking-label.spec.ts` | after the S1 verdict the graph bar no longer says "checking …" | expected failure until #13 is fixed (PR #41) | skipped (replay-only) |
| `verdict-labels.spec.ts` | the S1 verdict reads "SUPPORTED CAUSE" on the page and in the digest: no raw enum, no "root cause" | expected failure until #15 is fixed (PR #60) | skipped (replay-only) |
| `trail-cards.spec.ts` | at 1920x1080 and 1440x900 every card visible in the investigation row is whole | expected failure until #16 is fixed (PR #61) | skipped (replay-only) |
| `scenarios.spec.ts` | every recorded scenario on its own replay API (`--replay fixtures[/<s>]`) at 64x to `run.finished`: S1 one SUPPORTED CAUSE card in DE / android / PayCo; quiet no incident card; S2 no incident card and a "Didn't wake you" card about the budget (tab count > 0); S3 no incident card and a "Data issue · held back" card; S4 one SUPPORTED CAUSE card naming pacing and DE or FR; S5 three market "Didn't wake you" notes and one resolved SUPPORTED CAUSE card in DE / android / PayCo | runs (about 50 s) | skipped (replay-only) |
| `fx.spec.ts` | the "Argus Ice" workspace (after the IA redesign, e0ce93b) on its own replay API (`--replay fixtures`): `?fx=1&fxintro=0` sets `html[data-fx=ice]`, the loader leaves, the overview shows its five KPI tiles (cost, open incidents, key metrics normal "7 of 7", small moves, human actions), the shop health gauge and one "Key metrics, this hour" row per north-star metric, no console errors or failed requests (501 stubs and 409s allowed); S1 at 64x puts INC-0001 "Supported cause (evidenced)" in Germany / Android / PayCo in the overview's decisions and in Incidents, "See why" and "Open" open its incident page (What happened, Copy report) and Escape goes back; every sidebar section (Overview, Incidents, Live investigation, While you slept, Visualization, Village, Metric tree, Track record, Glossary) opens by click, and the view keys 1-5 switch Visualization, Metric tree, Live investigation, While you slept, Track record; the visualization shows the 3D scene's canvas (headless Chromium has WebGL2 via SwiftShader) or the classic graph, with the "what the map shows" panel; the village (lane G) opens from the sidebar with its seven agents, a three.js (or 2D) stage and a tape that plays; `?fx=night` sets `data-fx=night`; the recording URL `/?demo=1&captions=1&fx=1` restarts the replay at 2x by itself, shows a caption from the start, switches to Live investigation on the first step, captions the verdict, opens the INC-0001 incident page 3.5 s after it and leaves it by itself back to the overview (the test fast-forwards the server, never touches the page). With `ARGUS_E2E_SHOTS=1` it also saves `fx-*.png` | runs (about 2.5 min on an 8 GB Mac); "key 1 on the overview opens the visualization (#63)" is an expected failure, and any test marks itself as one when the page logs a skipped view transition (see below) | skipped (replay-only) |
| `new-metric.spec.ts` | demo moment 3, "a new metric places itself in the graph", on its own replay API (port 8015) at 1920x1080: `POST /graph/metrics` with `cost_per_impression.yml` shows the "New metric placed" card (EXACT, parents CTR × CPC, feeds Ad spend, breakdowns, headline with the residual, certificate) and the node appears in the graph with the placed highlight (one box more, as many boxes as `GET /graph` has metrics and logs: the graph bar is plain copy since the IA redesign); the tree marks the row; the card's "Add the ad metric pack" button places the other four: the AMBIGUOUS card shows the probation parent and the alternative parent, the REJECTED card the fan-out ×6.72 and the repair diff, four marked nodes, none for the rejected metric; the graph refits to every node after each of four API posts; a placement before the page's first poll still shows its node; in the fx look (sidebar "Visualization", once the scene has built the seed graph) the card shows and the 3D scene gets a "new metric" block (skipped with `ARGUS_E2E_FX=0`). No console errors, no HTTP errors. With `ARGUS_E2E_SHOTS=1` it saves `new-metric-*.png` | runs (about 30 s, 45 s with fx); "a placement before the page's first poll" is an expected failure, and the refit test marks itself as one when it hits the random miss (see below) | skipped (replay-only) |
| `screenshots.spec.ts` | not a check: captures the QA screenshots, skipped unless `ARGUS_E2E_SHOTS=1` | skipped by default | skipped (replay-only) |

## Prerequisites

From the repo root:

```sh
make setup                                   # Python env (uv sync)
npm --prefix web install && npm --prefix web run build   # the page the API serves
npm --prefix e2e install
npx --prefix e2e playwright install chromium
```

If `web/dist` is missing, the page says "not built yet" and every UI spec fails with a message pointing at the build.

## Running

Replay mode: `npm --prefix e2e test` runs the core specs in about 3 min on an 8 GB Mac. The demo-specific specs run separately:
- `npm --prefix e2e run test:demo` runs `fx.spec.ts` (the Argus Ice workspace, the village and the recording URL `/?demo=1&captions=1&fx=1`) and `new-metric.spec.ts` (demo moment 3, a new metric placing itself), about 3.5 min on an 8 GB Mac;
- `test:fx` runs only the fx spec;
- `test:all` runs everything.

Before a rehearsal, run `test` and then `test:demo`.

```sh
npm --prefix e2e test
npm --prefix e2e test -- receipt          # one spec
```

Live mode (about 45 s): generate the S1 world once, then Playwright starts
`uv run argus api --port 8011 --world runs/s1-7/world.duckdb --tick-seconds 0.2`.

```sh
make world SEED=7                          # writes runs/s1-7 (gitignored)
npm --prefix e2e run test:live
```

Environment flags:

| Variable | Effect |
| --- | --- |
| `ARGUS_E2E_MODE=live` | live mode (what `test:live` sets) |
| `ARGUS_E2E_WORLD` | the world live mode runs over (default `runs/s1-7/world.duckdb`) |
| `ARGUS_E2E_PORT` | the main server's port (default 8010 replay, 8011 live) |
| `ARGUS_E2E_OFFLINE_PORT` | `offline.spec.ts`'s own server (default 8012) |
| `ARGUS_E2E_SCENARIO_PORT` | `scenarios.spec.ts`'s own server (default 8013) |
| `ARGUS_E2E_SCENARIOS=0` | skip `scenarios.spec.ts` (saves about 40 s) |
| `ARGUS_E2E_NEWMETRIC=0` | skip `new-metric.spec.ts` (what `npm test` sets) |
| `ARGUS_E2E_FX=0` | skip `fx.spec.ts` (what `npm test` sets; `test:fx` and `test:all` run it) |
| `ARGUS_E2E_FX_PORT` | `fx.spec.ts`'s own server (default 8014) |
| `ARGUS_E2E_NEWMETRIC_PORT` | `new-metric.spec.ts`'s own server (default 8015) |
| `ARGUS_E2E_SHOTS=1` | capture the QA screenshots (`screenshots.spec.ts`, `scenario-<s>.png` from `scenarios.spec.ts`, `fx-*.png` from `fx.spec.ts`) |
| `ARGUS_E2E_ROOT` | the repository checkout whose `argus api` (and `web/dist`) the suite runs; default `..`. Use it to test a fix branch from another worktree |
| `CI` | never reuse a running server; also write the HTML report |

Outside CI an API already listening on the port is reused, so stop stray servers first
(`pkill -f "argus api --port 801"`) or you test whatever that server is running.

QA screenshots (replay, 1920x1080 and 1440x900, into `docs/qa/screenshots/`; the scenario end states at
1920x1080 as `scenario-<s>.png`):

```sh
ARGUS_E2E_SHOTS=1 npm --prefix e2e test -- screenshots scenarios
ARGUS_E2E_SHOTS=1 npm --prefix e2e run test:fx         # fx-*.png: Argus Ice at 1920x1080 (the overview, fx-dashboard-*, also 1440x900), the incident page, the visualization, the village, night, captions
```

Failure traces and screenshots land in `e2e/test-results/`; `npx --prefix e2e playwright show-trace <trace.zip>`.

## Ports

| Port | Used by |
| --- | --- |
| 8010 | main API, replay mode (Playwright `webServer`) |
| 8011 | main API, live mode |
| 8012 | `offline.spec.ts` starts and stops its own replay API here (`ARGUS_E2E_OFFLINE_PORT`) |
| 8013 | `scenarios.spec.ts` starts one replay API per scenario here, one at a time (`ARGUS_E2E_SCENARIO_PORT`) |
| 8014 | `fx.spec.ts` starts one replay API for the whole spec here (`ARGUS_E2E_FX_PORT`) |
| 8015 | `new-metric.spec.ts` starts one replay API for the whole spec here, so its placements never reach the main server's graph (`ARGUS_E2E_NEWMETRIC_PORT`) |

8020-8029 belong to other agents' API servers, leave them alone.
The self-started servers go through `tests/own-api.ts`: bounded start (30 s), stop in `afterEach` (`afterAll` for `fx.spec.ts` and `new-metric.spec.ts`; SIGINT to the
process group, SIGKILL after 5 s), and a refusal to start when the port already answers.

## Why one worker

The replay is global server state: play, pause, speed and restart act on the one run every open page follows,
and live mode has a single run that only moves forward. Two specs in parallel would restart or pause each other's
run. `workers: 1`, `fullyParallel: false`, `retries: 0`; a flaky spec is a bug to fix, not to retry.
In live mode the specs depend on file order (load and controls run before the incident exists; digest and
receipt wait for it), which Playwright keeps with one worker.

## The expected failure in offline.spec.ts

`offline.spec.ts` asserts the correct behaviour but is marked
`test.fail(true, "offline banner never shows: https://github.com/ArgusSearch/argus/issues/6")`.
When the API stops, the browser keeps the `EventSource` in CONNECTING and retries forever, so
`web/src/lib/api.ts` never reports "offline" (it only does on `CLOSED`), and the header falls back to the last
known mode. Observed 5 s and 30 s after the stop: no banner, header still "Replay · recorded run", clock frozen,
only the replay controls disappear. The list reporter shows this test as `✘` but counts it as passed. Once the
bug is fixed the test passes, Playwright reports it as "expected to fail", and the suite goes red: then remove
the `test.fail` line (the comment above it says so).

Re-checked on `main` @ f35b00a: still fails the same way (`web/src/lib/api.ts:103` unchanged).

The spec stops its own server in `afterEach` (via `tests/own-api.ts`), so a failure or timeout never leaves port
8012 busy, and it refuses to start if 8012 is already serving.

## The expected failure in fx.spec.ts

"key 1 on the overview opens the visualization (#63)" is marked `test.fail(...)`. With `?fx=1` the workspace's own pages
(Overview, Incidents, Glossary, Village) sit on top of the view host's "Graph" tab, so pressing `1` there selects a tab
that is already selected: no `aria-selected` changes, `watchHost` in `web/src/fx/nav.ts` never hears it, and the page
stays. From a view of the host (Track record, Metric tree, ...) `1` opens the visualization (covered by the keys test).
The shortcuts are the view host's 1-5 (Visualization, Metric tree, Live investigation, While you slept, Track record),
in a different order than the sidebar, and the workspace pages have none. Re-checked after the IA redesign (e0ce93b):
`1` on the overview and on the glossary still does nothing. Once fixed, the test passes, Playwright reports "expected to
fail", and the `test.fail` line goes.

## The conditional expected failure in fx.spec.ts: a skipped view transition

Found on `main` @ e0ce93b. `transition()` in `web/src/fx/nav.ts` runs each page change as a view transition and catches
only its `finished` promise. When a new page change starts while one still runs, the browser skips the older transition
and rejects its `ready` promise, which nobody handles: "Uncaught (in promise) AbortError: Transition was skipped. New
ViewTransition started". Reproduction: open `/?fx=1&fxintro=0` and press `5`, `2`, `3` in quick succession (one error per
burst, every time); in the suite it also comes from demo mode's own switches and the keys test on a loaded machine.
Every fx test ends with `noErrors(...)`: any other error fails the test; when the only errors are this one, the test
calls `test.fail(true, ...)` and Playwright counts the hit as an expected failure, otherwise it passes. Remove that
branch once `nav.ts` also catches `.ready` (or `.updateCallbackDone`).

## What changed in fx.spec.ts with the IA redesign (e0ce93b)

The redesign (`fm/argus-ia-redesign`, `fm/argus-lane-f`, `fm/argus-lane-g`) renamed and regrouped the sidebar, replaced the
dashboard with a plain-words overview and the incident sheet with an incident page, and hides the activity feed in the fx
look. The spec follows it: Dashboard is Overview (`main "overview"`), Investigations is Live investigation, Morning report
is While you slept, Metric graph is Visualization, Scorecard is Track record; Incidents, Village and Glossary are new. The
KPI cards per north-star metric are now the five KPI tiles plus one "Key metrics, this hour" row per north-star metric. The
verdict reads "Supported cause (evidenced)" and the place "Android in Germany via PayCo". "Open report" on a dashboard row
(a dialog) is now "See why" (overview) or "Open" (Incidents) to the incident page, and demo mode opens and leaves that page.
The feed card is no longer checked: the feed is hidden in the fx look by design (`workspace.css`, "the feed steps aside").

## The demo report hold (found after the IA redesign, not an expected failure)

On the recording URL the incident page should stay `hold` (12 s) and then return to the overview. It leaves after about
8 s. In `fixtures/events.jsonl` the verdict step (seq 140, `incident_id: null`) comes one event before the incident update
(seq 141). When the page renders between the two, `closedWithoutIncident` (`web/src/views/demo/demo.ts`) counts S1's
investigation as one that ended without an incident and schedules `setTab("graph")` `hold` seconds after the verdict;
3.5 s later the incident opens, and the early `setTab("graph")` takes the workspace back to the overview (`followHost` in
`nav.ts`) 3.5 s before the incident's own close. With the old sheet the tab switch happened under the dialog, so nobody
saw it. The recording test only asserts that the page leaves by itself (within 16 s) and records the time it stayed open
as the annotation "report open for" (also printed).

## The expected failures in new-metric.spec.ts

Found on `main` @ 2c62f8b (the graph extension), both still so on `main` @ e0ce93b. Both tests assert the correct behaviour.
Since the IA redesign the graph bar no longer counts the metrics, so the spec counts the rendered boxes (27 metrics and 4
change logs on the seed, `SEED_BOXES`), and the fx check opens the graph through the sidebar's "Visualization".

- "a placement that lands before the page's first poll still puts its node in the graph" is marked `test.fail(...)`.
  `useGraphExtension` (`web/src/graph-extension/useGraphExtension.ts`) calls `onGraphChanged` only when the
  `stream:version` key moves between two polls (`seen.current !== null`). When a placement lands after the page's
  `GET /graph` but before its first `GET /graph/metrics` answers, the card says "New metric placed" while the graph
  stays at 27 metrics until the next placement. The test holds the first poll with `page.route` to make the window
  certain; in the fx look the first poll comes seconds late, so the window is real there.
- "the graph refits to every node after each placement posted to the API": after a placement the classic graph
  sometimes zooms onto the new node(s) alone (scale 1, every other node off-canvas) and stays there, despite the
  `fitView({ nodes: all })` in `web/src/components/GraphView.tsx` (React Flow's own `fitView` prop seems to win the
  race). Seen in about 3 of 5 runs of four API posts, about 1 in 12 single posts, rarely through the pack button. The
  miss is random, so the test calls `test.fail(true, ...)` only when it hits it (and saves `new-metric-refit-bug.png`
  with `ARGUS_E2E_SHOTS=1`); when every refit lands it passes. Remove that call once the fit is fixed. The other tests
  only record the off-canvas count as an annotation.

Screenshots: `ARGUS_E2E_SHOTS=1 npm --prefix e2e run test:all -- new-metric` (the fx one needs `test:all`).

## Known flake source: blank graph after a stream reset

After a restart (`POST /replay {"action":"restart"}` or the Restart button) with the page open, React Flow can keep
every metric node `visibility: hidden` for a few seconds (longer at 64x while the page folds the burst of events),
so the graph panel is empty while the legend, feed and trail render. The specs therefore only assert the graph
nodes are attached after a reset, not visible; the screenshot capture waits (bounded) for them to show.

## Proposed CI step

Not wired up yet (`.github/` is untouched). A separate job next to the existing one in `.github/workflows/ci.yml`:

```yaml
  e2e:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - uses: actions/setup-node@v4
        with: { node-version: 22 }
      - run: make setup
      - run: npm --prefix web ci && npm --prefix web run build
      - run: npm --prefix e2e ci && npx --prefix e2e playwright install --with-deps chromium
      - run: npx --prefix e2e tsc -p e2e
      - run: npm --prefix e2e test
        env: { CI: "1" }
      - run: make world SEED=7 && npm --prefix e2e run test:live
        env: { CI: "1" }
      - uses: actions/upload-artifact@v4
        if: failure()
        with: { name: playwright-report, path: "e2e/playwright-report\ne2e/test-results" }
```

With `CI` set, Playwright never reuses a running server and also writes the HTML report.
