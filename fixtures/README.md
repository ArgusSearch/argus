# fixtures

One recorded S1 run (seed 1), produced by `make fixtures` (`argus-bench s1 --seed 1 --record fixtures`).
Lanes build against these files before the producing lane's code is ready.

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

`receipts.json` re-runs against the world of seed 1: `make world SEED=1`, then `make demo SEED=1` and `POST /receipts/{id}/rerun`.
Timings (`ms`, `cost.seconds`) differ between recordings; everything else is deterministic for a seed.
