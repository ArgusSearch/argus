"""Generate the contract artifacts in `contracts/` from the pydantic models.

Usage: `python -m argus.contracts.export` (write) or `python -m argus.contracts.export --check` (CI).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from argus.contracts import CONTRACT_VERSION, events, findings, graph, metric, tools, world

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "contracts"


def _bundle(title: str, models: list[type[BaseModel]], extra: dict[str, Any] | None = None) -> str:
    _, schema = models_json_schema([(m, "validation") for m in models], title=title)
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "version": CONTRACT_VERSION, **schema}
    if extra:
        schema.update(extra)
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def _world_json() -> str:
    tables = [
        {
            "name": t.name,
            "kind": t.kind,
            "description": t.description,
            "raw_table": t.raw_name,
            "grain": t.grain,
            "measures": t.measures,
            "columns": [
                {"name": c.name, "type": c.sql_type, "role": c.role, "description": c.description} for c in t.columns
            ],
        }
        for t in world.ALL_TABLES
    ]
    doc = {
        "version": CONTRACT_VERSION,
        "as_of_variable": world.AS_OF_VARIABLE,
        "dimensions": {k: list(v) for k, v in world.DIMENSIONS.items()},
        "evidence_logs": list(world.EVIDENCE_LOGS),
        "tables": tables,
    }
    return json.dumps(doc, indent=2) + "\n"


def artifacts() -> dict[str, str]:
    tool_models: list[type[BaseModel]] = [m for pair in tools.TOOL_MODELS.values() for m in pair]
    return {
        "schema.sql": world.render_schema_sql(),
        "c1_world.json": _world_json(),
        "c2_metric.schema.json": _bundle("C2 metric definition", [metric.MetricDefinition]),
        "c3_graph.schema.json": _bundle("C3 metric graph", [graph.Graph, graph.GraphChange, graph.Certificate]),
        "c4_findings.schema.json": _bundle(
            "C4 findings and incidents",
            [findings.Receipt, findings.Anomaly, findings.Findings, findings.Note, findings.Incident],
        ),
        "c5_events.schema.json": _bundle(
            "C5 event stream",
            [events.Event, *events.PAYLOAD_MODELS.values()],
            {
                "event_types": {t.value: events.PAYLOAD_MODELS[t].__name__ for t in events.EventType},
                "reserved_event_types": sorted(t.value for t in events.RESERVED_EVENT_TYPES),
                "routes": [r.model_dump() for r in events.ROUTES],
            },
        ),
        "c6_tools.schema.json": _bundle(
            "C6 investigation tools", tool_models, {"tools": [t.model_dump() for t in tools.TOOLS]}
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if contracts/ is stale")
    args = parser.parse_args(argv)
    stale = []
    for name, content in artifacts().items():
        path = OUT / name
        if args.check:
            if not path.exists() or path.read_text() != content:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if stale:
        print(f"stale contract artifacts: {stale}. Run `make contracts`.", file=sys.stderr)
        return 1
    if not args.check:
        print(f"wrote {len(artifacts())} contract artifacts to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
