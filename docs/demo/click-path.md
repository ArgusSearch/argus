# Click path: the 3-minute video and the live demo

> Historical rehearsal draft. See the [current showcase guide](../pitch/showcase.md) for the playback flow and metric placement.

Everything below runs on `main`. Times marked **measured** come from Playwright on the laptop (Windows 11, Chrome,
1920x1080) on 2026-11-21; times marked **computed** come from the replay pacing in `src/argus/api/replay.py`
(2 s per simulated hour, 0.9 s per investigation step, divided by the speed) over the recorded fixtures.
Nobody has run this with a stopwatch and a narrator yet: do that at rehearsal 1 and correct the numbers here.

## 0. Before you record (5 minutes)

```bash
git switch main && git pull && make setup && npm --prefix web install && npm --prefix web run build
make api                                  # terminal 1: S1 replay on http://127.0.0.1:8000
make api SCENARIO=s2 PORT=8001            # terminal 2: S2 replay (planned budget raise) on :8001
make world SEED=7                         # once: runs/s1-7 for the terminal beat and the live fallback
```

- Chrome, window exactly 1920x1080 (DevTools device toolbar "Responsive" 1920x1080, or a 1920x1080 display),
  zoom 100%, bookmarks bar hidden, one profile with no extensions in the toolbar, dark OS theme.
- Tab 1: http://127.0.0.1:8000/ · Tab 2: http://127.0.0.1:8001/ · Tab 3: http://127.0.0.1:8000/?challenge=reveal
- Terminal window (beat 3): font 20 pt or larger, dark theme, 1920x1080, cleared.
- Close every toast and drawer before each take. Restart a replay with the ↻ button in the header.

## 1. The video, beat by beat (target 3:00)

| Clip | Length | Screen and clicks | Narrator (one line) |
| --- | --- | --- | --- |
| Cold open | 0:00-0:12 | Tab 1, replay finished (press 8×, wait about 30 s, **measured** resolved at 28 s at 8×), click the `INC-0001` card: the incident page with the lifecycle, "Where it is", the LMDI bars and "Ruled out". Slow scroll down. | "At 18:00 on a Friday, PayCo payments on Android in Germany started failing. Nobody asked. Argus found it, explained it and closed it." |
| Beat 1, the fault (S1) | 0:12-1:00 | Tab 1: Esc, ↻ restart, press 4×. Graph and ticker count up; at **46.7 s (measured, 4×)** the anomaly opens and the trail walks the playbook; at **50.2 s** the incident card and the toast "INC-0001 explained" land; **54.3 s** resolved. In the edit, cut the quiet part from 0:05 to 0:42 of the raw clip. Click "Open report". Click the first number (for example the observed rate): the receipt drawer with the SQL and `as_of`. | "Every hour Argus scores the metric graph. When payment success breaks, it walks the graph, splits the change exactly, tests the release that shipped the same hour against a holdout and rules it out. Every number is a SQL receipt." |
| Re-run the receipt | 1:00-1:12 | Only live: see "Live re-run" below. In replay the button answers "Receipt re-runs need live mode" (on purpose), so record this clip from the live take. | "Click any number, re-run the query, get the same hash." |
| Beat 2, harmless change (S2) | 1:12-1:40 | Tab 2: ↻ restart, press 4×. **Computed** at 4×: anomaly at 28 s, note "Didn't wake you" (kind `expected`) at 30 s. Click the "Didn't wake you" tab, then the note: "delivery follows its plan (planned_spend +41.0%, pacing_ratio flat); planned by bud_adv_01_FR_increase" with its receipts. Cut 0:03-0:25 of the raw clip. | "A big advertiser raised its budget, planned and logged. Argus saw the spend jump, found the plan, and did not wake anyone. It says so, with the reason." |
| Beat 3, a new metric places itself | 1:40-2:05 | Terminal: `uv run python -m argus.graph.classify metrics/roas_by_advertiser.yml --world runs/s1-7/world.duckdb --cards` (**measured** 1.7 s). Hold on the `PROPOSED -> VALID` lines. | "Drop a metric YAML in. Argus works out where it belongs in the graph and proves every new edge on the data before it trusts it." |
| Bench and blind challenge | 2:05-2:40 | Scorecard view (Youssef, PR #25) for 8 s, then Tab 3 `/?challenge=reveal`: "The hash matches", the truth next to what Argus said, PASS. Click "Change one character of the payload": red "The hash does not match". | "Across every scenario and seed Argus is scored against a sealed truth. A judge picks the seed; the answer key is hashed before the run, and anyone can check it on their phone." |
| Closing | 2:40-3:00 | Tab 1, graph at rest, "While you slept" opened. | "Argus. The analyst that never sleeps, and knows when not to wake you." |

MISSING: in-browser beat 3. `POST /metrics` answers 501, so the new node does not appear in the graph:
`docs/demo/issues/demo-new-metric-in-ui.md` (file it, link the issue number here).
MISSING: the live blind challenge. The screens play the recorded seed-11 run until the bench routes exist:
`docs/demo/issues/api-blind-challenge-routes.md`.
MISSING until PR #25 (Youssef) is merged: demo mode `http://127.0.0.1:8000/?demo=1` and the Scorecard view.
With demo mode, beat 1 records hands-off; without it, use the clicks above.
MISSING until the hook branches are merged: `/?challenge` needs `team/alan/hook-challenge`, the 1920 projector
layout needs `team/alan/hook-responsive`.

### Live re-run (for the receipt clip and the live demo)

```bash
uv run argus api --world runs/s1-7/world.duckdb --port 8002 --tick-seconds 0.5
```

**Measured**: the incident appears 64 s after start (hour 70 of 120) and is resolved by 151 s. Open
http://127.0.0.1:8002/, click the incident, click a number, click "Re-run SQL": "✓ Same hash" (checked with
`POST /receipts/r169/rerun`: `matches: true`, 72 ms). At the default 2 s per hour the incident comes after
about 2:20; use `--tick-seconds 0.5` or the 4× button.

## 2. The live demo in front of the judges (about 4 minutes)

1. Blind challenge opener (if the go/no-go on Sunday 10:30 says yes). Tab `/?challenge`: a judge types a number,
   "Seal the scenario" (the hash appears large with a QR code; ask a judge to scan it now), "Start the run"
   (Mission Control with the "Hidden scenario, committed" banner bottom right), then "Reveal".
   Honest caveat on screen: the chip "recorded run · seed 11" and, if the judge picked another number, the note
   "Live sealing is not built yet". Phone link: run the API with `--host 0.0.0.0`, then type the laptop's LAN
   address (`ipconfig` -> IPv4) into the box under the QR code; the QR updates.
2. S1 in replay at 4× (as beat 1), open the report, click a number.
3. S2 at 4× on :8001, the "Didn't wake you" note.
4. Terminal: the new metric.
5. "While you slept".

## 3. If something fails live

| Failure | Fallback |
| --- | --- |
| Live API slow or crashes | `make api` (replay of the same S1 story; the page header says `Replay · recorded run`) |
| Page shows "Lost the connection to the API" | Restart the API in its terminal; the page recovers on its own (checked: about 8 s, no duplicated cards) |
| Phone cannot open the QR link | Show the reveal's own check ("The hash matches", computed in the laptop's browser) and the terminal `uv run argus-bench verify runs/bench/blind-11` |
| Venue Wi-Fi blocks phone to laptop | Laptop hotspot, or skip the phone and use "Change one character of the payload" on the big screen |
| Anything else | Play the recorded backup video (record it at C2, Saturday 22:30, from this file) |
