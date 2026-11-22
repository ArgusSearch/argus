"""The agent's tools: Argus's own typed checks and state, nothing else (no free SQL, no shell).

Every tool has a name, a description and a JSON input schema (the shape an MCP server serves), and runs
through existing Argus code:

* data checks: the implemented C6 tools via `StageTwoToolbox.run` plus the S5 market control; each call
  states its hypothesis and prediction before it runs, and may name the outcome it expects, in which case
  the deterministic ledger (`argus.investigate.ledger`) judges it validated / refuted / inconclusive;
* state: incidents, findings, notes, receipts and playbooks as the runtime filed them.

`LiveTools` runs them against a world with the agent's own runner (receipt ids `a1`, `a2`, ...), so the
runtime's receipts and determinism are untouched. `RecordingTools` keeps every result and `TapeTools`
plays them back, which is how a recorded run replays with no world and no API call.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from argus.contracts.findings import Anomaly, Incident, Note, Receipt, TrailStep
from argus.contracts.graph import Graph
from argus.contracts.tools import TOOL_MODELS, TOOLS, ToolOutput
from argus.contracts.world import FACT_TABLES
from argus.investigate.ledger import OUTCOMES, TRAIL_KIND, Hypothesis, LedgerEntry, judge, outcome_of
from argus.investigate.tools import StageTwoToolbox, ToolUnavailable
from argus.market import check_control_group
from argus.narrator.autonomy import build_autonomy
from argus.semantic.runner import Runner

MAX_RESULT_CHARS = 6000
MAX_SERIES_HOURS = 72
AGENT_SOURCE = "planner:argus-agent"
# C6 tools the Stage-2 toolbox runs (lag_test is lane G's and not implemented), plus the market control
DATA_TOOLS = (
    "check_freshness",
    "check_identities",
    "get_series",
    "decompose_formula",
    "mix_rate_split",
    "segment_search",
    "list_events",
    "holdout_check",
    "placebo_test",
    "counterfactual_impact",
    "market_control",
)
STATE_TOOLS = ("list_incidents", "get_incident", "list_notes", "get_receipt", "list_playbooks")
MARKET_TOOL = "market_control"
FRESHNESS_TABLES = tuple(t.name for t in FACT_TABLES)
SIGNIFICANT = 6  # floats in tool results, as the model reads them


# ---------------------------------------------------------------------------------------------- state


@dataclass(frozen=True)
class Snapshot:
    """What the agent may read at one moment: the run as the source serves it."""

    as_of: datetime
    graph: Graph
    incidents: list[Incident]
    notes: list[Note]
    anomalies: dict[str, Anomaly]
    receipt: Callable[[str], Receipt | None]


# ---------------------------------------------------------------------------------------------- results


@dataclass
class ToolResult:
    name: str
    input: dict[str, Any]
    content: dict[str, Any]
    is_error: bool = False
    receipts: list[str] = field(default_factory=list)
    trail: TrailStep | None = None
    ledger: LedgerEntry | None = None
    new_receipts: list[Receipt] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return str(self.content.get("summary") or self.content.get("error") or "")

    def text(self) -> str:
        """What the model reads: compact JSON, cut at MAX_RESULT_CHARS."""
        text = json.dumps(self.content, separators=(",", ":"), default=str)
        return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + '..."(truncated)"'

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "input": self.input,
            "content": self.content,
            "is_error": self.is_error,
            "receipts": self.receipts,
            "trail": self.trail.model_dump(mode="json") if self.trail else None,
            "ledger": self.ledger.model_dump(mode="json") if self.ledger else None,
            "new_receipts": [r.model_dump(mode="json") for r in self.new_receipts],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ToolResult:
        return cls(
            name=data["name"],
            input=data["input"],
            content=data["content"],
            is_error=data["is_error"],
            receipts=data["receipts"],
            trail=TrailStep.model_validate(data["trail"]) if data["trail"] else None,
            ledger=LedgerEntry.model_validate(data["ledger"]) if data["ledger"] else None,
            new_receipts=[Receipt.model_validate(r) for r in data["new_receipts"]],
        )


def error(name: str, payload: dict[str, Any], message: str) -> ToolResult:
    return ToolResult(name, payload, {"error": message}, is_error=True)


def naive_utc(value: Any) -> Any:
    """Timestamps with a zone (the model likes '...Z') become naive UTC, the clock every world table uses."""
    if isinstance(value, dict):
        return {k: naive_utc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [naive_utc(v) for v in value]
    if isinstance(value, str) and len(value) >= 16 and value[4:5] == "-" and value[10:11] in ("T", " "):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        if parsed.tzinfo is not None:
            return parsed.astimezone(UTC).replace(tzinfo=None).isoformat()
    return value


def rounded(value: Any) -> Any:
    """Floats at SIGNIFICANT significant digits: what the model reads, quotes and is checked against."""
    if isinstance(value, float):
        return float(f"{value:.{SIGNIFICANT}g}")
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [rounded(v) for v in value]
    return value


# ---------------------------------------------------------------------------------------------- schemas


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve `$ref`s into `$defs` so every tool schema is self-contained."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items() if k not in ("$defs", "title")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_META = {
    "hypothesis": {"type": "string", "description": "what would be true if your idea holds (one sentence)"},
    "prediction": {"type": "string", "description": "what this check should show if it holds, written before it runs"},
}


def c6_schema(name: str) -> dict[str, Any]:
    base = inline_refs(TOOL_MODELS[name][0].model_json_schema())
    props = dict(base.get("properties", {}))
    props.update(_META)
    required = [*base.get("required", []), "hypothesis", "prediction"]
    if name in OUTCOMES:
        outcomes = list(OUTCOMES[name])
        props["expect"] = {
            "type": "string",
            "description": "optional: the outcome that would support the hypothesis; the deterministic ledger "
            "judges it. One of " + ", ".join(o if not o.endswith(":") else "factor:<node id>" for o in outcomes),
        }
    return _object(props, required)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]

    def api(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def _c6_description(name: str) -> str:
    spec = next(t for t in TOOLS if t.name == name)
    extra = {
        "get_series": f" At most {MAX_SERIES_HOURS} hours; expected = mean of the same hour in 4 earlier weeks.",
        "segment_search": " Searches inside `segment` and descends while one value dominates.",
        "holdout_check": " Pass an event exactly as list_events returned it.",
        "counterfactual_impact": " Orders and EUR lost per hour and so far, against the expectation.",
        "check_freshness": f" Tables: {', '.join(FRESHNESS_TABLES)}.",
    }.get(name, "")
    return spec.description + extra + " Runs SQL with a receipt; never accepts SQL."


def specs() -> dict[str, ToolSpec]:
    out = {n: ToolSpec(n, _c6_description(n), c6_schema(n)) for n in DATA_TOOLS if n != MARKET_TOOL}
    out[MARKET_TOOL] = ToolSpec(
        MARKET_TOOL,
        "S5 market comparison: is a traffic drop (sessions, orders, gmv) also in the independent market demand "
        "index? verdict market = the whole market moved (expected), us = only we moved.",
        _object({"anomaly_id": {"type": "string"}, **_META}, ["anomaly_id", "hypothesis", "prediction"]),
    )
    out["list_incidents"] = ToolSpec(
        "list_incidents", "Every incident Argus filed so far: id, title, verdict, state, root segment.", _object({}, [])
    )
    out["get_incident"] = ToolSpec(
        "get_incident",
        "One incident with its deterministic findings: observed change, root, LMDI split, impact, ruled out, "
        "the investigation trail with receipts.",
        _object({"incident_id": {"type": "string"}}, ["incident_id"]),
    )
    out["list_notes"] = ToolSpec(
        "list_notes",
        "Notes Argus logged without paging: expected changes, data issues, suppressed symptoms.",
        _object({}, []),
    )
    out["get_receipt"] = ToolSpec(
        "get_receipt",
        "The SQL, as_of and result hash behind a receipt id (r.. from the runtime, a.. from your own checks).",
        _object({"receipt_id": {"type": "string"}}, ["receipt_id"]),
    )
    out["list_playbooks"] = ToolSpec(
        "list_playbooks",
        "Argus's named playbooks and its autonomy boundary: what it decides alone and what needs a human.",
        _object({}, []),
    )
    return out


SPECS = specs()


# ---------------------------------------------------------------------------------------------- executors


class Tools(Protocol):
    def execute(self, name: str, payload: dict[str, Any], step: int) -> ToolResult: ...


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _incident_view(inc: Incident) -> tuple[dict[str, Any], list[str]]:
    f = inc.findings
    trail = [
        {
            "step": s.step,
            "kind": s.kind,
            "tool": s.tool,
            "result": s.result,
            "decision": s.decision,
            "receipts": s.receipts,
        }
        for s in f.trail
    ]
    view = {
        "id": inc.id,
        "title": inc.title,
        "state": inc.state.value,
        "verdict": inc.verdict.value,
        "root_node": inc.root_node,
        "segment": inc.segment,
        "direction": inc.direction,
        "severity_eur": inc.severity_eur,
        "opened_at": inc.opened_at.isoformat(),
        "anomalies": inc.anomalies,
        "symptoms": inc.symptoms,
        "history": [{"sim_ts": h.sim_ts.isoformat(), "to": h.to_state.value, "reason": h.reason} for h in inc.history],
        "findings": {
            "headline": f.headline,
            "window": _dump(f.window),
            "observed": _dump(f.observed),
            "root": _dump(f.root) if f.root else None,
            "decomposed_node": f.decomposed_node,
            "decomposition": [_dump(c) for c in f.decomposition],
            "impact": _dump(f.impact) if f.impact else None,
            "ruled_out": [_dump(r) for r in f.ruled_out],
            "uncertain": f.uncertain,
            "explained_share": f.explained_share,
            "unexplained_share": f.unexplained_share,
            "suggested_action": _dump(f.suggested_action) if f.suggested_action else None,
            "trail": trail,
        },
    }
    receipts = sorted({r for s in f.trail for r in s.receipts} | _quantity_receipts(_dump(f)), key=_rid)
    return view, receipts


def _quantity_receipts(data: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(data, dict):
        if isinstance(data.get("receipt"), str):
            found.add(data["receipt"])
        for v in data.values():
            found |= _quantity_receipts(v)
    elif isinstance(data, list):
        for v in data:
            found |= _quantity_receipts(v)
    return found


def _rid(receipt: str) -> tuple[str, int]:
    return receipt[0], int(receipt[1:]) if receipt[1:].isdigit() else 0


class StateTools:
    """The state tools, over a snapshot. Used live and in replay (they need no world)."""

    def __init__(self, snapshot: Callable[[], Snapshot], own_receipt: Callable[[str], Receipt | None]) -> None:
        self.snapshot = snapshot
        self.own_receipt = own_receipt

    def execute(self, name: str, payload: dict[str, Any]) -> ToolResult:
        snap = self.snapshot()
        if name == "list_incidents":
            items = []
            roots: set[str] = set()
            for each in sorted(snap.incidents, key=lambda i: i.id):
                root = each.findings.root
                if root and root.change_pct.receipt:
                    roots.add(root.change_pct.receipt)
                items.append(
                    {
                        "id": each.id,
                        "title": each.title,
                        "verdict": each.verdict.value,
                        "state": each.state.value,
                        "root_node": each.root_node,
                        "segment": each.segment,
                        "severity_eur": each.severity_eur,
                        "opened_at": each.opened_at.isoformat(),
                    }
                )
            content = {"summary": f"{len(items)} incident(s)", "incidents": items}
            return ToolResult(name, payload, content, receipts=sorted(roots, key=_rid))
        if name == "get_incident":
            inc = next((i for i in snap.incidents if i.id == payload.get("incident_id")), None)
            if inc is None:
                return error(name, payload, f"no incident {payload.get('incident_id')!r}")
            view, cited = _incident_view(inc)
            return ToolResult(name, payload, {"summary": inc.title, "incident": view}, receipts=cited)
        if name == "list_notes":
            notes = sorted(snap.notes, key=lambda n: (n.sim_ts, n.id))[-30:]
            content = {"summary": f"{len(notes)} note(s)", "notes": [_dump(n) for n in notes]}
            return ToolResult(name, payload, content, receipts=sorted({r for n in notes for r in n.receipts}, key=_rid))
        if name == "get_receipt":
            rid = str(payload.get("receipt_id", ""))
            found = self.own_receipt(rid) if rid.startswith("a") else snap.receipt(rid)
            if found is None:
                return error(name, payload, f"no receipt {rid!r}")
            return ToolResult(name, payload, {"summary": found.purpose, "receipt": _dump(found)}, receipts=[found.id])
        if name == "list_playbooks":
            autonomy = build_autonomy(snap.graph)
            content = {
                "summary": f"{len(autonomy.playbooks)} playbooks",
                "playbooks": [{"id": p.id, "name": p.name} for p in autonomy.playbooks],
                "decides_alone": [r.id for r in autonomy.decides_alone],
                "asks_first": [_dump(r) for r in autonomy.asks_first],
            }
            return ToolResult(name, payload, content)
        return error(name, payload, f"unknown tool {name!r}")


class LiveTools:
    """Runs the data checks against a world with the agent's own runner, and the state tools over the source."""

    def __init__(self, world: Any, snapshot: Callable[[], Snapshot], runner: Runner | None = None) -> None:
        self.runner = runner or Runner(world, receipt_prefix="a")
        self.snapshot = snapshot
        self.state = StateTools(snapshot, self.runner.receipts.get)

    def close(self) -> None:
        self.runner.close()

    def execute(self, name: str, payload: dict[str, Any], step: int) -> ToolResult:
        if name in STATE_TOOLS:
            return self.state.execute(name, payload)
        if name not in SPECS:
            return error(name, payload, f"unknown tool {name!r}; tools: {sorted(SPECS)}")
        before = len(self.runner.receipts)
        try:
            result = self._data(name, naive_utc(payload), step)
        except (ValidationError, KeyError, ValueError, ToolUnavailable, ZeroDivisionError) as exc:
            message = str(exc).splitlines()[0] if not isinstance(exc, ValidationError) else _validation(exc)
            return error(name, payload, f"{type(exc).__name__}: {message}")
        result.input = payload
        result.content = rounded(result.content)
        result.new_receipts = list(self.runner.receipts.values())[before:]
        return result

    def _data(self, name: str, payload: dict[str, Any], step: int) -> ToolResult:
        snap = self.snapshot()
        meta: dict[str, Any] = {k: payload[k] for k in ("hypothesis", "prediction", "expect") if k in payload}
        args = {k: v for k, v in payload.items() if k not in meta}
        if name == MARKET_TOOL:
            anomaly = snap.anomalies.get(str(args.get("anomaly_id")))
            if anomaly is None:
                raise KeyError(f"no anomaly {args.get('anomaly_id')!r}")
            assessment = check_control_group(self.runner, snap.graph, anomaly, snap.as_of)
            if assessment is None:
                content: dict[str, Any] = {"summary": "not applicable: only drops of sessions, orders or gmv"}
                return ToolResult(
                    name, payload, content, trail=self._trail(step, "holdout", name, meta, content["summary"], [])
                )
            content = {"summary": assessment.reason, **_dump(assessment)}
            content["series"] = content["series"][-6:]
            receipts = [assessment.receipt_id]
            trail = self._trail(
                step,
                "holdout",
                name,
                meta,
                assessment.reason,
                receipts,
                decision=f"market verdict: {assessment.verdict}",
            )
            return ToolResult(name, payload, content, receipts=receipts, trail=trail)

        if name == "check_freshness":
            unknown = sorted(set(args.get("tables") or []) - set(FRESHNESS_TABLES))
            if unknown:
                raise ValueError(f"unknown tables {unknown}; source tables: {list(FRESHNESS_TABLES)}")
        if name == "get_series":
            window = TOOL_MODELS[name][0].model_validate(args).window  # type: ignore[attr-defined]
            if (window.end - window.start).total_seconds() / 3600 >= MAX_SERIES_HOURS:
                raise ValueError(f"get_series is limited to {MAX_SERIES_HOURS} hours")
        output = StageTwoToolbox(snap.graph, self.runner, snap.as_of).run(name, args)
        ledger = self._judge(name, args, meta, output)
        content = _dump(output)
        decision = f"{ledger.status}: outcome {ledger.outcome or 'in between'}" if ledger else "observed"
        trail = self._trail(
            step, TRAIL_KIND.get(name, "events"), name, meta, output.summary, list(output.receipts), decision
        )
        if ledger is not None:
            trail.data["ledger"] = _dump(ledger)
        return ToolResult(name, payload, content, receipts=list(output.receipts), trail=trail, ledger=ledger)

    @staticmethod
    def _judge(name: str, args: dict[str, Any], meta: dict[str, Any], output: ToolOutput) -> LedgerEntry | None:
        expect = meta.get("expect")
        if not expect or name not in OUTCOMES:
            return None
        hypothesis = Hypothesis(
            statement=str(meta.get("hypothesis") or "-"),
            prediction=str(meta.get("prediction") or "-"),
            tool=name,
            input=args,
            expect=str(expect),
            source=AGENT_SOURCE,
        )
        outcome = outcome_of(name, output)
        return LedgerEntry(
            id="h0",
            hypothesis=hypothesis,
            status=judge(hypothesis, outcome),
            outcome=outcome,
            summary=output.summary,
            receipts=list(output.receipts),
        )

    @staticmethod
    def _trail(
        step: int,
        kind: str,
        tool: str,
        meta: dict[str, Any],
        result: str,
        receipts: list[str],
        decision: str = "observed",
    ) -> TrailStep:
        return TrailStep(
            step=step,
            kind=kind,  # type: ignore[arg-type]
            tool=tool,
            hypothesis=meta.get("hypothesis"),
            prediction=meta.get("prediction"),
            result=result,
            decision=decision,
            receipts=receipts,
            data={"source": AGENT_SOURCE},
        )


