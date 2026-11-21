"""The fixed opening of every investigation (Stage 1, no LLM).

1. freshness     data before business: incomplete source tables -> DATA_ISSUE
2. identities    cross-table identities (orders = payment_successes) must hold -> else DATA_ISSUE
3. calendar      planned events in the window (S2 turns a match inside its band into EXPECTED)
4. decompose     exact LMDI split along product formulas; follow the factor with the largest share
5. segment       smallest segment that explains >= 67% of the deviation, descending while concentrated
6. events        log entries in [onset - 3h, onset + 1h] whose scope covers the segment
7. holdout       per candidate: the event's scope minus the segment must move too, else it is ruled out
8. impact        orders and EUR lost against the expectation, plus the exact split of the north star
9. verdict       SUPPORTED_CAUSE needs an aligned, not-refuted event and >= 20% explained

Stage 2 (lane B) adds the hypothesis ledger with the LLM planner after step 7, and the skeptic.
Every step is appended to the trail with its receipts; `on_step` streams it to the UI as it happens.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta

from argus.contracts.findings import (
    Anomaly,
    Contribution,
    Cost,
    EvidenceRef,
    Findings,
    Impact,
    ObservedChange,
    Quantity,
    RootCause,
    RuledOut,
    Segment,
    SuggestedAction,
    TrailStep,
    Verdict,
    Window,
)
from argus.contracts.graph import EdgeKind, Graph, NodeKind
from argus.decompose.segments import Cell
from argus.graph.store import product_factors
from argus.investigator.tools import Toolbox
from argus.semantic.compile import measures_window_sql, segment_where, tables_of, window_hours
from argus.semantic.runner import Runner

HOUR = timedelta(hours=1)
SUPPORTED_MIN_EXPLAINED = 0.20
STOP_EXPLAINED = 0.80
MAX_STEPS = 12
EVENT_BEFORE = timedelta(hours=3)
EVENT_AFTER = timedelta(hours=1)
IMPACT_NODE = "orders"


def segment_text(segment: Segment) -> str:
    return " / ".join(segment.values()) if segment else "all segments"


class Investigation:
    def __init__(
        self,
        graph: Graph,
        runner: Runner,
        anomaly: Anomaly,
        as_of: datetime,
        on_step: Callable[[TrailStep], None] | None = None,
    ):
        self.graph = graph
        self.runner = runner
        self.anomaly = anomaly
        self.as_of = as_of
        self.tools = Toolbox(graph, runner, as_of)
        self.trail: list[TrailStep] = []
        self.on_step = on_step
        self.window = Window(start=anomaly.onset, end=anomaly.hour)

    def step(self, kind: str, tool: str, result: str, decision: str, **extra: object) -> TrailStep:
        step = TrailStep(step=len(self.trail) + 1, kind=kind, tool=tool, result=result, decision=decision, **extra)  # type: ignore[arg-type]
        self.trail.append(step)
        if self.on_step:
            self.on_step(step)
        return step

    # ------------------------------------------------------------------ main
    def run(self) -> Findings:
        started, queries0 = time.perf_counter(), self.runner.query_count
        a = self.anomaly
        node = self.graph.node(a.node)
        observed = self._observed()

        tables = sorted(set(tables_of(self.graph, a.node)) | self._identity_tables())
        fresh = self.tools.check_freshness(tables, self.window)
        self.step(
            "freshness",
            "check_freshness",
            fresh.summary,
            "continue" if fresh.ok else "stop: DATA_ISSUE",
            receipts=fresh.receipts,
            data={"tables": [t.model_dump(mode="json") for t in fresh.tables]},
        )
        if not fresh.ok:
            return self._finish(
                Verdict.DATA_ISSUE, observed, started, queries0, headline=f"{node.label}: source data incomplete"
            )

        ident = self.tools.check_identities(self.window)
        self.step(
            "identities",
            "check_identities",
            ident.summary,
            "continue" if ident.ok else "stop: DATA_ISSUE",
            receipts=ident.receipts,
            data={"identities": [i.model_dump() for i in ident.identities]},
        )
        if not ident.ok:
            return self._finish(
                Verdict.DATA_ISSUE, observed, started, queries0, headline=f"{node.label}: identity broken"
            )

        cal = self.tools.list_events(self.window.start - EVENT_BEFORE, self.window.end, logs=["log_calendar"])
        self.step(
            "calendar",
            "list_events",
            cal.summary if cal.events else "no planned event in the window",
            "continue: not an expected change"
            if not cal.events
            else "continue: planned events found (S2 band check, lane B)",
            receipts=cal.receipts,
            data={"events": [e.model_dump(mode="json") for e in cal.events]},
        )

        focus = a.node
        decomp = self.tools.decompose_formula(a.node, {}, self.window)
        if decomp is not None:
            same_sign = [c for c in decomp.contributions if c.value * (1 if a.direction == "up" else -1) > 0]
            focus = (same_sign or decomp.contributions)[0].node
            self.step(
                "decompose",
                "decompose_formula",
                decomp.summary,
                f"follow {focus}",
                receipts=decomp.receipts,
                data={"contributions": [c.model_dump() for c in decomp.contributions], "residual": decomp.residual},
            )
        else:
            self.step(
                "decompose",
                "decompose_formula",
                f"{a.node} has no formula children",
                f"localise {a.node} directly",
                why="leaf node: the exact split ends here",
            )

        search = self.tools.segment_search(focus, self.window)
        seg = search.output.segment
        explained = search.output.explained_share
        self.step(
            "segment",
            "segment_search",
            search.output.summary,
            f"root segment {segment_text(seg)}",
            receipts=search.output.receipts,
            data={"path": [p.model_dump() for p in search.output.path]},
        )

        focus_node = self.graph.node(focus)
        onset = a.onset
        if seg:
            root_onset, rid = self.tools.segment_onset(focus, seg, a.hour, a.direction)
            if root_onset is not None and root_onset < a.onset:
                onset = root_onset
                self.window = Window(start=onset, end=a.hour)
            self.step(
                "segment",
                "get_series",
                f"root segment deviates since {onset:%Y-%m-%d %H:%M}"
                + (f", {int((a.onset - onset) / HOUR)} h before the symptom" if onset < a.onset else ""),
                "align evidence with the root onset",
                receipts=[rid],
                data={"onset": onset.isoformat()},
            )
        logs = sorted({src for e in self.graph.edges_into(focus, EdgeKind.EVIDENCE) for src in e.sources})
        events = self.tools.list_events(
            onset - EVENT_BEFORE, onset + EVENT_AFTER, logs=logs, covering=seg, node_dims=focus_node.dims
        )
        self.step(
            "events",
            "list_events",
            events.summary,
            f"test {len(events.events)} candidate(s)" if events.events else "no aligned event",
            receipts=events.receipts,
            data={"events": [e.model_dump(mode="json") for e in events.events]},
        )

        supported: list[EvidenceRef] = []
        ruled_out: list[RuledOut] = []
        for ev in events.events:
            if len(self.trail) >= MAX_STEPS - 2:
                break
            hypothesis = f"{ev.description} ({ev.ref}) caused the change"
            prediction = (
                f"everything in the event's scope moves, not only {segment_text(seg)}"
                if ev.scope != {k: [v] for k, v in seg.items()}
                else f"the change is confined to {segment_text(seg)}"
            )
            hold = self.tools.holdout_check(ev, focus, seg, self.window, search.final.rel_change)
            decision = {
                "refuted": "ruled out",
                "consistent": "keep as cause",
                "not_applicable": "keep as cause",
                "inconclusive": "keep as hypothesis",
            }[hold.result]
            self.step(
                "holdout",
                "holdout_check",
                hold.summary,
                decision,
                hypothesis=hypothesis,
                prediction=prediction,
                receipts=hold.receipts,
                data={"event": ev.model_dump(mode="json"), "result": hold.result},
            )
            if hold.result == "refuted":
                ruled_out.append(
                    RuledOut(
                        hypothesis=ev.description,
                        prediction=prediction,
                        result="refuted",
                        reason="holdout normal",
                        evidence=ev,
                        receipts=hold.receipts,
                    )
                )
            elif hold.result in ("consistent", "not_applicable"):
                supported.append(ev)

        root_change = Quantity(value=round(search.final.rel_change * 100, 2), unit="pct", receipt=search.final_receipt)
        impact, decomposition, decomposed = self._impact(focus, seg, search.final, search.final_receipt)

        if supported and explained >= SUPPORTED_MIN_EXPLAINED:
            verdict = Verdict.SUPPORTED_CAUSE
            evidence: EvidenceRef | None = max(supported, key=lambda e: len(e.scope))
        else:
            verdict, evidence = Verdict.HYPOTHESIS, None
        stop_reason = (
            f"explained {explained:.0%} >= {STOP_EXPLAINED:.0%}"
            if explained >= STOP_EXPLAINED
            else f"no candidate left; {1 - explained:.0%} stays unexplained"
        )
        root = RootCause(node=focus, segment=seg, direction=a.direction, evidence=evidence, change_pct=root_change)
        self.step(
            "verdict",
            "verdict",
            verdict.value,
            f"stop: {stop_reason}",
            why="aligned event, holdout not refuted" if evidence else "no aligned event survived the holdout",
        )
        headline = f"{focus_node.label} {a.direction} in {segment_text(seg)}"
        return self._finish(
            verdict,
            observed,
            started,
            queries0,
            headline=headline,
            root=root,
            explained=explained,
            impact=impact,
            decomposition=decomposition,
            decomposed=decomposed,
            ruled_out=ruled_out,
            uncertain=self._uncertain(seg, evidence, explained),
            action=self._action(focus, seg, search.last_level),
        )

    # ------------------------------------------------------------------ helpers
    def _identity_tables(self) -> set[str]:
        out = set()
        for e in self.graph.edges:
            if e.kind is EdgeKind.FORMULA and len(e.sources) == 1:
                for n in (e.target, e.sources[0]):
                    out.update(tables_of(self.graph, n))
        return out

    def _observed(self) -> ObservedChange:
        a = self.anomaly
        rid = a.receipts[0] if a.receipts else None
        change = (a.observed / a.expected - 1) * 100 if a.expected else 0.0
        return ObservedChange(
            node=a.node,
            segment=a.segment,
            observed=Quantity(value=round(a.observed, 6), unit="value", receipt=rid),
            expected=Quantity(value=round(a.expected, 6), unit="value", receipt=rid),
            change_pct=Quantity(value=round(change, 2), unit="pct", receipt=rid),
        )

    def _impact(
        self, focus: str, seg: Segment, cell: Cell, seg_receipt: str
    ) -> tuple[Impact | None, list[Contribution], str | None]:
        hours = window_hours(self.window)
        target = self._decomposition_target(focus)
        decomposition: list[Contribution] = []
        if target is not None:
            out = self.tools.decompose_formula(target, seg, self.window)
            if out is not None:
                decomposition = out.contributions
                self.step(
                    "impact",
                    "decompose_formula",
                    out.summary,
                    "where the change came from",
                    receipts=out.receipts,
                    data={"node": target, "residual": out.residual},
                )
        node = self.graph.node(focus)
        num = self.graph.node(node.numerator) if node.kind is NodeKind.RATIO and node.numerator else node
        lost = cell.deviation / hours
        orders_node = self.graph.node(IMPACT_NODE)
        oseg = {d: v for d, v in seg.items() if d in orders_node.dims}
        rows, receipt = self.runner.query(
            measures_window_sql("fact_orders_hourly", ["orders", "gmv"], self.window, segment_where(oseg)),
            self.as_of,
            purpose=f"AOV in {segment_text(oseg)} for the EUR impact",
        )
        base_orders = float(rows[0]["base_orders"] or 0)
        aov = float(rows[0]["base_gmv"] or 0) / base_orders if base_orders else 0.0
        if num.id in ("orders", "payment_successes"):
            gmv_per_hour = lost * aov
        elif num.unit == "eur":
            gmv_per_hour = lost
        else:
            gmv_per_hour = 0.0
        impact = Impact(
            node=IMPACT_NODE if num.id in ("orders", "payment_successes") else num.id,
            segment=seg,
            hours=hours,
            per_hour=Quantity(value=round(lost, 1), unit=num.unit, receipt=seg_receipt),
            gmv_eur_per_hour=Quantity(value=round(gmv_per_hour, 0), unit="eur", receipt=receipt.id),
            eur_so_far=Quantity(value=round(gmv_per_hour * hours, 0), unit="eur", receipt=receipt.id),
        )
        self.step(
            "impact",
            "counterfactual_impact",
            f"{lost:+.1f} {num.id}/h, EUR {gmv_per_hour:+,.0f}/h, EUR {gmv_per_hour * hours:+,.0f} so far",
            "severity = cumulative EUR impact",
            receipts=[seg_receipt, receipt.id],
        )
        return impact, decomposition, target

    def _decomposition_target(self, focus: str) -> str | None:
        if product_factors(self.graph, self.anomaly.node):
            return self.anomaly.node
        owners = [n for n in self.graph.north_stars() if (f := product_factors(self.graph, n.id)) and focus in f]
        owners.sort(key=lambda n: (n.kind is not NodeKind.ADDITIVE, len(product_factors(self.graph, n.id) or [])))
        return owners[0].id if owners else None

    def _uncertain(self, seg: Segment, evidence: EvidenceRef | None, explained: float) -> list[str]:
        out = []
        if "provider" in seg:
            out.append(f"Whether the fault is inside {seg['provider']} or in our {seg['provider']} integration.")
        if evidence is None:
            out.append(
                "No logged change lines up with the onset; "
                "a provider status entry or a deploy in scope would upgrade this."
            )
        out.append(f"{1 - explained:.0%} of the deviation is outside the root segment.")
        return out

    def _action(self, focus: str, seg: Segment, level: dict[str, list[Cell]]) -> SuggestedAction | None:
        if "provider" in seg:
            others = [c for c in level.get("provider", []) if c.value != seg["provider"] and c.cur_den]
            rest = {k: v for k, v in seg.items() if k != "provider"}
            where = "-".join(rest.values()) or "all"
            if others:
                best = max(others, key=lambda c: c.cur / (c.cur_den or 1))
                provider = seg["provider"]
                return SuggestedAction(
                    text=f"Route {where} payments from {provider} to {best.value} until {provider} recovers."
                )
            return SuggestedAction(text=f"Fail over {where} payments away from {seg['provider']}.")
        return None

    def _finish(
        self,
        verdict: Verdict,
        observed: ObservedChange,
        started: float,
        queries0: int,
        headline: str,
        root: RootCause | None = None,
        explained: float = 0.0,
        impact: Impact | None = None,
        decomposition: list[Contribution] | None = None,
        decomposed: str | None = None,
        ruled_out: list[RuledOut] | None = None,
        uncertain: list[str] | None = None,
        action: SuggestedAction | None = None,
    ) -> Findings:
        return Findings(
            anomaly_id=self.anomaly.id,
            verdict=verdict,
            headline=headline,
            as_of=self.as_of,
            window=self.window,
            observed=observed,
            root=root,
            decomposition=decomposition or [],
            decomposed_node=decomposed,
            impact=impact,
            ruled_out=ruled_out or [],
            uncertain=uncertain or [],
            explained_share=round(max(0.0, min(1.0, explained)), 4),
            unexplained_share=round(1 - max(0.0, min(1.0, explained)), 4),
            trail=self.trail,
            cost=Cost(queries=self.runner.query_count - queries0, seconds=round(time.perf_counter() - started, 3)),
            suggested_action=action,
        )


def investigate(
    graph: Graph, runner: Runner, anomaly: Anomaly, as_of: datetime, on_step: Callable[[TrailStep], None] | None = None
) -> Findings:
    return Investigation(graph, runner, anomaly, as_of, on_step).run()
