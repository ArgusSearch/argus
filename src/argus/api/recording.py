"""A recorded run, as the API replays it: `fixtures/` (written by `make fixtures` or `argus run`).

| file              | content                                                    | required |
|-------------------|------------------------------------------------------------|----------|
| `events.jsonl`    | one C5 `Event` per line, `seq` strictly increasing         | yes      |
| `graph.json`      | the C3 `Graph` of the run                                  | no       |
| `incidents.json`  | the incidents at the end of the run (C4 `Incident` list)   | no       |
| `incidents.jsonl` | `{"seq": n, "incident": Incident}`: incidents as of seq n  | no       |
| `receipts.json`   | list of C4 `Receipt`                                       | no       |
| `manifest.json`   | the public world manifest (to find the world for re-runs)  | no       |

Replay must never show what the stream has not reached yet. With `incidents.jsonl` each snapshot
appears once its seq is published. With only `incidents.json` (the end state), every `incident_updated`
event gets a snapshot of the final incident cut back to that moment: its state, verdict, title and
severity from the event, its history up to the transition into that state (the k-th event with a state
matches the k-th transition into it), and only the trail steps published so far.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from argus.contracts.events import Event, EventType, IncidentUpdatedPayload, InvestigationStepPayload
from argus.contracts.findings import Incident, Receipt
from argus.contracts.graph import Graph
from argus.graph.store import REPO, load_seed_graph

FIXTURES = REPO / "fixtures"


class IncidentSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    incident: Incident


@dataclass
class Recording:
    events: list[Event]
    graph: Graph
    incidents: list[IncidentSnapshot] = field(default_factory=list)
    receipts: list[Receipt] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    def validate(self) -> None:
        """Check the invariants replay relies on (raises ValueError)."""
        seqs = [e.seq for e in self.events]
        if any(b <= a for a, b in itertools.pairwise(seqs)):
            raise ValueError("event seq must be strictly increasing")
        known = set(seqs)
        for snap in self.incidents:
            if snap.seq not in known:
                raise ValueError(f"incident snapshot {snap.incident.id} points at unknown seq {snap.seq}")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def progressive_snapshots(events: list[Event], final: list[Incident]) -> list[IncidentSnapshot]:
    """Snapshots of the final incidents cut back to each `incident_updated` event (see module doc)."""
    by_id = {i.id: i for i in final}
    snapshots: list[IncidentSnapshot] = []
    steps: dict[str, int] = {}
    entered: dict[tuple[str, str], int] = {}
    for event in events:
        if event.type is EventType.INVESTIGATION_STEP:
            step = InvestigationStepPayload.model_validate(event.payload)
            if step.incident_id:
                steps[step.incident_id] = steps.get(step.incident_id, 0) + 1
            continue
        if event.type is not EventType.INCIDENT_UPDATED:
            continue
        update = IncidentUpdatedPayload.model_validate(event.payload)
        incident = by_id.get(update.id)
        if incident is None:
            continue
        trail = incident.findings.trail[: steps.get(update.id, 0)] if update.id in steps else incident.findings.trail
        key = (update.id, update.state.value)
        entered[key] = entered.get(key, 0) + 1
        into = [i for i, h in enumerate(incident.history) if h.to_state is update.state]
        end = into[entered[key] - 1] + 1 if len(into) >= entered[key] else len(incident.history)
        cut = incident.model_copy(
            update={
                "title": update.title,
                "state": update.state,
                "verdict": update.verdict,
                "severity_eur": update.severity_eur,
                "segment": update.segment,
                "updated_at": event.sim_ts,
                "resolved_at": incident.resolved_at if update.state.value == "resolved" else None,
                "history": incident.history[:end],
                "findings": incident.findings.model_copy(update={"trail": trail}),
            }
        )
        snapshots.append(IncidentSnapshot(seq=event.seq, incident=cut))
    return snapshots


def load_recording(path: Path) -> Recording:
    """Load a recording directory (or a bare events.jsonl file)."""
    root = path.parent if path.is_file() else path
    events_path = path if path.is_file() else path / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"no events.jsonl in {path}")
    events = [Event.model_validate(e) for e in _jsonl(events_path)]
    graph_path = root / "graph.json"
    graph = Graph.model_validate_json(graph_path.read_text()) if graph_path.exists() else load_seed_graph()
    if (root / "incidents.jsonl").exists():
        incidents = [IncidentSnapshot.model_validate(s) for s in _jsonl(root / "incidents.jsonl")]
    elif (root / "incidents.json").exists():
        final = [Incident.model_validate(i) for i in json.loads((root / "incidents.json").read_text())]
        incidents = progressive_snapshots(events, final)
    else:
        incidents = []
    receipts_path = root / "receipts.json"
    raw: Any = json.loads(receipts_path.read_text()) if receipts_path.exists() else []
    receipts = [Receipt.model_validate(r) for r in (raw.values() if isinstance(raw, dict) else raw)]
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    recording = Recording(events, graph, incidents, receipts, manifest, root)
    recording.validate()
    return recording
