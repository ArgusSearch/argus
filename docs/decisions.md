# Decisions

## Board decisions D1 to D9

Recommended picks stand until the team confirms them.

| Id | Decision | Current pick |
| --- | --- | --- |
| D1 | How agentic is the investigation? | fixed procedure with a visible planner |
| D2 | Marketplace only, or with a rewards layer? | rewards yes but small (cashback postback scenario) |
| D3 | Which moment opens the demo? | blind challenge, go/no-go Sunday 10:30 |
| D4 | Where does Argus speak? | app plus MCP, no Slack |
| D5 | Name | Argus |
| D6 | Deadline to plan against | Sunday 16:30 |
| D7 | Repository at submission | public |
| D8 | Roles and sleep shifts | as proposed in the build plan |
| D9 | Working mode in the repo | fast path: automated tests plus review by the lane owner |

## Engineering decisions (Stage 0)

1. **One process.**
   DuckDB allows one writer per file, so simulator delivery, Argus and the API run in one process; the bench reads its own files.
   The world is generated in full up front; the clock only advances `as_of`, and views hide every batch that has not arrived yet.
2. **Pinned `as_of` and canonical hashes.**
   Every receipt re-runs to the same hash, even after late data (tested in `tests/unit/test_semantic.py`).
3. **Micro-batches.**
   Late and partial data are missing batches, so `SUM` stays the only aggregation and completeness is `SUM(share)` in `log_ingestion`.
   History far before the live window is stored compacted as one batch; it is complete for every `as_of` the runtime uses.
4. **Truth wall.**
   Only `src/bench/` reads `truth.duckdb`; Argus never imports the simulator (enforced by tests).
5. **Decoys in the logs.**
   About three innocent deploys per day and regular provider maintenance entries, so the deploy next to a fault is not automatically the cause.
6. **Payments grain.**
   `fact_payments_hourly` is `(ts, country, platform, provider)`, the natural grain of a payment gateway.
   The identity `orders = payment_successes` holds per `(ts, country, platform)`.
7. **Ratio nodes never fan out.**
   Numerator and denominator are aggregated in their own tables at the requested grain and joined only afterwards.
8. **Log residuals and a full sampling floor.**
   The detector scores `ln(observed / expected)`; the floor includes the sampling noise of the hour and of the 4-week baseline.
   Plain relative residuals let a small Poisson denominator (cpa) push |z| over the line.
9. **Thresholds are measured, not guessed.**
   On 40 quiet worlds (seeds 200 to 239, 120 live hours times 7 north-star nodes each) the vision's rule `|z| > 4` would have paged in 6 of 40 worlds (largest |z| 4.63); the second value of "2 of 3 hours" peaked at 3.28.
   Chosen: open on `|z| > 5` or on 2 of the last 3 hours `|z| > 3.5` with the same sign.
   Validation: 0 false alarms on 40 fresh quiet worlds (seeds 300 to 339); S1 on seeds 1 to 20 detected 0 to 2 data hours after the onset, all criteria passing.
   Reproduce S1 with `uv run argus-bench s1 --seed 1 --seed 2 --seed 3`; a quiet-world calibration command in the bench is lane W work.
10. **The root's own onset.**
    A symptom can cross its alert line hours after the root segment started; the investigator scans the root segment hour by hour (|z| > 3) and aligns the evidence window with that onset.
11. **Descent rule.**
    The naive "simplest cell with 67%" stops at `country = DE`; Argus descends into a single cell while it explains at least 25 points more than its volume share and |z| >= 3, which yields `DE / android / PayCo`.
12. **S1 provider status scope.**
    The PayCo status entry is scoped `{provider: PayCo, country: DE, platform: android}`; its holdout is empty (not applicable), while the release's holdout (Android outside the segment) is normal, so the release is ruled out.
13. **Pacing node.**
    The seed graph has `pacing_ratio = ad_spend / planned_spend` per hour.
    The cumulative `budget_burn` for S4 is lane B and W work.
14. **Personal data.**
    No names, emails or secrets in the repo; MockMart names are fictional; `.env` is ignored and `.env.example` holds only empty keys.

## Libraries for the Argus Ice style layer

- **Three.js** (`three`, MIT, with `@types/three`, MIT): renders the metric graph as a 3D scene in the Argus Ice interface (the default; not with `?classic=1`); loaded only in the lazy scene chunk, never in the classic interface.
- **IBM Plex Mono** (`@fontsource/ibm-plex-mono`, SIL Open Font License 1.1): the mono face of the style layer, weights 400 and 500, bundled so the demo needs no network.
- **Bot Avatars** (`bot-avatars` 0.2.2, MIT, (c) Jakub Antalik, libraries.dev/bots): the plush body of the seven agent avatars (`web/src/village/avatars`); drawn on a 2D canvas, our own armor and nameplates on top, no assets copied.
