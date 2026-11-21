"""The six frozen contracts every lane codes against.

| id | contract           | module      | generated artifact                     | producer | consumers |
|----|--------------------|-------------|----------------------------------------|----------|-----------|
| C1 | world schema       | `world`     | `contracts/schema.sql`, `c1_world.json` | W        | G, B      |
| C2 | metric definition  | `metric`    | `contracts/c2_metric.schema.json`      | G        | all       |
| C3 | metric graph       | `graph`     | `contracts/c3_graph.schema.json`       | G        | B, U      |
| C4 | findings, incidents| `findings`  | `contracts/c4_findings.schema.json`    | B        | U, W      |
| C5 | events and API     | `events`    | `contracts/c5_events.schema.json`      | U        | all       |
| C6 | investigation tools| `tools`     | `contracts/c6_tools.schema.json`       | B, G     | B, U      |

Change a contract only with the agreement of its producer and consumers, then run `make contracts`.
CI fails when the generated artifacts are stale.
"""

CONTRACT_VERSION = "1.0.0"
