"""Grade one run: compare an agent's claims with the revealed truth of its world.

Every truth event except red herrings gets a grade on five levels (0..4). A confident wrong answer
scores 0, the same as a miss, so guessing never pays:

| grade | fault (SUPPORTED_CAUSE expected)            | innocent (EXPECTED)        | data (DATA_ISSUE)          |
|-------|---------------------------------------------|----------------------------|----------------------------|
| 4     | right node, segment, evidence, ruled out    | explained, cited the log   | data issue, no page        |
| 3     | right node and segment (or one dim off)     | explained, imprecise       | -                          |
| 2     | right node or evidence, segment overlaps    | silent: no page, no reason | -                          |
| 1     | paged, but no cause claimed                 | -                          | data issue, but also paged |
| 0     | missed, dismissed, or wrong cause as fact   | paged on a planned change  | missed, or paged only      |

A claim touches an event when it is made inside the event window, its segment does not contradict the
event's segment, and its node is one the event moves (when the truth lists `affected_nodes`).
A page that touches no fault is a false alarm. A run passes when every event grades 3 or more and it
raised no false alarm.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from argus.contracts.findings import Verdict
from bench.claims import Claim

LEAD = timedelta(hours=1)  # a claim may come slightly before the truth start (rounding to the hour)
GRACE = timedelta(hours=3)  # after the event's end plus the delivery lag
PASS_GRADE = 3
GRADED_KINDS = ("fault", "innocent", "data")


class WorldWindow(BaseModel):
    live_start: datetime
    world_end: datetime
    delivery_lag_hours: int

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> WorldWindow:
        return cls(
            live_start=datetime.fromisoformat(manifest["live_start"]),
            world_end=datetime.fromisoformat(manifest["world_end"]),
            delivery_lag_hours=int(manifest["delivery_lag_hours"]),
        )

    @property
    def live_days(self) -> float:
        return (self.world_end - self.live_start) / timedelta(days=1)


class EventGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    kind: str
    expected: str
    grade: int = Field(ge=0, le=4)
    label: str
    claim: str | None = Field(default=None, description="id of the claim that decided the grade")
    claimed: str | None = Field(default=None, description="verdict of that claim")
    ttd_hours: float | None = Field(default=None, description="truth start to first relevant claim, sim hours")

    @property
    def passed(self) -> bool:
        return self.grade >= PASS_GRADE


class RunGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: str
    scenario: str
    seed: int
    agent: str
    commitment: str
    verified: bool = Field(description="the revealed truth hashes to the commitment made before the run")
    live_days: float
    events: list[EventGrade]
    claims: int
    pages: int
    false_alarms: list[str] = Field(description="ids of pages that touch no fault")
    data_claims: int
    true_data_claims: int
    agent_seconds: float = 0.0
    error: str | None = Field(default=None, description="the agent crashed; graded as if it said nothing")

    @property
    def true_pages(self) -> int:
        return self.pages - len(self.false_alarms)

    @property
    def passed(self) -> bool:
        return self.verified and self.error is None and all(e.passed for e in self.events) and not self.false_alarms


class _Expect:
    """Accessors over one truth event's `expected` record (single values or `*_any` alternatives)."""

    def __init__(self, event: dict[str, Any], window: WorldWindow):
        exp = event["expected"]
        self.event = event
        self.verdict: str = exp.get("verdict", "")
        root = exp.get("root_node") or event.get("root_node")
        self.root_nodes: set[str] = set(exp.get("root_nodes_any") or ([root] if root else []))
        self.segments: list[dict[str, str]] = exp.get("segments_any") or [exp.get("segment", event["segment"])]
        evidence = exp.get("evidence")
        self.evidence: set[str] = set(exp.get("evidence_any") or ([evidence] if evidence else []))
        self.ruled_out: set[str] = set(exp.get("ruled_out", []))
        self.affected: set[str] = set(exp.get("affected_nodes", []))
        end = event["end_ts"] or window.world_end
        self.start: datetime = event["start_ts"]
        self.window = (self.start - LEAD, end + timedelta(hours=window.delivery_lag_hours) + GRACE)

    def touches(self, claim: Claim) -> bool:
        lo, hi = self.window
        if not lo <= claim.detected_at <= hi:
            return False
        if not any(_compatible(claim.segment, s) for s in self.segments):
            return False
        return not self.affected or claim.node is None or claim.node in self.affected | self.root_nodes

    def ttd(self, claims: list[Claim]) -> float | None:
        if not claims:
            return None
        return round((min(c.detected_at for c in claims) - self.start) / timedelta(hours=1), 2)


def _compatible(a: dict[str, str], b: dict[str, str]) -> bool:
    return all(a[k] == b[k] for k in a.keys() & b.keys())


def _one_dim_off(a: dict[str, str], b: dict[str, str]) -> bool:
    return _compatible(a, b) and len(a.keys() ^ b.keys()) == 1


def _cited(claim: Claim, ids: set[str]) -> set[str]:
    """Log ids the claim cites, structurally or (fallback) by name in its text."""
    return (set(claim.evidence) & ids) | {i for i in ids if i in claim.text}


