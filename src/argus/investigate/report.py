"""Template report of a Stage-2 investigation, written only from the C4 findings.

Same rules as the Stage-1 narrator (`argus.narrator.report`): every number carries the receipt it came
from (`[r12]`), and the report passes `unbacked_numbers` because it prints nothing that is not in the
findings JSON. On top of Stage 1 it shows every claim with its label (evidence or hypothesis, with
what would upgrade a hypothesis) and the hypothesis ledger: prediction, check, expected outcome, result.
No LLM is involved; an LLM-written report must pass the same number check or this one is used.
"""

from __future__ import annotations

from typing import Any

from argus.contracts.findings import Findings, TrailStep
from argus.contracts.graph import Graph
from argus.investigate.claims import claims_of
from argus.narrator.report import fmt, seg_text, tag

BADGE = {"evidence": "EVIDENCE", "hypothesis": "HYPOTHESIS"}


def _receipts(ids: list[str]) -> str:
    return " ".join(f"[{r}]" for r in ids)


def _ledger(findings: Findings) -> list[dict[str, Any]]:
    for step in reversed(findings.trail):
        if step.kind == "verdict" and "ledger" in step.data:
            return list(step.data["ledger"])
    return []


def _walk(findings: Findings) -> list[TrailStep]:
    return [s for s in findings.trail if s.kind == "decompose" and s.tool == "decompose_formula"]


def _playbook_lines(findings: Findings) -> list[str]:
    last = findings.trail[-1] if findings.trail else None
    if last is None or "playbook_run" not in last.data:
        return []
    name = last.data.get("playbook", {}).get("name", "Playbook")
    run = " -> ".join(
        step["label"] if step["status"] == "done" else f"~~{step['label']}~~" for step in last.data["playbook_run"]
    )
    return [f"**{name}:** {run}", ""]


def render_findings(findings: Findings, graph: Graph) -> str:
    f = findings
    label = graph.node(f.observed.node).label
    lines = [
        f"# {f.verdict.value.replace('_', ' ')} · {f.headline}",
        "",
        f"anomaly {f.anomaly_id}"
        + (f" · {f.incident_id}" if f.incident_id else "")
        + f" · as_of {f.as_of:%Y-%m-%d %H:%M}"
        f" · window {f.window.start:%Y-%m-%d %H:%M} to {f.window.end:%Y-%m-%d %H:%M}",
        "",
        *_playbook_lines(f),
        "## What happened",
        "",
        f"{label} in {seg_text(f.observed.segment)} moved {fmt(f.observed.change_pct, 2, pct=True)} against its "
        f"expectation (observed {fmt(f.observed.observed, 4)}, expected {fmt(f.observed.expected, 4)}).",
    ]
    if f.root:
        root_label = graph.node(f.root.node).label
        lines.append(
            f"Root: {root_label.lower()} in {seg_text(f.root.segment)} moved {fmt(f.root.change_pct, 1, pct=True)}; "
            f"it explains {f.explained_share * 100:.0f}% of the deviation, "
            f"{f.unexplained_share * 100:.0f}% stays unexplained."
        )
        if f.root.evidence:
            ev = f.root.evidence
            lines.append(f"Evidence: {ev.description} ({ev.log} `{ev.ref}`, {ev.ts:%Y-%m-%d %H:%M}).")
    else:
        lines.append(f"No root cause: {f.unexplained_share * 100:.0f}% of the deviation stays unexplained.")

    claims = claims_of(f)
    if claims:
        lines += ["", "## Claims, labelled", ""]
        for c in claims:
            upgrade = f" Would be confirmed by: {c.upgrade}." if c.upgrade else ""
            lines.append(f"- **{BADGE[c.label]}** {c.text} _({c.basis})_{upgrade} {_receipts(c.receipts)}".rstrip())

    if f.impact:
        i = f.impact
        lines += [
            "",
            "## Impact",
            "",
            f"{fmt(i.per_hour)} {i.node} per hour, {fmt(i.gmv_eur_per_hour, eur=True)} GMV per hour, "
            f"{fmt(i.eur_so_far, eur=True)} so far (over {i.hours} h).",
        ]

    walk = _walk(f)
    if walk or f.decomposition:
        lines += ["", "## Where the change came from", ""]
        for s in walk:
            lines.append(f"- {s.result} -> {s.decision} {_receipts(s.receipts)}".rstrip())
            if s.why:
                lines.append(f"  - why: {s.why}")
        if f.decomposition:
            lines += [
                "",
                f"Exact LMDI split of {f.decomposed_node} in the root segment:",
                "",
                "| factor | share of the change |",
                "| --- | --- |",
            ]
            lines += [f"| {c.node} | {c.share * 100:+.0f}%{tag(c.receipt)} |" for c in f.decomposition]

    ledger = _ledger(f)
    if ledger:
        lines += [
            "",
            "## Hypotheses tested (prediction written before the check ran)",
            "",
            "| # | hypothesis | prediction | check | expected | result | status |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for e in ledger:
            h = e["hypothesis"]
            lines.append(
                f"| {e['id']} | {h['statement']} | {h['prediction']} | {h['tool']} | {h['expect']} | "
                f"{e['summary']} {_receipts(e['receipts'])} | {e['status']} |"
            )

    if f.ruled_out:
        lines += ["", "## Ruled out", ""]
        for r in f.ruled_out:
            lines.append(
                f'- {r.hypothesis}: predicted "{r.prediction}"; {r.result} ({r.reason}) {_receipts(r.receipts)}'
            )
    if f.uncertain:
        lines += ["", "## Still uncertain", ""] + [f"- {u}" for u in f.uncertain]
    if f.suggested_action:
        lines += ["", "## Suggested action (needs human approval)", "", f.suggested_action.text]

    lines += ["", "## Investigation trail", ""]
    for s in f.trail:
        label = s.data.get("playbook", {}).get("label")
        prefix = f"[{label}] " if label else ""
        lines.append(
            f"{s.step}. {prefix}{s.kind} ({s.tool}): {s.result} -> {s.decision} {_receipts(s.receipts)}".rstrip()
        )
    lines += [
        "",
        "## Cost of this investigation",
        "",
        f"{f.cost.queries} queries · {f.cost.seconds:.2f} s · {f.cost.llm_calls} LLM calls",
        "",
    ]
    return "\n".join(lines)
