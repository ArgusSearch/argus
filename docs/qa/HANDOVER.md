# QA handover (Ansor)

Updated: Saturday 2026-11-21, ~17:45 CET. Branch `team/ansor/qa` (base `origin/fm/argus-api` @ `437fff5`).

This file is enough to continue the QA work without the chat.

## State in one paragraph

On `fm/argus-api` everything is green: `make check`, `make s1` ALL PASS, and the web typecheck, tests and build. The S1 fault plays correctly in the browser, in replay and live on seeds 7, 3 and 11, and every receipt re-run gives the same hash. On the integration branch (section 3.4 of the team prompt) the quiet scenario is correct. S2 and S4 are wrong in the API/browser, and S3 is only partly right. The reason is that the Stage-2 investigator and the detect lane exist but are not wired into `src/argus/runtime/loop.py` (#1, #2). So demo moment 2 (a harmless change, "didn't wake you") cannot be shown yet: S2 is silent with no note (#3). The blind challenge mechanics work: commit, reveal and verify match. But seed 11 reveals S4, which Argus gets wrong today.

## What is in this branch

- `docs/qa/baseline.md`: every setup and check command, with results and timings.
- `docs/qa/matrix.md`: one row per run (S1 replay, S1 live seeds 7/3/11, quiet, S2, S3, S4, blind), observed vs expected, with issue links, plus the scorecard and the list of all QA issues.
- `docs/qa/screenshots/`: Mission Control at 1920x1080 and 1440x900, in five states.
- `e2e/`: the Playwright smoke suite, a separate npm package (see `e2e/README.md`).
  - 7 specs: health, load, s1-replay, receipt, controls, digest, offline.
  - Replay mode: green twice in a row, about 1:10 each.
  - Live mode: green (7 passed, 4 skipped as replay-only), about 43 s.
  - `offline.spec.ts` is marked `test.fail` until #6 is fixed. Remove the mark then.

## How to re-run

```bash
make setup && make check && make s1
npm --prefix web install && npm --prefix web run build
npm --prefix e2e install && npx --prefix e2e playwright install chromium
npm --prefix e2e test                       # replay, starts its own API on 8010 (8012 for offline)
make world SEED=7 && npm --prefix e2e run test:live   # live over runs/s1-7 on 8011
ARGUS_E2E_SHOTS=1 npm --prefix e2e test -- screenshots # refresh docs/qa/screenshots
```

To fill the live rows of the matrix:

1. Build the integration branch as in section 3.4 of the team prompt. This time it lives in a separate worktree, `git worktree add -b local/integration ../argus-integration origin/fm/argus-api`, followed by the merges.
2. Run `uv run mockmart generate --scenario <s> --seed 7 --out runs/<s>-7`.
3. Run `uv run argus api --port 8020 --world runs/<s>-7/world.duckdb --tick-seconds 0.2`. A run takes about 30 s.
4. Read `/incidents`, `/notes` and `/digest`, and `POST /receipts/{id}/rerun`.

On an 8 GB machine, run one API server and one browser at a time.

## Open issues found by QA

P0: #1, #2, #3 (all integration: Stage-2 investigate and detect are not in the runtime, so S2 is silent).
P1: #4 (S4 segment), #5 (S3 note), #6 (offline banner), #9 (identity never BROKEN in S3), #10 (report Impact frozen at 1 h), #13–#16 (web/UX: stale "checking", sparkline over labels, verdict labels, trail cut off).
P2: #7, #8 (bench output), #11 ("0 anomalys"), #12 (receipt demo coverage), #17–#20 (web polish).

## Next steps

1. Re-run the matrix after every merge into `fm/argus-api` that touches the runtime or the UI. The S2/S3/S4 rows should flip once #1 and #2 land.
2. Small UI/API fixes that QA can take, after Batu confirms nobody else is on them: #11 (one line in `src/argus/api/digest.py`) and #6 (`web/src/lib/api.ts` plus the header fallback). Each fix goes in its own PR `fix(api|web): ... (#n)` with a failing-then-passing test.
3. Propose the e2e CI job to Batu. The suggested step is in `e2e/README.md`; `.github/` is not ours.
4. Before the 11:00 freeze and the 12:00 rehearsal: run the e2e suite and the matrix again.
