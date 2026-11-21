# Mission Control showcase

Keep the four chapters in one Mission Control page. The first three advance automatically. S4 stops for the operator to approve or deny the rollback.

| Chapter | On-screen moment | Source |
| --- | --- | --- |
| Real fault | Argus catches the payment failure, tests the app release, and finds the PayCo cause. | S1 recording. Play at 8× for roughly 11 seconds. |
| Planned change | The FR advertiser’s planned budget raise increases ad spend. Argus logs it as expected and opens zero incidents. Open the note’s budget-log receipt for the evidence. | S2 recording. Play for 12 seconds. |
| New metric | Submit CPM to the graph. Its certificate shows the exact formula and live check. Submit the ambiguous case and show the competing placements in its certificate. | The graph extension’s real placement endpoint. |
| Agent and rollback | Argus investigates S4, answers a question about spend, waits for approval, then shows the measured effect against the untouched twin. | Sealed S4 agent presentation. See [the agent scene](agent-scene.md). |

## Integration

`GET /demo/showcase` delivers the ordered chapters. For a `playback` chapter, send its `start` body to `POST /demo/start`. Follow `GET /demo/snapshot?run_id=…` to update the current page with the visible events and incidents. The SSE `complete` event or a completed snapshot advances S1 and S2. The S2 `expected_change` cue carries the recorded note and its C4 receipt IDs. Starting a new playback chapter assigns a fresh run ID.

For the `metric_placement` chapter, follow the placement endpoint and display the returned certificates before starting S4. The hook advertises the required outcomes, EXACT followed by AMBIGUOUS. The graph extension supplies the request bodies and certificate fields.
