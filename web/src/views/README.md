# Views (Youssef's lane): handover note

New screens around Mission Control's main area, plus the demo mode the video is recorded in.
Everything lives in `web/src/views/` (code) and `web/test/views/` (tests). The only change outside the folder is
the hook PR `hook: mount views in App.tsx` (one import, and `<ViewHost …>` around the existing `<div className="main">`).

## How to see it

```bash
uv run argus api --port 8000          # make api: replays fixtures/ (the recorded S1 run)
npm --prefix web run build            # the API serves web/dist at /
```

Open http://127.0.0.1:8000. The tab bar under the ticker switches views; the keys `1`–`5` do the same.
Deep links: `/?view=tree`, `/?view=investigation`, `/?view=report`, `/?view=scorecard`.

| View | Tab / key | Reads | What a judge sees |
| --- | --- | --- | --- |
| Graph | Graph · 1 | the existing page (`children`) | unchanged, kept mounted so it never loses its place |
| Y1 Tree | Tree · 2 | `graph` prop, `RunView` | the metric graph as a collapsible tree: GMV and CPA at the top, formula / ratio / cause children, one row per breakdown, logs as leaves; live state and edge status per row; the running investigation opens the tree down to the metric it checks |
| Y2 Investigation | Investigation · 3 | `RunView` (steps, anomalies, incidents, skeptic) | the walk as a story in six chapters (trust the data, rule out the calendar, localise, test the suspects, quantify, decide); every step shows the question it answers, the prediction written before the query, the result, the decision and its receipts; next to it the case file: what tripped, the root-cause path `payment_success_rate › android › DE › PayCo`, suspects with the ruled-out ones struck through, the verdict with a link to the report |
| Y4 Morning report | Morning report · 4 | `GET /digest`, `GET /incidents`, `GET /notes`, `GET /incidents/{id}/report` | a printable "While you slept": digest lines with receipts, each incident as a card (verdict, segment, € impact, explained and unexplained share, ruled out, suggested action) with the full report rendered from Markdown (receipts clickable), and every "didn't wake you" note with its distance to the alarm line; **Print** prints only this page |
| Y5 Scorecard | Scorecard · 5 | `GET /bench/results`, else `fixtures/scorecard.sample.json` | Argus against the threshold baseline per scenario on sealed seeds; misses in red and listed, never hidden; the bench commitment hash. Until the route exists the sample is shown with a "Recorded <date> · commit <sha>" label |
| Y6 Autonomy strip | right side of the tab bar | `RunView` counts | hours watched · edge tests · investigated · **0 human actions** (anomalies, incidents and held-back alerts are already in the ticker) |

## Y3 Demo mode (the video)

`http://127.0.0.1:8000/?demo=1&captions=1` and touch nothing.

| Option | Default | Meaning |
| --- | --- | --- |
| `demo=1` | off | hands-off mode; **Esc** leaves it and removes the options from the address bar |
| `speed=1\|2\|4\|8` | 2 | replay speed (live mode: tick speed) |
| `captions=1` | off | one caption line per beat (ids below) |
| `hold=<s>` | 12 | seconds the incident report stays open (3–120) |
| `end=report` | off | open the morning report when the run is complete |

What it does: hides the replay controls and the toast and raises font sizes; on a replay it reads the current
stream id from `/health`, restarts from the first tick at `speed` and follows only the new stream (a paused or
finished replay restarts too; a live run keeps going); switches to **Investigation** when the first
step arrives; 3.5 s after an incident gets a verdict it opens the report, and after `hold` seconds closes it and goes
back to **Graph** to watch the recovery. The replay loops, so the choreography repeats on every loop.

Caption beat ids (for `docs/demo/click-path.md`): `watching`, `held` (a planned change or late data did not page),
`anomaly`, `checks`, `localised`, `suspects`, `verdict`, `monitoring`, `resolved`. Captions name things; they never
state a measurement.

## Rules these views keep

- No view opens its own `EventSource`; everything comes from the folded `RunView` or a REST read.
- No displayed number is computed here: numbers are the API's (with `Num`/`ReceiptChips` where a receipt exists).
  The views only pick, order, format and label.
- The heavy views are lazy chunks (`React.lazy`), so the main bundle only grows by the switcher and demo mode.
- Styles in `views.css` use only the variables of `styles.css`; nothing in `styles.css` changed.

## Tests

`npm --prefix web test` runs `web/test/views/*.test.ts` against the recorded run in `fixtures/`:
tree (every metric expanded exactly once, cycles, refs), investigation story and suspects, demo beats and URL
options, autonomy counts, metric state, the Markdown reader against `fixtures/report.md`, scorecard shaping.

## Open / known

- `GET /bench/results` is a 501 stub (bench lane); the scorecard falls back to the recorded sample and says so.
  Its shape is `Scorecard` in `src/bench/scorecard.py` on `fm/argus-bench`.
  The sample was recorded before `main` landed, on a local integration of the lane branches
  (`uv run argus-bench run --runs 3`): Argus passes quiet, S1 and S3 3/3 and misses S2 and S4 3/3. Re-record it on
  `main` with `make bench` + `--json web/src/views/fixtures/scorecard.sample.json`, or wait for the route.
- On `main` every scenario streams through the API (`make api SCENARIO=s2|s3|s4` replays `fixtures/<scenario>`):
  S1 walks to a supported cause with the release struck through; S2 ends EXPECTED with no incident (caption
  "did not wake anyone", demo mode returns to the graph); S3 is a data-issue note (morning report, caption);
  S4 has no single segment, so the case file names where the kept cause applied (`country DE, FR`).
- Checked in a real Chrome window at 1536×735 and at 1920×1080 through Playwright. In a backgrounded
  automation browser Chrome throttles frames, and React Flow then keeps graph nodes hidden; that is the browser,
  not the page (a foreground window renders them).
