# Scenario matrix

## Current: `main` @ `260d499` (Saturday 2026-11-21, ~20:30 CET)

New on main since `f35b00a`:
- S5 (market control) with its recording;
- counterfactual replay, the morning report and `/autonomy`;
- demo playback `/demo/*`;
- the ruff-format fix (#27).

`make check` is green: 335 passed, 1 xfailed. `make s1` gives ALL PASS.

| Run | Expected | Observed | Verdict ok | Time to incident or note | Receipt re-runs | Bugs |
| --- | --- | --- | --- | --- | --- | --- |
| S1 live, seeds 7 / 3 / 11 | one incident `SUPPORTED_CAUSE` on `payment_success_rate` DE / android / PayCo; android-app 8.3.0 ruled out; resolved after 3 normal hours | as expected on all three seeds: €86,459 / €163,454 / €71,646, resolved 08:00 / 20:00 / 06:00 | yes | 17 / 24 / 18 s | 21/21 same hash | #10, #35 |
| S1 replay (browser and API) | same | INC-0001 SUPPORTED CAUSE DE / android / PayCo, two releases ruled out, resolved, €99,647 | yes | 20 s | 409 by design | #13–#16 UI (fix PRs open) |
| quiet, live and replay | zero incidents | 0 incidents, 0 notes | yes | — | 2/2 | #11 (fix PR #28) |
| S2, live and replay | `EXPECTED` note, no incident | `expected` note (`cal_adv_03_FR_push` live, `bud_adv_01_FR_increase` replay), no incident | yes | 22 s live / 12 s replay | 3/3 | #31 |
| S3, live and replay | `DATA_ISSUE`, identity broken, re-check after the backfill | freshness `data_issue` note only; no BROKEN edge, no re-check | partial | 26 s | 2/2 | #5, #9 |
| S4, live and replay | `SUPPORTED_CAUSE` on the pacing ratio, DE or FR, `dep_ad-pacer_1.7.0`, UK/ES/NL holdout | `pacing_ratio`, `dep_ad-pacer_1.7.0`, holdout outside DE/FR validated, **segment `{}`**. The replay stays at €1,687 | mostly | 14 s | 7/7 | #4, #29 |
| S5 live (new) | market-wide dip: three `EXPECTED` notes from the market control; the checkout-routing fault on DE / android / PayCo is `SUPPORTED_CAUSE` and resolves | 3 `expected` notes (sessions, orders, gmv), and `SUPPORTED_CAUSE` on `payment_success_rate` {DE, android, PayCo} citing `dep_checkout-routing_retry-policy`. Opened 21:00 (2 h after onset), resolved 05:00. Action: "Roll back dep_checkout-routing_retry-policy" | yes | notes 18 s, incident 19 s | 10/10 | #10 |
| S5 replay (browser and API) | same | 3 notes and SUPPORTED CAUSE, decoy recommendations 1.1.5 refuted, resolved | yes | 18 / 21 s | 409 by design | — |
| Blind `argus-bench blind --seed 11` | the sealed scenario is solved | drew s3: DATA_ISSUE note, grade 4, PASS. `verify`: the hash matches | yes | — | — | #8 (baseline dropped; S5 not in the blind list) |

New routes, checked once per run (13 runs), with no 5xx anywhere:
- `GET /incidents/{id}/counterfactual`: 200 on S1 and S4 in 3.5–4.3 s, explained share 0.945–0.984. S5 gives the documented 409.
- `GET /report/morning` and `GET /autonomy`: 200 everywhere.
- `/demo/*`: the 9-beat stream with resume, and the documented 409/204/422/404.
- `GET /routes` does not list the 14 new routes (#62).

### Scorecard on main @ 260d499 (`uv run argus-bench`, 3 seeds per scenario)

```
agent      recall  cause  exact     TTD h  prec  FA/day quietFA expect   data grade pass@1 truth
argus        100%   100%    67%       2/2  100%       0       0   100%   100%  3.83   100%    ok
threshold    100%     0%     0%       2/2   44%   0.167       0     0%     0%  0.83    17%    ok
argus      s1 3x exact | s2 3x explained | s3 3x data issue | s4 3x right cause (grade 3) | s5 3x explained | quiet 3x pass
threshold  s5  0%  3x paged on a planned change (FA 9)
```

### Smoke suite on main @ 260d499

- `npm --prefix e2e test` gives 21 passed, 2 skipped (screenshots), twice in a row, in 2:50 and 2:53.
- `scenarios.spec.ts` now covers S5.
- Seven specs are marked `test.fail` for open bugs that have fix PRs: #6 (#32), #13 (#41), #14 (#40), #15 (#60), #16 (#61); #33 was fixed on main in f85616a and its spec now runs as a normal check. Each turns red once its fix lands, as a reminder to remove the mark.

---

## Earlier: `main` @ `f35b00a` (Saturday 2026-11-21, ~18:30 CET)

On `main` every lane has landed: the runtime uses the Stage-2 investigator and the detect lane's plan watch, and every scenario has a recording in `fixtures/<scenario>`.

How the columns were observed:

- **Live:** `uv run argus api --port <p> --world runs/<s>-<n>/world.duckdb --tick-seconds 0.2`, read through the routes the page renders.
- **Replay:** `uv run argus api --replay fixtures/<s>` (the same as `make api SCENARIO=<s>`), played at 64x.
- **Browser:** `e2e/tests/scenarios.spec.ts` checks the outcome card for every recorded scenario.
- **Terminal:** `uv run argus-bench`.

| Run | Expected | Observed | Verdict ok | Time to incident or note | Receipt re-runs | Bugs |
| --- | --- | --- | --- | --- | --- | --- |
| S1 live, seed 7 | one incident `SUPPORTED_CAUSE` on `payment_success_rate` DE / android / PayCo; android-app 8.3.0 ruled out; resolved after 3 normal hours | INC-0001 `SUPPORTED_CAUSE` {DE, android, PayCo}, evidence `ps_payco_degraded`. 8.3.0 ruled out (+0.3% outside vs -34.6% inside). Resolved 11-21 08:00. €86,459 | yes | 22 s wall (sim 11-20 23:00, opened 21:00) | 7/7 same hash | [#10](https://github.com/ArgusSearch/argus/issues/10) |
| S1 live, seed 3 | same | same, €163,454, resolved 11-21 20:00 | yes | 20 s | 7/7 | #10 |
| S1 live, seed 11 | same | same, €71,646, resolved 11-21 06:00 | yes | 17 s | 7/7 | #10 |
| S1 replay (browser) | same | INC-0001 card `SUPPORTED CAUSE`, DE / android / PayCo, 8.3.0 under "Ruled out", Copy report works | yes | — | 409 by design | [#13](https://github.com/ArgusSearch/argus/issues/13)–[#20](https://github.com/ArgusSearch/argus/issues/20) (UI polish) |
| quiet, live and replay | zero incidents | 0 incidents, 0 notes | yes | — | 2/2 (edge receipts only) | [#11](https://github.com/ArgusSearch/argus/issues/11) "0 anomalys" (fix: PR #28), [#12](https://github.com/ArgusSearch/argus/issues/12) |
| S2, live and replay | `EXPECTED`, no incident, a "didn't wake you" note citing the planned budget change | 0 incidents. An `expected` note on ad_spend {adv_03, FR} citing `cal_adv_03_FR_push` (+44.2% delivered vs +33% planned); the replay cites `bud_adv_01_FR_increase`. The browser shows "Didn't wake you" 1 | **yes** (was no) | note after 22 s live / 12 s replay | 3/3 | [#31](https://github.com/ArgusSearch/argus/issues/31) (digest "0 queries", duplicated receipts) |
| S3, live and replay | `DATA_ISSUE`, no business incident, identity `orders = payment_successes` broken, re-check after the backfill, hotfix decoy ruled out | 0 incidents. One `data_issue` note ("fact_orders_hourly … only 55% delivered"), with no node and no receipts. 0 BROKEN edges, nothing after the backfill. The browser shows "Data issue · held back" | partial (silent for the right reason, but the reason is not shown) | note after 18 s | 2/2 (edge receipts only) | [#5](https://github.com/ArgusSearch/argus/issues/5), [#9](https://github.com/ArgusSearch/argus/issues/9) |
| S4 live | `SUPPORTED_CAUSE` on the pacing ratio in DE or FR citing `dep_ad-pacer_1.7.0`, UK/ES/NL as holdout | root **`pacing_ratio`**, evidence `dep_ad-pacer_1.7.0`, holdout -2.2% outside DE/FR vs +191.1% inside, but **segment `{}`**. €73,675. Stays explained (correct: the fault never ends) | mostly | 14 s | 7/7 | [#4](https://github.com/ArgusSearch/argus/issues/4), #10 |
| S4 replay | same | same verdict, but €1,687 for the whole replay (the recording ends at €73,602) | mostly | 11 s | 409 by design | [#29](https://github.com/ArgusSearch/argus/issues/29), #4 |
| Blind `argus-bench blind --seed 11` | the sealed scenario is solved | drew s3: DATA_ISSUE note, grade 4, PASS. `verify`: hash matches. Forced `--scenario s4`: pacing_ratio grade 3, PASS | yes | — | — | [#8](https://github.com/ArgusSearch/argus/issues/8) (baseline agent dropped) |

No server log showed a Traceback or ERROR. Raw captures are kept outside the repo, under `qa-logs/main-*`.

### Scorecard on main (`uv run argus-bench`, 3 seeds per scenario)

```
agent      recall  cause  exact     TTD h  prec  FA/day quietFA expect   data grade pass@1 truth
argus        100%   100%    50%       2/2  100%       0       0   100%   100%  3.75   100%    ok
threshold    100%     0%     0%       2/2   60%    0.08       0     0%     0%     1    20%    ok
argus      quiet 3x pass | s1 3x exact | s2 3x explained | s3 3x data issue | s4 3x right cause (grade 3)
threshold  quiet pass | s1 paged, no cause | s2 silent | s3 paged a business incident (FA 6) | s4 paged, no cause
```

### Checks on main

- `make check` is **red**, but only at `ruff format --check`, which flags the Python block in `docs/plan/build-plan.md` (#27, filed by someone else). CI on main fails for the same reason.
- Every other step passes: `ruff check`, mypy (96 files), contracts, `make web` (19 vitest tests, build) and pytest (`273 passed`).
- `make s1`: ALL PASS.

### Smoke suite on main

- Replay: `npm --prefix e2e test` gives 14 passed, 2 skipped (screenshots), twice in a row, in 105.6 s and 103.2 s.
- Live: `npm --prefix e2e run test:live` gives 7 passed, the rest skipped as replay-only, in 46 s.
- `offline.spec` stays `test.fail` until #6 is fixed.

---

## Earlier: `fm/argus-api` @ `437fff5` + local integration branch (Saturday 16:20–17:30)

Kept for history. #1, #2 and #3 below were verified fixed on main and closed.

Commits:

- `fm/argus-api` @ `437fff5`: the S1 replay and S1 live rows.
- `local/integration` @ `59ee8a7`: the quiet, S2, S3 and S4 rows. It is `fm/argus-api` `437fff5` merged with `fm/argus-investigate` `c1d9055`, `fm/argus-detect` `79025ea` and `fm/argus-graph` `d56d92e`, plus `tests/bench/test_bench_scenarios.py` from `fm/argus-bench` `74e2131`. Built exactly as in section 3.4 of the team prompt, merged without conflicts, and `make check` gives `249 passed, 2 skipped`.

How each column was observed:

- **Observed in UI.** The S1 replay was checked in Chromium by the Playwright suite (`e2e/`). The live rows were read from the API routes the page renders (`/incidents`, `/incidents/{id}`, `/notes`, `/digest`, `/events`, `POST /receipts/{id}/rerun`), running `uv run argus api --port <p> --world runs/<s>-<n>/world.duckdb --tick-seconds 0.2`.
  - Each live run is 120 ticks and finishes in 29–32 s of wall time.
  - Raw captures are kept outside the repo, under `qa-logs/live-*`.
- **Observed in terminal.** `uv run python -m argus.investigate --world runs/<s>-7/world.duckdb --out runs/<s>-7/argus` (Stage-2) and `uv run argus-bench case <s> --seed 7` (default agent `argus` = the Stage-1 runtime the API uses).

| Run | Expected | Observed in UI | Observed in terminal | Verdict ok | Bugs |
| --- | --- | --- | --- | --- | --- |
| S1 replay (`make api`) | one incident, `SUPPORTED_CAUSE` on `payment_success_rate` DE / android / PayCo, release ruled out, report | INC-0001 `SUPPORTED CAUSE`, segment DE / android / PayCo, android-app 8.3.0 under "Ruled out", Copy report gives the Markdown. Receipts open with SQL and `as_of`; re-run answers 409 in replay by design. | `make s1` ALL PASS (seed 7) | yes | — |
| S1 live seed 7 (`make demo`) | same | INC-0001 `SUPPORTED_CAUSE`, segment {DE, android, PayCo}, evidence `ps_payco_degraded`, 8.3.0 refuted ("holdout normal"). Resolved 11-21 08:00 after 3 normal hours. €86,459. First visible after 17 s wall (sim 11-20 23:00, opened 21:00). Re-runs 5/5 same hash. | bench scorecard s1: 3x exact | yes | [#10](https://github.com/ArgusSearch/argus/issues/10) (report Impact shows 1 h only) |
| S1 live seed 3 | same | same pattern, €163,454, resolved 11-21 20:00, first visible after 20 s. Re-runs 5/5 same hash. | — | yes | #10 |
| S1 live seed 11 | same | same pattern, €71,646, resolved 11-21 06:00, first visible after 17 s. Re-runs 5/5 same hash. | — | yes | #10 |
| quiet live seed 7 | zero incidents | 0 incidents, 0 notes. Digest has 6 lines and says "0 anomalys". | investigate: 0 incidents. Scorecard: 3x pass. | yes | [#11](https://github.com/ArgusSearch/argus/issues/11), [#12](https://github.com/ArgusSearch/argus/issues/12) |
| S2 live seed 7 | `EXPECTED`, no incident, "didn't wake you" note citing `log_ad_budgets` | 0 incidents and **0 notes**. ad_spend peaks at \|z\| 2.94, under the alarm line of 5. The digest says 0 planned or harmless changes. Demo moment 2 does not appear. | Stage-2: 0 incidents, 0 notes. Bench `argus` and `argus-stage2`: grade 2 "silent", FAIL. `python -m argus.detect` alone does open `ad_spend[adv_03, FR] z=+5.4`, but it is not wired in. | **no** | [#3](https://github.com/ArgusSearch/argus/issues/3), [#2](https://github.com/ArgusSearch/argus/issues/2), [#1](https://github.com/ArgusSearch/argus/issues/1) |
| S3 live seed 7 | `DATA_ISSUE`, no business incident, identity `orders = payment_successes` broken for the stalled hours, re-check after the backfill | 0 incidents. One `data_issue` note: "fact_orders_hourly 23:00 is only 55% delivered" (node null, no receipts). orders, gmv and cvr not scored for 4 ticks. `f_orders_payments` stays VALID, with no re-check event. | Stage-2: the same single freshness note. Bench: grade 4 PASS. The grader does not check the identity or ruled-out. | **partial** (correctly silent, but the reason is not shown) | [#5](https://github.com/ArgusSearch/argus/issues/5), [#9](https://github.com/ArgusSearch/argus/issues/9) |
| S4 live seed 7 | `SUPPORTED_CAUSE` on the pacing ratio in DE or FR citing `dep_ad-pacer_1.7.0`, UK/ES/NL as holdout | INC `SUPPORTED_CAUSE` citing `dep_ad-pacer_1.7.0`, but root **`impressions_per_session`**, segment `{}` (all), nothing ruled out, €0, stays `explained`. Holdout says "nothing to hold out". Re-runs 5/5 same hash. | Stage-1 bench: `impressions_per_session [all]` grade 2, FAIL. Stage-2: `pacing_ratio`, segment `{}` grade 3. | **no** | [#1](https://github.com/ArgusSearch/argus/issues/1), [#4](https://github.com/ArgusSearch/argus/issues/4) |
| Blind challenge `argus-bench blind --seed 11` | the sealed scenario is solved | Terminal only: revealed s4, `impressions_per_session [all]` grade 2, FAIL. The seal checks out (`verify`: match). | — | **no** | #1, [#8](https://github.com/ArgusSearch/argus/issues/8) |

### Scorecard (integration branch, `uv run argus-bench`, 3 seeds per scenario)

```
agent      recall  cause  exact     TTD h  prec  FA/day quietFA expect   data grade pass@1 truth
argus        100%    50%    50%       2/2  100%       0       0     0%   100%     3    60%    ok
threshold    100%     0%     0%       2/2   60%    0.08       0     0%     0%     1    20%    ok
```

Argus beats the threshold baseline on every row. The gaps (S2 0% expected, S4 partial) all come from the Stage-2 investigator and the detect lane not being wired into the runtime (#1, #2).

### Smoke suite

See [e2e/README.md](../../e2e/README.md): 7 specs, replay and live mode.

## All QA issues (status on main @ f35b00a)

| # | Area | Sev | Summary |
| --- | --- | --- | --- |
| [1](https://github.com/ArgusSearch/argus/issues/1) | brain | ~~P0~~ fixed | Stage-2 investigator not wired into the runtime (API, bench default agent, blind) |
| [2](https://github.com/ArgusSearch/argus/issues/2) | brain | ~~P0~~ fixed | Detect lane not wired into the runtime |
| [3](https://github.com/ArgusSearch/argus/issues/3) | brain | ~~P0~~ fixed | S2 silent: no EXPECTED / "didn't wake you" note |
| [4](https://github.com/ArgusSearch/argus/issues/4) | brain | P1 | S4 Stage-2 segment `{}` although its own holdout localises DE, FR |
| [5](https://github.com/ArgusSearch/argus/issues/5) | brain | P1 | S3 note is freshness-only: no broken identity, decoy not ruled out |
| [6](https://github.com/ArgusSearch/argus/issues/6) | web | P1 | Offline banner never appears when the API stops (fix: PR #32) |
| [7](https://github.com/ArgusSearch/argus/issues/7) | bench | P2 | Progress output starts at [17/46] |
| [8](https://github.com/ArgusSearch/argus/issues/8) | bench | P2 | `blind` runs only the first default agent |
| [9](https://github.com/ArgusSearch/argus/issues/9) | graph | P1 | `f_orders_payments` never BROKEN during the S3 stall (28-day daily test) |
| [10](https://github.com/ArgusSearch/argus/issues/10) | api | P1 | Report Impact frozen at 1 h vs severity total |
| [11](https://github.com/ArgusSearch/argus/issues/11) | api | P2 | Digest says "0 anomalys" (fix in PR #28) |
| [12](https://github.com/ArgusSearch/argus/issues/12) | api | P2 | Receipts on quiet runs are world-independent; a zero-row receipt among samples |
| [13](https://github.com/ArgusSearch/argus/issues/13) | web | P1 | Graph bar still says "checking …" after the verdict (fix: PR #41) |
| [14](https://github.com/ArgusSearch/argus/issues/14) | web | P1 | Sparkline drawn over the COUNT/RATE/EUR unit label (fix: PR #40) |
| [15](https://github.com/ArgusSearch/argus/issues/15) | web | P1 | One verdict, four labels (SUPPORTED_CAUSE / SUPPORTED CAUSE / ROOT CAUSE) (fix: PR #60) |
| [16](https://github.com/ArgusSearch/argus/issues/16) | web | P1 | Investigation trail is a sideways scroller; leftmost card cut through its text (fix: PR #61) |
| [17](https://github.com/ArgusSearch/argus/issues/17) | web | P2 | "INC-0001 explained" toast covers trail cards 12–13 |
| [18](https://github.com/ArgusSearch/argus/issues/18) | web | P2 | "log_provider_status" overflows its pill |
| [19](https://github.com/ArgusSearch/argus/issues/19) | web | P2 | Metric node text about 7–9 px at 1440x900 |
| [20](https://github.com/ArgusSearch/argus/issues/20) | web | P2 | Incident money frozen at "€19,717 so far" for hours; receipt as_of vs opened time unexplained |
| [29](https://github.com/ArgusSearch/argus/issues/29) | api | P1 | S4 replay shows €1,687 for the whole run (the recording ends at €73,602) |
| [30](https://github.com/ArgusSearch/argus/issues/30) | api | P2 | Every replay re-run's 409 says "make demo runs … the S1 world", even for other scenarios |
| [31](https://github.com/ArgusSearch/argus/issues/31) | api | P2 | S2 digest "0 queries"; duplicated receipts in the S2 note |
| [33](https://github.com/ArgusSearch/argus/issues/33) | web | ~~P1~~ fixed | Metric graph blanks for seconds after a replay restart or loop (fixed on main via df4b26d) |
| [34](https://github.com/ArgusSearch/argus/issues/34) | web | P2 | "Run complete" toast while the S4 incident is still open |
| [35](https://github.com/ArgusSearch/argus/issues/35) | brain | P2 | S1 title repeats the provider ("PayCo: PayCo: …") |
| [36](https://github.com/ArgusSearch/argus/issues/36) | web | P2 | Lifecycle and digest use the data hour, feed cards the clock hour |
| [37](https://github.com/ArgusSearch/argus/issues/37) | web | P2 | S2 Verdict trail card text cut off |
| [38](https://github.com/ArgusSearch/argus/issues/38) | web | P2 | "no anomaly yet" stays after the run is complete |
| [62](https://github.com/ArgusSearch/argus/issues/62) | api | P2 | `GET /routes` omits the 14 new routes |
