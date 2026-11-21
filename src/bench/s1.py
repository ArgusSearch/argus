"""S1 end to end: simulate, run Argus over the world only, then grade against the hidden truth.

The bench is the only code that reads truth.duckdb. Each S1 exit criterion is one `Criterion`;
`tests/e2e/test_s1.py` asserts each of them on three seeds.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from argus.contracts.findings import Incident, Verdict
from argus.narrator.report import render, unbacked_numbers
from argus.runtime.loop import Runtime
from mockmart.scenarios.s1_payco import QUIET_LIVE_HOURS
from mockmart.sim import WorldConfig
from mockmart.truth import read_truth
from mockmart.world import generate

HOUR = timedelta(hours=1)
NUMBER_SECTIONS = ("## What happened", "## Impact", "## Where the change came from", "## Ruled out")


@dataclass
class Criterion:
    id: str
    description: str
    passed: bool
    detail: str


@dataclass
class S1Run:
    seed: int
    out: Path
    runtime: Runtime
    truth: dict[str, Any]
    criteria: list[Criterion] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.criteria)

    def criterion(self, cid: str) -> Criterion:
        return next(c for c in self.criteria if c.id == cid)


def run_s1(seed: int, out: Path) -> S1Run:
    paths = generate("s1", WorldConfig(seed=seed), out)
    runtime = Runtime(paths.world)  # Argus gets the world, never the truth
    runtime.run()
    runtime.export(out / "argus")
    truth = next(e for e in read_truth(paths.truth) if e["kind"] == "fault")
    run = S1Run(seed=seed, out=out, runtime=runtime, truth=truth)
    run.criteria = grade(runtime, truth)
    return run


def _seg(segment: dict[str, str]) -> str:
    return "/".join(segment.values()) or "total"


def grade(rt: Runtime, truth: dict[str, Any]) -> list[Criterion]:
    expected = truth["expected"]
    t0: datetime = truth["start_ts"]
    t1: datetime = truth["end_ts"]
    incidents: list[Incident] = list(rt.book.incidents.values())
    supported = [i for i in incidents if i.verdict is Verdict.SUPPORTED_CAUSE]
    match = [
        i
        for i in supported
        if i.root_node == expected["root_node"]
        and i.segment == expected["segment"]
        and i.findings.root is not None
        and i.findings.root.evidence is not None
        and i.findings.root.evidence.ref == expected["evidence"]
    ]
    out = []
    first = match[0] if match else (incidents[0] if incidents else None)
    out.append(
        Criterion(
            "supported_cause",
            "S1 -> SUPPORTED_CAUSE on payment_success_rate in DE / android / PayCo, evidence: PayCo status",
            len(match) == 1,
            f"{first.id} {first.verdict.value} {first.root_node} {_seg(first.segment)}" if first else "no incident",
        )
    )
    ruled = [r for i in match for r in i.findings.ruled_out if r.evidence and r.evidence.ref in expected["ruled_out"]]
    out.append(
        Criterion(
            "release_ruled_out",
            "the android 8.3.0 release is listed under 'ruled out' because the holdout is normal",
            # Stage 1 writes the bare label, Stage 2 appends the holdout's numbers ("holdout normal: +0.3% ...").
            bool(ruled) and all(r.result == "refuted" and r.reason.startswith("holdout normal") for r in ruled),
            "; ".join(f"{r.evidence.ref if r.evidence else '?'}: {r.reason}" for r in ruled) or "release not ruled out",
        )
    )
    delay = (first.opened_at - t0) / HOUR if first else None
    out.append(
        Criterion(
            "detected_within_3h",
            f"incident opens at most {expected['max_detection_delay_hours']} data hours after the onset",
            delay is not None and 0 <= delay <= expected["max_detection_delay_hours"],
            f"opened {delay:.0f} h after onset (data hour), {delay + rt.lag / HOUR:.0f} h wall clock"
            if delay is not None
            else "never opened",
        )
    )
    live_start = datetime.fromisoformat(str(rt.manifest["live_start"]))
    quiet_hours = (t0 - live_start) / HOUR
    early = [a for a in rt.anomalies.values() if a.hour < t0]
    out.append(
        Criterion(
            "quiet_hours_silent",
            f"no alert in the >= {QUIET_LIVE_HOURS} quiet live hours before the fault",
            quiet_hours >= QUIET_LIVE_HOURS and not early,
            f"{quiet_hours:.0f} quiet hours, {len(early)} anomalies before onset",
        )
    )
    fingerprints = [i.fingerprint for i in incidents]
    first = incidents[0] if incidents else None
    resolved = first is not None and first.resolved_at is not None and first.resolved_at >= t1
    out.append(
        Criterion(
            "one_incident",
            "the same problem is reported once: one incident, symptoms suppressed, resolved after recovery",
            len(incidents) == 1 and len(set(fingerprints)) == len(fingerprints) and resolved,
            f"{len(incidents)} incident(s), {len(rt.anomalies)} anomalies, "
            f"{sum(n.kind == 'suppressed' for n in rt.book.notes)} suppressed, "
            f"state {first.state.value if first else '-'}",
        )
    )
    out.append(_receipts_criterion(rt, match[0] if match else first))
    return out


def _receipts_criterion(rt: Runtime, inc: Incident | None) -> Criterion:
    if inc is None:
        return Criterion("receipts_reproducible", "every number has a receipt that re-runs", False, "no incident")
    report = render(inc, rt.graph)
    unbacked = unbacked_numbers(report, inc.findings, extra=inc.model_dump(mode="json"))
    untagged = []
    section = None
    for line in report.splitlines():
        if line.startswith("## "):
            section = line
        elif (
            section
            and section.startswith(NUMBER_SECTIONS)
            and any(ch.isdigit() for ch in line)
            and "[r" not in line
            and not line.startswith(("| ---", "| factor"))
        ):
            untagged.append(line)
    cited = sorted(_receipt_ids(inc))
    reruns = [rt.runner.rerun(r) for r in cited]
    mismatched = [r for r, (_, ok) in zip(cited, reruns, strict=True) if not ok]
    return Criterion(
        "receipts_reproducible",
        "every number in the report has a receipt; re-running every cited receipt returns the same hash",
        not unbacked and not untagged and not mismatched and bool(cited),
        f"{len(cited)} receipts re-run, {len(mismatched)} mismatched, {len(unbacked)} unbacked numbers, "
        f"{len(untagged)} untagged lines",
    )


def _receipt_ids(inc: Incident) -> set[str]:
    data = inc.findings.model_dump(mode="json")
    found: set[str] = set()

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                if k in ("receipt",) and isinstance(x, str):
                    found.add(x)
                elif k == "receipts" and isinstance(x, list):
                    found.update(x)
                else:
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(data)
    return found


def record_fixtures(run: S1Run, target: Path) -> None:
    """Copy one run's outputs into fixtures/ so the UI and MCP lanes can build against real data."""
    target.mkdir(parents=True, exist_ok=True)
    src = run.out / "argus"
    for name in ("graph.json", "events.jsonl", "incidents.json", "notes.json", "receipts.json", "anomalies.json"):
        shutil.copy(src / name, target / name)
    inc = next(iter(run.runtime.book.incidents.values()))
    (target / "findings.json").write_text(json.dumps(inc.findings.model_dump(mode="json"), indent=2) + "\n")
    shutil.copy(src / "reports" / f"{inc.id}.md", target / "report.md")
    shutil.copy(run.out / "manifest.json", target / "manifest.json")
