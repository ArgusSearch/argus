# Argus presentation

[Public HackLab Berlin presentation](https://a928840d.ht-ml.app/). The ten slides cover the metric graph, how Argus investigates changes, the recorded demo, and the benchmark. The “Scenario results” control on slide 9 opens the per-scenario results and the sealed benchmark commitment.

## Demo evidence

- **S2, planned spend.** The French budget increase appears in the held-back notes with its calendar change and receipt IDs. [S2 notes](../../fixtures/s2/notes.json)
- **S1, PayCo.** The incident report records the German Android segment and the unaffected Android holdout used to rule out the release. [Incident report](../../fixtures/report.md) · [SQL receipts](../../fixtures/receipts.json)
- **Metric placement.** The recorded certificates include exact cost per impression, ambiguous revenue per impression, and rejected ad spend per session. [Placement certificates](../../fixtures/graph_extension/placements.json)
- **S4, approved ad-pacing rollback.** The treated shop returned to a pacing ratio of 1.01 while the untreated twin remained at 4.05. [Verified action](../../fixtures/agent/v1/s4/approve/actions.json) · [SQL receipts e4 and e5](../../fixtures/agent/v1/s4/approve/receipts.json)

## Benchmark

The comparison uses the checked-in three-way scorecard. It covers the same six MockMart scenarios and three seeds per approach, with the language model off. [Scorecard](../../web/src/views/fixtures/scorecard.sample.json) · [Grading](../../src/bench/grade.py)

Run the comparison from the repository root.

```sh
uv run argus-bench run --agents argus,argus-stage1,threshold --out runs/bench
```
