# fixtures

Recorded Argus runs, all seed 1, produced by `make fixtures`: the S1 run at the top level (`argus-bench s1 --seed 1 --record fixtures`) and one directory per other scenario (`argus-bench record <scenario> --seed 1 --out fixtures/<scenario>`).
`make api SCENARIO=<scenario>` replays one of them; `tests/api/test_api_scenarios.py` checks that a live run over a fresh world of the same seed still streams the same story, so re-record after changing what Argus does.

| Directory | Scenario | What the run shows |
| --- | --- | --- |
| `fixtures/` | S1 | PayCo DE/android outage: SUPPORTED_CAUSE, the release ruled out, resolved |
| `fixtures/quiet/` | quiet | nothing injected: no anomaly, no page |
| `fixtures/s2/` | S2 | planned FR budget increase: EXPECTED note, no page |
| `fixtures/s3/` | S3 | orders loader stall: DATA_ISSUE note, no business incident |
| `fixtures/s4/` | S4 | ad-pacer 1.7.0 overburn: SUPPORTED_CAUSE on pacing_ratio |
| `fixtures/s5/` | S5 | market-wide demand dip: three EXPECTED notes from the market control; checkout-routing fault on DE/android/PayCo: SUPPORTED_CAUSE, resolved |

The top-level S1 files:

| File | Contract | What it is |
| --- | --- | --- |
| `events.jsonl` | C5 | every event of the run, one JSON `Event` per line (what `GET /events` streams) |
| `graph.json` | C3 | the seed graph after its edge tests ran |
| `incidents.json` | C4 | incidents with findings, trail and lifecycle |
| `findings.json` | C4 | the findings of the S1 incident |
| `anomalies.json` | C4 | anomalies opened by the watcher |
| `notes.json` | C4 | "didn't wake you" and data-issue notes |
| `receipts.json` | C4 | every query of the run with its pinned as_of and hash |
| `report.md` | narrator | the template report of the incident |
| `manifest.json` | C1 | the public world manifest |

The scenario directories hold the runtime export instead (`graph.json`, `events.jsonl`, `incidents.json`, `notes.json`, `anomalies.json`, `receipts.json`, `graph_changelog.jsonl`, `reports/<incident>.md`) plus `manifest.json`.

`receipts.json` re-runs against the world of seed 1: `make world SCENARIO=<scenario> SEED=1`, then `make demo SCENARIO=<scenario> SEED=1` and `POST /receipts/{id}/rerun`.
Timings (`ms`, `cost.seconds`) differ between recordings; everything else is deterministic for a seed.
