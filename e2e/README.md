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
| `graph-restart.spec.ts` | the metric graph never goes blank (`visibility: hidden`) in the 4 s after each of three replay restarts | expected failure until #33 is fixed (PR #39) | skipped (replay-only) |
| `graph-nodes.spec.ts` | on every metric node the unit text (COUNT/RATE/EUR) ends before the sparkline starts | expected failure until #14 is fixed (PR #40) | runs |
| `checking-label.spec.ts` | after the S1 verdict the graph bar no longer says "checking …" | expected failure until #13 is fixed (PR #41) | skipped (replay-only) |
| `verdict-labels.spec.ts` | the S1 verdict reads "SUPPORTED CAUSE" on the page and in the digest: no raw enum, no "root cause" | expected failure until #15 is fixed (PR #60) | skipped (replay-only) |
| `scenarios.spec.ts` | every recorded scenario on its own replay API (`--replay fixtures[/<s>]`) at 64x to `run.finished`: S1 one SUPPORTED CAUSE card in DE / android / PayCo; quiet no incident card; S2 no incident card and a "Didn't wake you" card about the budget (tab count > 0); S3 no incident card and a "Data issue · held back" card; S4 one SUPPORTED CAUSE card naming pacing and DE or FR | runs (about 40 s) | skipped (replay-only) |
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

Replay mode (default, about 2 min with the scenario spec): Playwright starts `uv run argus api --port 8010` from
the repo root, which streams `fixtures/` (S1) through the real SSE path. `scenarios.spec.ts` and `offline.spec.ts`
start and stop their own replay APIs next to it.

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
| `ARGUS_E2E_SHOTS=1` | capture the QA screenshots (`screenshots.spec.ts`, and `scenario-<s>.png` from `scenarios.spec.ts`) |
| `ARGUS_E2E_ROOT` | the repository checkout whose `argus api` (and `web/dist`) the suite runs; default `..`. Use it to test a fix branch from another worktree |
| `CI` | never reuse a running server; also write the HTML report |

Outside CI an API already listening on the port is reused, so stop stray servers first
(`pkill -f "argus api --port 801"`) or you test whatever that server is running.

QA screenshots (replay, 1920x1080 and 1440x900, into `docs/qa/screenshots/`; the scenario end states at
1920x1080 as `scenario-<s>.png`):

```sh
ARGUS_E2E_SHOTS=1 npm --prefix e2e test -- screenshots scenarios
```

Failure traces and screenshots land in `e2e/test-results/`; `npx --prefix e2e playwright show-trace <trace.zip>`.

## Ports

| Port | Used by |
| --- | --- |
| 8010 | main API, replay mode (Playwright `webServer`) |
| 8011 | main API, live mode |
| 8012 | `offline.spec.ts` starts and stops its own replay API here (`ARGUS_E2E_OFFLINE_PORT`) |
| 8013 | `scenarios.spec.ts` starts one replay API per scenario here, one at a time (`ARGUS_E2E_SCENARIO_PORT`) |

8013-8015 are reserved for e2e; 8020-8029 belong to other agents' API servers, leave them alone.
Both self-started servers go through `tests/own-api.ts`: bounded start (30 s), stop in `afterEach` (SIGINT to the
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