def _validation(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(p) for p in first.get("loc", ()))
    return f"{where}: {first.get('msg', 'invalid')}"


@dataclass
class RecordingTools:
    """Wraps an executor and keeps every result in call order."""

    inner: Tools
    tape: list[dict[str, Any]] = field(default_factory=list)

    def execute(self, name: str, payload: dict[str, Any], step: int) -> ToolResult:
        result = self.inner.execute(name, payload, step)
        self.tape.append(result.to_json())
        return result


class TapeMismatch(RuntimeError):
    """A replayed run asked for another tool call than the recording holds."""


class TapeTools:
    """Plays recorded tool results back; the call must match the recording exactly."""

    def __init__(self, tape: list[dict[str, Any]]) -> None:
        self._tape = [ToolResult.from_json(t) for t in tape]
        self._next = 0

    @property
    def remaining(self) -> int:
        return len(self._tape) - self._next

    def execute(self, name: str, payload: dict[str, Any], step: int) -> ToolResult:
        if self._next >= len(self._tape):
            raise TapeMismatch(f"the recording has no result for {name}")
        result = self._tape[self._next]
        self._next += 1
        if result.name != name or result.input != payload:
            raise TapeMismatch(f"recorded call {result.name}({result.input}) but the run asked {name}({payload})")
        return result
