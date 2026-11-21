# Argus agent scene

**90-second screen capture of Mission Control.** Use the sealed S4 replay when it passes the cold rehearse gate. The export labels the screen “Recorded model run” throughout. For a qualified live take, use “Live model.”

| Film time | Real app shot | Proof to leave on screen |
| --- | --- | --- |
| 0:00–0:12 | Overview. Let the monitor open the ad spend incident. | Simulated clock, ad spend, new investigation. |
| 0:12–0:24 | Open the S4 investigation and Agent activity. | Model-selected check, prediction before the query, returned evidence and next check. |
| 0:24–0:34 | Open a receipt from the finding or the agent check. | Readable query purpose, simulated time, result hash and capture-verification label. |
| 0:34–0:50 | Open Ask Argus in the case. Ask “Could higher traffic explain the spend?” | Actual answer and its decomposition receipt. Hold the cited evidence long enough to read it. |
| 0:50–1:10 | Show the DE/FR rollback and success rule. Hold on the pending state, then click Approve once. | Operator decision, effective time and applied action. |
| 1:10–1:24 | Open the action’s measured effect and its evidence. | Treated pacing beside the untouched twin, verification status, both receipts. |
| 1:24–1:30 | Open the updated morning report. | Report cutoff after the effect check. Include the bench and build SHA on the pitch worker’s closing card only after their release gates pass. |

Record the actual app. Keep the approval click in the footage. Retain the raw clips and cut offsets so the pitch editor can distinguish simulation waits from actions that viewers should see.

## Cold offline rehearsal

Build Mission Control and start a dedicated local replay server. Use the acceptance digest supplied with the sealed tape. Rehearse without provider credentials.

```sh
npm --prefix web run build
env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY ARGUS_AGENT=off \
  ARGUS_DEMO_BUNDLE_SHA="$SEALED_S4_DIGEST" \
  uv run --no-sync argus api --replay fixtures/s4 --port 8014
```

Run from a second terminal. Pin a custom capture directory with `ARGUS_DEMO_BUNDLE=/absolute/path/to/s4` if the bundle is staged outside the repository.

```sh
ARGUS_DEMO_BUNDLE_SHA="$SEALED_S4_DIGEST" uv run --no-sync argus demo --scenario s4 --variant agent
uv run --no-sync python scripts/demo_capture/rehearse.py http://127.0.0.1:8014
```

Open the same URL in an isolated Chrome session for the two manual rehearsals. Use the playback start control and the approval button in the app. On the second pass, wait longer at approval and ask the same question. Compare the receipt hashes and measured effect with the first pass. Check that the paused clock holds, the action history shows one approval, and a reload reconnects at the current beat. Archive the rehearsal output and bundle digest with the raw clips.

```sh
export CHROME_DEVTOOLS_AXI_SESSION=argus-lane-f
CHROME_DEVTOOLS_AXI_HEADED=1 chrome-devtools-axi open http://127.0.0.1:8014
chrome-devtools-axi resize 1600 900
chrome-devtools-axi snapshot
```

## Export

Use a window capture of the Mission Control viewport for each shot. A continuous take can supply every shot. The viewport recorder samples the selected Argus tab in the isolated Chrome session. Run it in a second terminal with the same `CHROME_DEVTOOLS_AXI_SESSION` and perform the clicks while it records.

```sh
uv run --no-sync python scripts/demo_capture/record_viewport.py /absolute/path/to/argus-take.mp4 --seconds 120
```

Save the clips and media offsets in scratch storage. In `cuts.json`, map shot names to `{"file":"argus-take.mp4","start":0.0}`. Relative media paths resolve from the cuts file. Set each start to the first frame to keep in that shot, trimming any excess provider or simulation wait.

```sh
uv run --no-sync python scripts/demo_capture/render.py /absolute/path/to/cuts.json \
  /absolute/path/to/argus-agent.mp4 --source recorded
```

The renderer uses FFmpeg, ImageMagick and macOS `say`. It writes an H.264/AAC MP4 with burned-in captions and a matching SRT sidecar. Verify playback with sound and check the receipt drawer, Ask answer, decision and effect at full size.

## Playback integration

`POST /demo/start` accepts `{"scenario":"s4","variant":"agent","speed":1}` on a replay server. It returns a new presentation `run_id`, `sim_ts` and C5 `through_seq`. Read `GET /demo/snapshot?run_id=…` for visible C5 events and incidents. Follow `GET /demo/events?run_id=…` for timed beats. Pass the same `run_id` to `/demo/control` and evidence links. At `awaiting_approval` the clock and evidence cursor stop until the agent action route records approval or denial.

Use the same `Playback` instance in the agent API and `create_router(hub, playback=playback, allow_agent=source.mode == "replay")`. The agent API reads `playback.agent_view(run_id)` and calls `playback.decide(run_id, action_id, decision, digest, idempotency_key)` on the app event loop. The view exposes visible activities, proposals, qualified receipt proofs, and the matching recorded Ask answer. Revealed receipts keep their capture hashes. Denial finishes the scene at the proposal hour.
