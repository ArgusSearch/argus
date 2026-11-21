# QA handover (Ansor)

Updated: Saturday 2026-11-21, ~18:40 CET. Branch `team/ansor/qa`, rebased on `origin/main` @ `2c62f8b`. PR #21 targets `main`.

This file is enough to continue the QA work without the chat.

## State in one paragraph

`main` has every lane. On it:

- **S1** (live seeds 7, 3, 11 and replay), **quiet**, **S2** and the new **S5** (market control: 3 expected notes plus the real PayCo routing fault) play correctly. S2 now writes its "Didn't wake you" note, so demo moment 2 works. #1, #2 and #3 are verified fixed and closed.
- **S4** names the right cause (`pacing_ratio`, `dep_ad-pacer_1.7.0`, holdout run), but the segment is `{}` instead of DE/FR (#4). The S4 replay shows €1,687 instead of about €73.6k (#29).
- **S3** holds back correctly, but the note does not name the broken identity (#5, #9).
- **Scorecard on 260d499:** Argus pass@1 is 100% vs 17% for the threshold baseline.
- **Blind challenge** (seed 11 → s3): PASS, and the seal verifies.
- **CI on main is green** on 2c36e82: worlds are now identical on macOS and Linux (118a335), and the fixtures were re-recorded.
- **The fx layer** (`/?fx=1`, and the recording URL `/?demo=1&captions=1&fx=1`) is the look the video uses. It is covered by `npm --prefix e2e run test:fx`. Open fx bugs: #63–#69; the P1s are #64 (morning card vs ticker) and #68 (live step cut at 1080).
- The graph-blank-after-restart bug (#33) is fixed on main (f85616a).

- **Demo moment 3** (a new metric places itself) works with the recorded pack, in replay and live. Bugs: #73, #74 (P1); #75–#77. Use the pack on stage, not hand-written metrics on ad clicks (#77).

## What is in this branch

- `docs/qa/baseline.md`: every setup and check command, with results and timings.
- `docs/qa/matrix.md`: one row per run (S1 replay, S1 live seeds 7/3/11, quiet, S2, S3, S4, blind), observed vs expected, with issue links, plus the scorecard and the list of all QA issues.
- `docs/qa/screenshots/`: Mission Control at 1920x1080 and 1440x900, in five states.
- `e2e/`: the Playwright smoke suite, a separate npm package (see `e2e/README.md`).
  - `scenarios.spec.ts` checks the outcome card of every recorded scenario (S1, quiet, S2, S3, S4, S5).
  - 7 specs: health, load, s1-replay, receipt, controls, digest, offline.
  - Replay mode: green twice in a row, about 1:45 each.
  - Live mode: green (7 passed, the rest skipped as replay-only), about 46 s.
  - `offline.spec.ts` is marked `test.fail` until #6 is fixed. Remove the mark then.

## How to re-run

```bash
make setup && make check && make s1
npm --prefix web install && npm --prefix web run build
npm --prefix e2e install && npx --prefix e2e playwright install chromium
npm --prefix e2e test                       # replay, everything but fx, under 3 min (own API on 8010)
npm --prefix e2e run test:demo              # fx look, recording URL and demo moment 3 (new metric), about 2 min
make world SEED=7 && npm --prefix e2e run test:live   # live over runs/s1-7 on 8011
ARGUS_E2E_SHOTS=1 npm --prefix e2e test -- screenshots # refresh docs/qa/screenshots
```

To fill the live rows of the matrix:

1. No integration branch is needed any more: work on `main`.
2. Run `uv run mockmart generate --scenario <s> --seed 7 --out runs/<s>-7` (or `make world SCENARIO=<s>`).
3. Run `uv run argus api --port 8020 --world runs/<s>-7/world.duckdb --tick-seconds 0.2`. A run takes about 30 s.
4. Read `/incidents`, `/notes` and `/digest`, and `POST /receipts/{id}/rerun`.

On an 8 GB machine, run one API server and one browser at a time.

## Open issues found by QA

Closed as fixed on main: #1, #2, #3.

P1: #4 (S4 segment), #5 (S3 note), #6 (offline banner), #9 (identity never BROKEN in S3), #10 (report Impact frozen at 1 h), #13–#16 (web/UX), #29 (S4 replay money), 
P2: #7, #8 (bench output), #11 ("0 anomalys", fix in PR #28), #12 (receipt coverage), #17–#20 (web polish), #30, #31, #34–#38.

## Next steps

1. Re-run the matrix after every merge into `fm/argus-api` that touches the runtime or the UI. The S2/S3/S4 rows should flip once #1 and #2 land.
2. Small UI/API fixes that QA can take, after Batu confirms nobody else is on them:
   - #11 is done (PR #28).
   - #6 is done (PR #32). After it merges, remove `test.fail` from `e2e/tests/offline.spec.ts`.
   - #14 is done (PR #40). After it merges, remove `test.fail` from `e2e/tests/graph-nodes.spec.ts`.
   - #13 is done (PR #41). After it merges, remove `test.fail` from `e2e/tests/checking-label.spec.ts`.
   - #15 is done (PR #60). After it merges, remove `test.fail` from `e2e/tests/verdict-labels.spec.ts`.
   - #16 is done (PR #61). After it merges, remove `test.fail` from `e2e/tests/trail-cards.spec.ts`.
   - Each fix goes in its own PR `fix(api|web): ... (#n)` with a test that fails before and passes after.
3. Propose the e2e CI job to Batu. The suggested step is in `e2e/README.md`; `.github/` is not ours.
4. Before the 11:00 freeze and the 12:00 rehearsal: run the e2e suite and the matrix again.