def _grade_cause(claim: Claim, exp: _Expect) -> tuple[int, str]:
    if claim.evidence and set(claim.evidence) & exp.ruled_out:
        return 0, "blamed the red herring"
    cited = _cited(claim, exp.evidence)
    node_ok = claim.node in exp.root_nodes
    seg_exact = claim.segment in exp.segments
    seg_close = any(_one_dim_off(claim.segment, s) for s in exp.segments)
    evidence_ok = not exp.evidence or bool(cited)
    ruled_ok = exp.ruled_out <= (set(claim.ruled_out) | _cited(claim, exp.ruled_out))
    if node_ok and seg_exact and evidence_ok and ruled_ok:
        return 4, "exact"
    if node_ok and (seg_exact or (seg_close and evidence_ok)):
        return 3, "right cause" + ("" if evidence_ok else ", no evidence") + (
            "" if ruled_ok else ", decoy not ruled out"
        )
    if node_ok or cited:
        return 2, "partial: segment or node off"
    return 0, "wrong cause, stated as fact"


def _grade_fault(exp: _Expect, touching: list[Claim]) -> EventGrade:
    pages = [c for c in touching if c.is_page]
    causes = [c for c in pages if c.verdict == Verdict.SUPPORTED_CAUSE]
    base = {"event_id": exp.event["event_id"], "kind": "fault", "expected": exp.verdict, "ttd_hours": exp.ttd(pages)}
    if causes:
        scored = [(*_grade_cause(c, exp), c) for c in causes]
        grade, label, claim = max(scored, key=lambda t: t[0])
        return EventGrade(**base, grade=grade, label=label, claim=claim.id, claimed=claim.verdict)
    if pages:
        return EventGrade(**base, grade=1, label="paged, no cause", claim=pages[0].id, claimed=pages[0].verdict)
    if touching:
        c = touching[0]
        return EventGrade(**base, grade=0, label=f"dismissed as {c.verdict}", claim=c.id, claimed=c.verdict)
    return EventGrade(**base, grade=0, label="missed")


def _grade_innocent(exp: _Expect, touching: list[Claim]) -> EventGrade:
    base = {"event_id": exp.event["event_id"], "kind": "innocent", "expected": exp.verdict}
    pages = [c for c in touching if c.is_page]
    if pages:
        c = pages[0]
        return EventGrade(**base, grade=0, label="paged on a planned change", claim=c.id, claimed=c.verdict)
    explained = [c for c in touching if c.verdict == Verdict.EXPECTED]
    if not explained:
        return EventGrade(**base, grade=2, label="silent")
    best = next(
        (
            c
            for c in explained
            if c.node in exp.root_nodes and c.segment in exp.segments and (not exp.evidence or _cited(c, exp.evidence))
        ),
        None,
    )
    claim = best or explained[0]
    return EventGrade(
        **base,
        grade=4 if best else 3,
        label="explained" if best else "expected, imprecise",
        claim=claim.id,
        claimed=claim.verdict,
        ttd_hours=exp.ttd(explained),
    )


def _grade_data(exp: _Expect, touching: list[Claim]) -> EventGrade:
    base = {"event_id": exp.event["event_id"], "kind": "data", "expected": exp.verdict}
    pages = [c for c in touching if c.is_page]
    flagged = [c for c in touching if c.verdict == Verdict.DATA_ISSUE]
    ttd = exp.ttd(flagged)
    if pages:
        grade, label = (1, "data issue, but also paged") if flagged else (0, "paged a business incident")
        return EventGrade(**base, grade=grade, label=label, claim=pages[0].id, claimed=pages[0].verdict, ttd_hours=ttd)
    if flagged:
        c = flagged[0]
        return EventGrade(**base, grade=4, label="data issue", claim=c.id, claimed=c.verdict, ttd_hours=ttd)
    return EventGrade(**base, grade=0, label="missed")


_GRADERS = {"fault": _grade_fault, "innocent": _grade_innocent, "data": _grade_data}


def grade_run(
    truth: list[dict[str, Any]],
    claims: list[Claim],
    window: WorldWindow,
    *,
    case: str,
    scenario: str,
    seed: int,
    agent: str,
    commitment: str,
    verified: bool,
    agent_seconds: float = 0.0,
    error: str | None = None,
) -> RunGrade:
    graded = [_Expect(e, window) for e in truth if e["kind"] in GRADED_KINDS]
    events = [_GRADERS[x.event["kind"]](x, [c for c in claims if x.touches(c)]) for x in graded]
    faults = [x for x in graded if x.event["kind"] == "fault"]
    data = [x for x in graded if x.event["kind"] == "data"]
    pages = [c for c in claims if c.is_page]
    flagged = [c for c in claims if c.verdict == Verdict.DATA_ISSUE]
    return RunGrade(
        case=case,
        scenario=scenario,
        seed=seed,
        agent=agent,
        commitment=commitment,
        verified=verified,
        live_days=window.live_days,
        events=events,
        claims=len(claims),
        pages=len(pages),
        false_alarms=[c.id for c in pages if not any(x.touches(c) for x in faults)],
        data_claims=len(flagged),
        true_data_claims=sum(1 for c in flagged if any(x.touches(c) for x in data)),
        agent_seconds=round(agent_seconds, 2),
        error=error,
    )
