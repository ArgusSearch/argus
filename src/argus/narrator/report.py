"""Template report (the fallback that always works) and the number check.

The narrator only ever sees the structured findings. Every number in the report is printed next to the
receipt it came from, as `[r12]`. `unbacked_numbers` extracts every number from a report and fails the
report if a number does not appear in the findings JSON: an LLM-written report (Stage 2, lane U) must pass
the same check, otherwise Argus falls back to this template.
"""

from __future__ import annotations

import json
import re
from typing import Any

from argus.contracts.findings import Findings, Incident, Quantity
from argus.contracts.graph import Graph


def tag(receipt: str | None) -> str:
    return f" [{receipt}]" if receipt else ""


def fmt(q: Quantity, digits: int = 1, pct: bool = False, eur: bool = False) -> str:
    if eur:
        text = f"EUR {q.value:+,.0f}"
    elif pct:
        text = f"{q.value:+.{digits}f}%"
    else:
        text = f"{q.value:,.{digits}f}"
    return text + tag(q.receipt)


def seg_text(segment: dict[str, str]) -> str:
    return " / ".join(segment.values()) if segment else "all segments"


def render(incident: Incident, graph: Graph) -> str:
    f = incident.findings
    label = graph.node(f.observed.node).label
    lines = [
        f"# {f.verdict.value.replace('_', ' ')} · {f.headline}",
        "",
        f"{incident.id} · state {incident.state.value} · opened {incident.opened_at:%Y-%m-%d %H:%M} UTC"
        f" · as_of {f.as_of:%Y-%m-%d %H:%M}",
        "",
        "## What happened",
        "",
        f"{label} moved {fmt(f.observed.change_pct, 2, pct=True)} against its expectation "
        f"(observed {fmt(f.observed.observed, 4)}, expected {fmt(f.observed.expected, 4)}).",
    ]
    if f.root:
        root_label = graph.node(f.root.node).label
        lines.append(
            f"Inside {seg_text(f.root.segment)}, {root_label.lower()} moved {fmt(f.root.change_pct, 1, pct=True)}; "
            f"this segment explains {f.explained_share * 100:.0f}% of the deviation."
        )
        if f.root.evidence:
            ev = f.root.evidence
            found = next((s.receipts[0] for s in f.trail if s.kind == "events" and s.receipts), None)
            lines.append(f"Evidence: {ev.description} ({ev.log} `{ev.ref}`, {ev.ts:%Y-%m-%d %H:%M}){tag(found)}.")
    if f.impact:
        i = f.impact
        lines += [
            "",
            "## Impact",
            "",
            f"{fmt(i.per_hour)} {i.node} per hour, {fmt(i.gmv_eur_per_hour, eur=True)} GMV per hour, "
            f"{fmt(i.eur_so_far, eur=True)} so far (over {i.hours} h).",
        ]
    if f.decomposition:
        lines += [
            "",
            f"## Where the change came from (LMDI on {f.decomposed_node}, exact)",
            "",
            "| factor | share of the change |",
            "| --- | --- |",
        ]
        lines += [f"| {c.node} | {c.share * 100:+.0f}%{tag(c.receipt)} |" for c in f.decomposition]
    if f.ruled_out:
        lines += ["", "## Ruled out", ""]
        for r in f.ruled_out:
            receipt = tag(r.receipts[0] if r.receipts else None)
            lines.append(f'- {r.hypothesis}: predicted "{r.prediction}"; {r.result} ({r.reason}){receipt}')
    if f.uncertain:
        lines += ["", "## Still uncertain", ""] + [f"- {u}" for u in f.uncertain]
    if f.suggested_action:
        lines += ["", "## Suggested action (needs human approval)", "", f.suggested_action.text]
    lines += ["", "## Lifecycle", ""]
    lines += [f"- {t.sim_ts:%Y-%m-%d %H:%M} {t.to_state.value}: {t.reason}" for t in incident.history]
    lines.append(f"- severity (cumulative EUR impact while open): EUR {incident.severity_eur:,.0f}")
    if incident.reopened:
        lines.append(f"- reopened {incident.reopened} time(s) with the same fingerprint")
    lines += ["", "## Investigation trail", ""]
    for s in f.trail:
        receipts = " ".join(f"[{r}]" for r in s.receipts)
        lines.append(f"{s.step}. {s.kind}: {s.result} -> {s.decision} {receipts}".rstrip())
    lines += [
        "",
        "## Cost of this investigation",
        "",
        f"{f.cost.queries} queries · {f.cost.seconds:.2f} s · {f.cost.llm_calls} LLM calls",
        "",
    ]
    return "\n".join(lines)


_NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")
_SKIP = re.compile(r"\[r\d+\]|`[^`]*`|INC-\d+|\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?|r\d+|\b\d+\.\s")


def _numbers_in(value: Any, out: set[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        out.add(float(value))
    elif isinstance(value, str):
        for m in _NUMBER.findall(_SKIP.sub(" ", value)):
            out.add(float(m.replace(",", "")))
    elif isinstance(value, dict):
        for v in value.values():
            _numbers_in(v, out)
    elif isinstance(value, list | tuple):
        for v in value:
            _numbers_in(v, out)


def unbacked_numbers(report: str, findings: Findings, extra: dict[str, Any] | None = None) -> list[str]:
    """Numbers in the report that do not appear in the findings (or `extra` facts), allowing for rounding
    and percentage formatting. An empty list means the report passes the number check."""
    known: set[float] = set()
    _numbers_in(json.loads(findings.model_dump_json()), known)
    _numbers_in(extra or {}, known)
    candidates = known | {v * 100 for v in known}
    bad = []
    for line in report.splitlines():
        for m in _NUMBER.findall(_SKIP.sub(" ", line)):
            x = float(m.replace(",", ""))
            decimals = len(m.split(".")[1]) if "." in m else 0
            tol = 0.5 * 10**-decimals + 1e-9
            if not any(abs(abs(x) - abs(v)) <= tol for v in candidates):
                bad.append(m)
    return bad
