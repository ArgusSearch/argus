"""Stage-2 investigation: the Stage-1 fixed opening plus a hypothesis ledger, placebo and claim labels.

```
1  freshness       data before business                                  (Stage 1)
2  identities      cross-table identities hold                           (Stage 1)
3  calendar        planned events in the window                          (Stage 1)
4  decompose       exact LMDI walk, hop by hop; follow the largest contribution among factors that
                   moved beyond their week-to-week spread, not just the largest contribution
5  mix vs rate     ratio focus: a mix shift with every segment's rate flat is EXPECTED (Simpson)
6  segment         segment search with the descent rule, inside the anomaly's own segment
7  onset           the root segment's own onset
8  events          log entries attached to the focus node by evidence edges, aligned with the onset
9  hypotheses      one ledger entry per candidate event: prediction first, then the holdout check;
                   an empty holdout falls back to a control group (never counted as support alone)
10 placebo         would the same deviation show up in the same hours of earlier weeks?
11 impact          orders and EUR against the expectation, exact split of the north star
12 planner         only while > 20% stays unexplained: proposed typed checks, judged by the ledger
13 verdict         labelled claims (evidence vs hypothesis), stopping rule, verdict
```

Verdicts: SUPPORTED_CAUSE needs a validated event hypothesis, a significant root and >= 20% explained,
and a validated historical placebo. HYPOTHESIS needs a localised, significant root. Anything else is
UNEXPLAINED with the remainder stated as a number. `investigate()` keeps the Stage-1 signature, so the
runtime can switch to it by changing one import.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from argus.agent.investigate import Case as AgentCase
    from argus.agent.investigate import Selection

from argus.contracts.findings import (
    Anomaly,
    Contribution,
    EvidenceRef,
    Findings,
    Quantity,
    RootCause,
    RuledOut,
    Segment,
    SkepticResult,
    SuggestedAction,
    TrailStep,
    Verdict,
)
from argus.contracts.graph import EdgeKind, Graph, NodeKind
from argus.contracts.tools import HoldoutCheckInput, PlaceboTestInput, ToolOutput
from argus.decompose.segments import Cell
from argus.investigate import claims as cl
from argus.investigate.ledger import TRAIL_KIND, Hypothesis, Ledger, LedgerEntry
from argus.investigate.planner import MAX_PROPOSALS, Planner, PlannerContext
from argus.investigate.playbook import GENERAL_PLAYBOOK, choose_playbook
from argus.investigate.tools import PLACEBO_WEEKS, ProductSplit, StageTwoToolbox
from argus.investigate.walk import (
    FactorView,
    choose_factor,
    decomposition_hops,
    decompositions,
    evidence_logs,
    has_direct_evidence,
    subtree_share,
)
from argus.investigate.weekly import fetch_weekly, week_stat
from argus.investigator.procedure import Investigation, segment_text
from argus.investigator.tools import SearchResult, covers
from argus.semantic.compile import scope_where, segment_where, tables_of
from argus.semantic.runner import Runner
from argus.settings import Settings

AGENT_SOURCE = "agent"  # ledger source of checks the agent chose (argus.agent.investigate)


class EvidenceSelector(Protocol):
    """Chooses and runs the candidate checks before the verdict (the agent seam). `select` returns what the
    verdict rules need; `close` hears the admitted verdict. Without one, Stage 2 runs its fixed checks.

    A selector may also offer `challenge(inv, case, selection, supported) -> Challenge | None` (looked up with
    `getattr`, so this protocol and its implementers stay as they are): it is asked only when the rules would
    admit SUPPORTED_CAUSE, and its answer can only downgrade the verdict, never grant one."""

    def select(self, inv: StageTwoInvestigation, case: AgentCase) -> Selection: ...

    def close(self, inv: StageTwoInvestigation, selection: Selection, admitted: str) -> None: ...


HOUR = timedelta(hours=1)
EVENT_BEFORE = timedelta(hours=3)
EVENT_AFTER = timedelta(hours=1)
SUPPORTED_MIN_EXPLAINED = 0.20
STOP_EXPLAINED = 0.80
ROOT_Z = 3.0
MIX_DOMINANT = 0.67
FLAT_Z = 2.0
PLAN_PREFIX = "planned_"  # plan nodes (planned_spend): a ratio over a plan measures delivery against it
PLAN_KINDS = ("budget_change", "budget_set", "campaign", "promo")
PLAN_EP = 0.67  # the planned event's scope must carry most of the deviation
PLAN_BAND_REL = 0.25  # delivered within +-25% of the planned uplift ...
PLAN_BAND_MIN = 0.05  # ... or within 5 points, whichever is wider
SCOPE_EXCESS_MIN = 0.25  # an unlocalised change counts only if the event's scope carries clearly more than its volume
PROCESS_NOTE = "No hypothesis planner is configured"

DECISION: dict[str, dict[str, str]] = {
    "holdout_check": {
        "validated": "validated: keep as cause",
        "refuted": "refuted: ruled out",
        "inconclusive": "inconclusive: keep as hypothesis",
    },
    "placebo_test": {
        "validated": "validated: the deviation is unusual",
        "refuted": "refuted: deviations like this recur",
        "inconclusive": "inconclusive: not clearly unusual",
    },
}
DEFAULT_DECISION = {
    "validated": "validated: as predicted",
    "refuted": "refuted: contrary to the prediction",
    "inconclusive": "inconclusive",
}


def _z(view: FactorView | None) -> float | None:
    return round(view.z, 2) if view is not None and view.z is not None else None


@dataclass(frozen=True)
class ScopeShare:
    ep: float
    volume_share: float
    excess: float
    receipt: str


def scope_text(scope: dict[str, list[str]]) -> str:
    return " / ".join(f"{d} {', '.join(v)}" for d, v in sorted(scope.items())) or "all segments"


def group_batches(events: list[EvidenceRef]) -> list[EvidenceRef]:
    """Entries of one log with the same kind and timestamp are one rollout (for example a pacer change
    written per budget line): test them as one candidate whose scope is the union of theirs. The union is
    a rectangle per dimension, so it can include combinations no member names; those carry no volume when
    the members cover every line, as a batch rollout does."""
    groups: dict[tuple[str, str, datetime], list[EvidenceRef]] = {}
    for e in events:
        groups.setdefault((e.log, e.kind, e.ts), []).append(e)
    out = []
    for (log, kind, ts), members in groups.items():
        if len(members) == 1:
            out.append(members[0])
            continue
        dims = set.intersection(*(set(m.scope) for m in members))
        scope = {d: sorted({v for m in members for v in m.scope[d]}) for d in sorted(dims)}
        refs = ", ".join(m.ref for m in members)
        out.append(
            EvidenceRef(
                log=log,
                ref=members[0].ref,
                ts=ts,
                kind=kind,
                description=f"{len(members)} {kind}{BATCH_MARK}{ts:%H:%M} ({members[0].description}, ...): {refs}",
                scope=scope,
            )
        )
    return out


BATCH_MARK = " entries at "


def best_ref(event: EvidenceRef | None) -> str:
    return f"{event.description} ({event.ref})" if event is not None else "-"


def is_batch(event: EvidenceRef) -> bool:
    return BATCH_MARK in event.description and ": " in event.description


def pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


class StageTwoInvestigation(Investigation):
    def __init__(
        self,
        graph: Graph,
        runner: Runner,
        anomaly: Anomaly,
        as_of: datetime,
        on_step: Callable[[TrailStep], None] | None = None,
        planner: Planner | None = None,
        selector: EvidenceSelector | None = None,
        settings: Settings | None = None,
    ):
        super().__init__(graph, runner, anomaly, as_of, on_step)
        self.selector = selector
        self.settings = settings or Settings()
        self.thresholds = self.settings.thresholds
        if settings is None:
            self.thresholds = self.thresholds.model_copy(
                update={
                    "supported": SUPPORTED_MIN_EXPLAINED,
                    "stop": STOP_EXPLAINED,
                    "plan_band": PLAN_BAND_REL,
                    "plan_min": PLAN_BAND_MIN,
                }
            )
        self.tools: StageTwoToolbox = StageTwoToolbox(graph, runner, as_of)
        self.ledger = Ledger(self.thresholds.checks)
        self.planner = planner
        self.claims: list[cl.Claim] = []
        self.llm_calls = 0
        self.playbook = choose_playbook(graph, anomaly.node, anomaly.direction)
        if self.playbook.id in self.settings.playbooks.disabled:
            self.playbook = GENERAL_PLAYBOOK
            self.selector = None
        self.flat_volumes: list[RuledOut] = []
        self.walk_split: ProductSplit | None = None
        self.plan_followed: tuple[FactorView, FactorView, list[str]] | None = None

    def step(self, kind: str, tool: str, result: str, decision: str, **extra: object) -> TrailStep:
        """Every trail step carries its named playbook step (`data["playbook"]`), also in the events."""
        raw = extra.pop("data", None)
        data: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
        data["playbook"] = self.playbook.tag(kind, tool, data)
        return super().step(kind, tool, result, decision, data=data, **extra)

    def _playbook_run(self) -> list[dict[str, str]]:
        done = {str(s.data["playbook"]["step"]) for s in self.trail if "playbook" in s.data} | {"verdict"}
        return self.playbook.run_status(done)

    # ------------------------------------------------------------------ main
    def run(self) -> Findings:
        started, queries0 = time.perf_counter(), self.runner.query_count
        a = self.anomaly
        node = self.graph.node(a.node)
        observed = self._observed()
        self.claims.append(
            cl.evidence(
                f"{node.label} moved {observed.change_pct.value:+.2f}% against its expectation "
                f"in {segment_text(a.segment)}.",
                "watcher: robust z against the same hours of 4 prior weeks",
                [observed.change_pct.receipt] if observed.change_pct.receipt else [],
            )
        )

        stop = self._data_checks()
        if stop is not None:
            return self._close(stop, observed, started, queries0, headline=f"{node.label}: {stop[1]}")

        focus, focus_share, significant = self._walk()
        if self.plan_followed is not None:
            reason = self._plan_change_reason(*self.plan_followed)
            return self._close(
                (Verdict.EXPECTED, reason), observed, started, queries0, headline=f"{node.label}: {reason}"
            )
        focus_node = self.graph.node(focus)
        seg0 = {d: v for d, v in a.segment.items() if d in focus_node.dims}

        mix_dim = self._mix_check(focus, seg0) if focus_node.kind is NodeKind.RATIO else None
        if mix_dim is not None:
            return self._close(
                (Verdict.EXPECTED, "mix shift"),
                observed,
                started,
                queries0,
                headline=f"{focus_node.label}: mix shift across {mix_dim}, every {mix_dim}'s own rate is flat",
            )

        search = self.tools.segment_search(focus, self.window, seg0)
        seg = search.output.segment
        localised = seg != seg0
        self.step(
            "segment",
            "segment_search",
            search.output.summary,
            f"root segment {segment_text(seg)}" if localised else "no single segment carries the change",
            receipts=search.output.receipts,
            data={"path": [p.model_dump() for p in search.output.path], "start": seg0},
        )
        root_cell = search.final
        root_z = root_cell.z
        if localised:
            self.claims.append(
                cl.evidence(
                    f"{segment_text(seg)} explains {search.output.explained_share:.0%} of the deviation of "
                    f"{focus} ({pct(root_cell.rel_change)} inside, z {root_z:+.1f}).",
                    "segment_search: descent while the deviation is concentrated",
                    search.output.receipts,
                )
            )

        onset = self._root_onset(focus, seg) if localised else a.onset
        selection = None
        if self.selector is not None:
            # the model chooses the checks; the gate backfills what it skipped (argus.agent.investigate)
            from argus.agent.investigate import Case

            case = Case(
                anomaly=a,
                as_of=self.as_of,
                focus=focus,
                start=seg0,
                segment=seg,
                localised=localised,
                explained_share=search.output.explained_share,
                root_rel=root_cell.rel_change,
                root_z=root_z,
                onset=onset,
                window=self.window,
            )
            selection = self.selector.select(self, case)
            events, supported, ruled_out, placebo = (
                selection.events,
                selection.supported,
                selection.ruled_out,
                selection.placebo,
            )
        else:
            events = self._events(focus, seg, onset)
            supported, ruled_out = self._test_events(events, focus, seg, root_cell.rel_change, onset)
            placebo = self._placebo(focus, seg, a.direction)

        share = max(0.0, min(1.0, focus_share))
        explained = share * search.output.explained_share if localised else 0.0
        best = self._pick(supported, onset) if supported else None
        scope_share = self._scope_share(focus, seg0, seg, best) if best is not None else None
        if scope_share is not None and (localised or scope_share.excess >= SCOPE_EXCESS_MIN):
            explained = max(explained, share * scope_share.ep)
        significant_root = abs(root_z) >= ROOT_Z
        recurring = placebo is not None and placebo.status == "refuted"
        history_validated = placebo is not None and placebo.status == "validated"
        hypothesis = (localised or (significant and focus != a.node)) and significant_root and not recurring
        can_support = best is not None and significant_root and explained >= self.thresholds.supported
        pending_history = best if can_support and not history_validated and not recurring else None
        if can_support and history_validated:
            verdict = Verdict.SUPPORTED_CAUSE
        elif hypothesis:
            verdict = Verdict.HYPOTHESIS
        else:
            verdict = Verdict.UNEXPLAINED
            explained = 0.0
        challenge = None
        if verdict is Verdict.SUPPORTED_CAUSE and selection is not None and best is not None:
            # profile v2 `critic`: a second model tries to break the cause; its rules can only take it away
            challenger = getattr(self.selector, "challenge", None)
            challenge = challenger(self, case, selection, best) if callable(challenger) else None
            if challenge is not None and challenge.downgrade:
                verdict = Verdict.HYPOTHESIS if hypothesis else Verdict.UNEXPLAINED
                explained = explained if hypothesis else 0.0

        impact, decomposition, decomposed = (
            self._impact(focus, seg, root_cell, search.final_receipt)
            if verdict is not Verdict.UNEXPLAINED
            else (None, [], None)
        )
        if self.walk_split is not None and verdict is not Verdict.UNEXPLAINED:
            # report the split the walk actually followed (it may be a ratio identity, not the formula)
            first = self.walk_split.receipts[0] if self.walk_split.receipts else None
            decomposition = [
                Contribution(node=v.node, share=round(v.share, 4), value=round(v.contribution, 4), receipt=first)
                for v in self.walk_split.factors
            ]
            decomposed = a.node
        planner_ruled_out = self._plan(focus, seg, explained, events)
        ruled_out += planner_ruled_out + self.flat_volumes

        evidence = best if verdict is Verdict.SUPPORTED_CAUSE else None
        root = (
            RootCause(
                node=focus,
                segment=seg,
                direction=a.direction,
                evidence=evidence,
                change_pct=self._root_change(root_cell, search.final_receipt),
            )
            if verdict is not Verdict.UNEXPLAINED
            else None
        )
        uncertain = self._uncertain_all(verdict, seg, evidence or pending_history, explained, placebo, events)
        history_reason = ""
        if pending_history is not None:
            history_reason = (
                "the historical placebo check was inconclusive"
                if placebo is not None
                else "the historical placebo check was not run"
            )
            if placebo is None:
                uncertain.append("A validated historical placebo check is required to confirm the cause.")
        if challenge is not None and challenge.downgrade:
            uncertain.append(
                f"Counter-check {challenge.verdict} the supported cause {best_ref(best)}: {challenge.reason}"
            )
        self._cause_claims(verdict, focus, seg, evidence, placebo, impact, uncertain, pending_history)
        headline = self._headline(verdict, focus_node.label, seg, root_cell.rel_change, evidence, a)
        stop_reason = (
            f"explained {explained:.0%} >= {self.thresholds.stop:.0%}"
            if explained >= self.thresholds.stop
            else f"no candidate left; {1 - explained:.0%} stays unexplained"
        )
        self.step(
            "verdict",
            "verdict",
            verdict.value,
            f"stop: {stop_reason}",
            why=(
                f"counter-check {challenge.verdict}: {challenge.reason}"
                if challenge is not None and challenge.downgrade
                else history_reason or self._why(verdict, evidence, significant_root, recurring, localised)
            ),
            data={
                "claims": [c.model_dump() for c in self.claims],
                "ledger": [e.model_dump() for e in self.ledger.entries],
                "explained_share": round(explained, 4),
                "event_scope_share": asdict(scope_share) if scope_share else None,
                "checks_used": len(self.ledger.entries),
                "checks_budget": self.ledger.budget,
                "playbook_run": self._playbook_run(),
            },
        )
        findings = self._finish(
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
            uncertain=uncertain,
            action=self._suggest(verdict, focus, seg, evidence, search),
        )
        if challenge is not None and challenge.verdict != "unavailable":
            findings = findings.model_copy(
                update={"skeptic": SkepticResult(verdict=challenge.verdict, checks=challenge.checks)}
            )
        if self.selector is not None and selection is not None:
            self.selector.close(self, selection, verdict.value)
        return self._with_llm_cost(findings)

    # ------------------------------------------------------------------ 1-3 data before business
    def _data_checks(self) -> tuple[Verdict, str] | None:
        tables = sorted(set(tables_of(self.graph, self.anomaly.node)) | self._identity_tables())
        fresh = self.tools.check_freshness(tables, self.window, self.thresholds.freshness)
        defer = not fresh.ok and self.settings.autonomy.defer_late_data == "alone"
        self.step(
            "freshness",
            "check_freshness",
            fresh.summary,
            "stop: DATA_ISSUE" if defer else "continue",
            receipts=fresh.receipts,
            data={"tables": [t.model_dump(mode="json") for t in fresh.tables]},
        )
        if defer:
            self.claims.append(cl.evidence(f"Source data is incomplete: {fresh.summary}.", "check_freshness"))
            return Verdict.DATA_ISSUE, "source data incomplete"
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
            self.claims.append(
                cl.evidence(f"A cross-table identity is broken: {ident.summary}.", "check_identities", ident.receipts)
            )
            return Verdict.DATA_ISSUE, "identity broken"
        return self._calendar_check() if self.settings.autonomy.hold_alert == "alone" else None

    def _calendar_check(self) -> tuple[Verdict, str] | None:
        """Planned events change the expectation (they never mute a metric): when a calendar entry in force
        plans an uplift for this node, the deviation sits inside its scope and the delivered change is inside
        the planned band, the change is EXPECTED. Delivering far below the plan stays a business finding."""
        a = self.anomaly
        node = self.graph.node(a.node)
        planned, rid = self.tools.planned_events(self.window)
        relevant = [(ev, up[a.node]) for ev, up in planned if a.node in up and covers(ev.scope, a.segment, node.dims)]
        results = []
        for ev, uplift in relevant:
            scope = {d: v for d, v in ev.scope.items() if d in node.dims}
            total, _ = self.tools.cells(a.node, self.window, None, segment_where(a.segment, node.dims))
            where_inside = f"({segment_where(a.segment, node.dims)}) AND ({scope_where(scope)})"
            inside, cell_rid = self.tools.cells(a.node, self.window, None, where_inside)
            if not total or not inside or not total[0].deviation:
                continue
            ep = inside[0].deviation / total[0].deviation
            rel = inside[0].rel_change
            band = max(
                self.thresholds.plan_band * abs(uplift),
                self.thresholds.plan_min,
                2 * self._week_spread(a.node, where_inside),
            )
            if ep >= PLAN_EP and abs(rel - uplift) <= band:
                status = "as planned"
            elif ep >= PLAN_EP and rel * uplift > 0 and abs(rel) < abs(uplift) - band:
                status = "underdelivering its plan"
            else:
                status = "outside its plan"
            results.append((ev, uplift, rel, ep, status, cell_rid))
        text = (
            "; ".join(
                f"{ev.ref}: planned {pct(up)}, delivered {pct(rel)} ({status})" for ev, up, rel, _, status, _ in results
            )
            if results
            else f"{len(planned)} planned event(s) in force, none plans {a.node} in {segment_text(a.segment)}"
        )
        expected = next((r for r in results if r[4] == "as planned"), None)
        self.step(
            "calendar",
            "list_events",
            text,
            f"stop: EXPECTED ({expected[0].ref})" if expected else "continue: not an expected change",
            why="planned events change the expectation; they do not mute the metric",
            receipts=[rid, *(r[5] for r in results)],
            data={
                "planned": [
                    {
                        "event": ev.model_dump(mode="json"),
                        "uplift": up,
                        "delivered": round(rel, 4),
                        "ep": round(ep, 4),
                        "status": status,
                    }
                    for ev, up, rel, ep, status, _ in results
                ]
            },
        )
        for ev, up, rel, _, status, cell_rid in results:
            if status == "underdelivering its plan":
                self.claims.append(
                    cl.evidence(
                        f"{ev.description} ({ev.ref}) is underdelivering: planned {pct(up)}, delivered {pct(rel)}.",
                        "calendar band check",
                        [rid, cell_rid],
                    )
                )
        if expected is None:
            return None
        ev, up, rel, ep, _, cell_rid = expected
        self.claims.append(
            cl.evidence(
                f"Planned: {ev.description} ({ev.ref}) planned {pct(up)} for {a.node}; delivered {pct(rel)}, inside "
                f"the band, and its scope carries {ep:.0%} of the deviation.",
                "calendar band check",
                [rid, cell_rid],
            )
        )
        return Verdict.EXPECTED, f"planned change {ev.ref} delivered {pct(rel)} against a plan of {pct(up)}"

    # ------------------------------------------------------------------ 4 significance-aware LMDI walk
    def _walk(self) -> tuple[str, float, bool]:
        """Returns (focus node, its share of the anomaly's change, whether the choice was significant).

        Every exact product of the anomaly node is split (its formula edge and every ratio identity
        N = D x R). In each split the walk takes the largest contribution among factors that moved beyond
        their week-to-week spread. Across splits it prefers a significant factor, then a factor the graph
        attaches evidence logs to (where a first cause can be checked), then the larger share.
        """
        a = self.anomaly
        node = self.graph.node(a.node)
        options = []
        for d in decompositions(self.graph, a.node):
            common = set(node.dims)
            for f in d.leaves:
                common &= set(self.graph.node(f).dims)
            seg = {k: v for k, v in a.segment.items() if k in common}
            split = self.tools.decompose_product(a.node, d.leaves, seg, self.window)
            if split is not None:
                chosen, significant = choose_factor(split.factors, split.change)
                options.append((d, split, chosen, significant))
        if not options:
            self.step(
                "decompose",
                "decompose_formula",
                f"{a.node} has no formula children",
                f"localise {a.node} directly",
                why="leaf node: the exact split ends here",
            )
            return a.node, 1.0, True
        if self.settings.autonomy.hold_alert == "alone":
            self.plan_followed = self._plan_follow(options)
        d, split, chosen, significant = max(
            options, key=lambda o: (o[3], has_direct_evidence(self.graph, o[2].node), abs(o[2].share))
        )
        receipts = sorted({r for o in options for r in o[1].receipts}, key=lambda r: int(r[1:]))
        if len(options) > 1:
            self.step(
                "decompose",
                "decompose_formula",
                f"{len(options)} exact splits of {a.node}: "
                + "; ".join(f"{o[0].label} -> {o[2].node} {o[2].share:.0%} (z {o[2].z or 0:+.1f})" for o in options),
                f"follow {d.label}",
                why=(
                    "prefer a factor that moved beyond its normal spread, then one the graph attaches logged "
                    f"causes to: {chosen.node} has evidence logs"
                    if has_direct_evidence(self.graph, chosen.node)
                    else "prefer a factor that moved beyond its normal spread, then the larger share"
                ),
                receipts=receipts,
                data={
                    "alternatives": [
                        {
                            "decomposition": o[0].label,
                            "factor": o[2].node,
                            "share": round(o[2].share, 4),
                            "z": _z(o[2]),
                            "significant": o[3],
                            "evidence_attached": has_direct_evidence(self.graph, o[2].node),
                        }
                        for o in options
                    ],
                    "follow": d.label,
                },
            )
        views = split.factors
        shares = {v.node: v.share for v in views}
        by_node = {v.node: v for v in views}
        quiet = [
            v for v in views if v.node != chosen.node and abs(v.share) >= 0.05 and v.z is not None and abs(v.z) < 3
        ]
        why = (
            f"largest contribution among factors that moved beyond their week-to-week spread: "
            f"{chosen.node} {chosen.share:.0%} (z {chosen.z:+.1f})"
            if significant and chosen.z is not None
            else f"no factor moved beyond its week-to-week spread; {chosen.node} only carries the largest share (weak)"
        )
        if quiet:
            why += "; within normal variation: " + ", ".join(f"{v.node} {v.share:.0%} (z {_z(v):+.1f})" for v in quiet)
        path = decomposition_hops(self.graph, a.node, d, chosen.node)
        path_nodes = [a.node, *[h.follow for h in path]]
        for i, hop in enumerate(path):
            children = [
                {"node": c, "share": round(subtree_share(self.graph, c, shares), 4), "z": _z(by_node.get(c))}
                for c in hop.children
            ]
            text = ", ".join(f"{c['node']} {c['share']:.0%}" for c in children)
            self.step(
                "decompose",
                "decompose_formula",
                f"{hop.node} = {' x '.join(hop.children)}: {text}",
                f"follow {hop.follow}",
                why=why if i == len(path) - 1 else f"{hop.follow} contains {chosen.node}",
                receipts=split.receipts,
                data={
                    "hop": i + 1,
                    "node": hop.node,
                    "children": children,
                    "follow": hop.follow,
                    "path": path_nodes,
                    "decomposition": d.label,
                    **(self._factor_data(views, split.residual, a.node, path_nodes) if i == 0 else {}),
                },
            )
        self._rule_out_flat_volumes(options, split)
        claim = f"{chosen.node} carries {chosen.share:.0%} of the change of {a.node} (exact LMDI split, {d.label}" + (
            f", z {chosen.z:+.1f})." if chosen.z is not None else ")."
        )
        self.claims.append(
            cl.evidence(claim, "decompose_formula: LMDI, zero residual", split.receipts)
            if significant
            else cl.hypothesis(
                claim,
                "decompose_formula: largest share, but no factor moved beyond its normal spread",
                "a factor whose move exceeds its week-to-week spread",
                split.receipts,
            )
        )
        self.walk_split = split
        return chosen.node, chosen.share, significant

    def _week_spread(self, node_id: str, where: str) -> float:
        """Relative week-to-week spread of the node's window total in `where` (0 when unknown)."""
        series = fetch_weekly(
            self.graph,
            self.runner,
            self.as_of,
            [node_id],
            self.window,
            where,
            purpose=f"normal week-to-week spread of {node_id} inside the planned scope",
        )[node_id]
        stat = week_stat(series)
        return stat.sd / abs(stat.baseline) if stat is not None and stat.baseline else 0.0

    def _plan_follow(self, options: list[Any]) -> tuple[FactorView, FactorView, list[str]] | None:
        """Delivery that follows a changed plan: in the identity N = plan x ratio the plan factor carries the
        change (significant, >= 67%) while the delivery ratio stays inside its normal spread."""
        for d, split, _, _ in options:
            plan_id, ratio_id = d.top
            if not plan_id.startswith(PLAN_PREFIX) or not d.label.startswith("identity"):
                continue
            by = {v.node: v for v in split.factors}
            plan, ratio = by.get(plan_id), by.get(ratio_id)
            if plan is None or ratio is None or plan.z is None or ratio.z is None:
                continue
            if abs(plan.z) >= ROOT_Z and plan.share >= PLAN_EP and abs(ratio.z) < FLAT_Z:
                return plan, ratio, list(split.receipts)
        return None

    def _plan_change_reason(self, plan: FactorView, ratio: FactorView, receipts: list[str]) -> str:
        """Name the logged change behind the moved plan (budget change or campaign) and file the claim."""
        a = self.anomaly
        node = self.graph.node(a.node)
        out = self.tools.list_events(
            a.onset - EVENT_BEFORE,
            a.hour + EVENT_AFTER,
            logs=["log_ad_budgets", "log_calendar"],
            covering=a.segment,
            node_dims=node.dims,
        )
        planned = [e for e in out.events if e.kind in PLAN_KINDS]
        self.step(
            "events",
            "list_events",
            out.summary + f"; {len(planned)} planned change(s) to the budget or calendar",
            "stop: EXPECTED, delivery follows its plan" if planned else "stop: EXPECTED, the plan moved",
            why=f"{plan.node} {pct(plan.rel_change or 0)} (z {plan.z or 0:+.1f}) carries "
            f"{plan.share:.0%} of the change; "
            f"{ratio.node} {pct(ratio.rel_change or 0)} (z {ratio.z or 0:+.1f}) stays inside its normal spread",
            receipts=[*receipts, *out.receipts],
            data={"planned": [e.model_dump(mode="json") for e in planned]},
        )
        cite = f"; planned by {planned[0].ref}: {planned[0].description}" if planned else ""
        self.claims.append(
            cl.evidence(
                f"{a.node} follows its plan: {plan.node} {pct(plan.rel_change or 0)}, {ratio.node} "
                f"{pct(ratio.rel_change or 0)} (z {ratio.z or 0:+.1f}){cite}.",
                "decompose_formula: identity over the plan",
                [*receipts, *out.receipts],
            )
        )
        return f"delivery follows its plan ({plan.node} {pct(plan.rel_change or 0)}, {ratio.node} flat){cite}"

    def _rule_out_flat_volumes(self, options: list[Any], chosen_split: Any) -> None:
        """A volume factor (additive, e.g. sessions) that stayed inside its normal spread did not drive the
        change: "traffic increased" is refuted with its own numbers."""
        a = self.anomaly
        seen: set[str] = set()
        for _, split, _, _ in options:
            for v in split.factors:
                if v.node in seen or self.graph.node(v.node).kind is not NodeKind.ADDITIVE:
                    continue
                seen.add(v.node)
                if v.z is None or abs(v.z) >= FLAT_Z or v.rel_change is None:
                    continue
                label = self.graph.node(v.node).label.lower()
                reason = f"{label} {pct(v.rel_change)} (z {v.z:+.1f}), within its normal week-to-week spread"
                self.flat_volumes.append(
                    RuledOut(
                        hypothesis=f"a change in {label} drove {a.node}",
                        prediction=f"{v.node} moves with {a.node}, beyond its normal spread",
                        result="refuted",
                        reason=reason,
                        receipts=list(split.receipts),
                    )
                )
                self.claims.append(
                    cl.evidence(f"Not a change in {label}: {reason}.", "decompose_formula: factor z", split.receipts)
                )

    @staticmethod
    def _factor_data(views: list[FactorView], residual: float, node: str, path: list[str]) -> dict[str, Any]:
        return {
            "decomposed": node,
            "path": path,
            "factors": [
                {
                    "node": v.node,
                    "share": round(v.share, 4),
                    "value": round(v.contribution, 4),
                    "z": round(v.z, 2) if v.z is not None else None,
                    "rel_change": round(v.rel_change, 4) if v.rel_change is not None else None,
                }
                for v in views
            ],
            "residual": residual,
        }

    # ------------------------------------------------------------------ 5 mix vs rate
    def _mix_check(self, focus: str, segment: Segment) -> str | None:
        node = self.graph.node(focus)
        outs = {d: self.tools.mix_rate(focus, d, segment, self.window) for d in node.dims if d not in segment}
        mix_dim = next(
            (
                d
                for d, o in outs.items()
                if o.change and o.rates_flat and o.mix / o.change >= MIX_DOMINANT and o.mix * o.change > 0
            ),
            None,
        )
        receipts = sorted({r for o in outs.values() for r in o.receipts}, key=lambda r: int(r[1:]))
        self.step(
            "decompose",
            "mix_rate_split",
            "; ".join(f"{d}: mix {o.mix:+.5f}, rate {o.rate:+.5f}" for d, o in outs.items()),
            f"mix shift across {mix_dim}: EXPECTED" if mix_dim else "rate effect: localise the rate",
            why="a blended rate can move while every segment's own rate stays flat (Simpson's paradox)",
            receipts=receipts,
            data={d: o.model_dump() for d, o in outs.items()},
        )
        if mix_dim is not None:
            self.claims.append(
                cl.evidence(
                    f"The change of {focus} is a mix shift across {mix_dim}: every {mix_dim}'s own rate is flat.",
                    "mix_rate_split: exact midpoint split",
                    outs[mix_dim].receipts,
                )
            )
        return mix_dim

    # ------------------------------------------------------------------ 7 onset, 8 events
    def _root_onset(self, focus: str, seg: Segment) -> datetime:
        a = self.anomaly
        root_onset, rid = self.tools.segment_onset(focus, seg, a.hour, a.direction)
        onset = a.onset
        if root_onset is not None and root_onset < a.onset:
            onset = root_onset
            self.window = self.window.model_copy(update={"start": onset})
        self.step(
            "segment",
            "get_series",
            f"root segment deviates since {onset:%Y-%m-%d %H:%M}"
            + (f", {int((a.onset - onset) / HOUR)} h before the symptom" if onset < a.onset else ""),
            "align evidence with the root onset",
            receipts=[rid],
            data={"onset": onset.isoformat()},
        )
        return onset

    def _events(self, focus: str, seg: Segment, onset: datetime) -> list[EvidenceRef]:
        logs = evidence_logs(self.graph, focus)
        if not logs:
            self.step(
                "events",
                "list_events",
                f"no evidence log is attached to {focus} in the graph",
                "no event to test",
            )
            return []
        out = self.tools.list_events(
            onset - EVENT_BEFORE, onset + EVENT_AFTER, logs=logs, covering=seg, node_dims=self.graph.node(focus).dims
        )
        # batch rollouts become one candidate; most specific scope first, then closest to the onset
        events = sorted(group_batches(out.events), key=lambda e: (-len(e.scope), abs((e.ts - onset).total_seconds())))
        self.step(
            "events",
            "list_events",
            out.summary + f" (logs attached to {focus} and its parts: {', '.join(logs)})",
            f"test {len(events)} candidate(s) as hypotheses" if events else "no aligned event",
            receipts=out.receipts,
            data={"events": [e.model_dump(mode="json") for e in events], "logs": logs},
        )
        return events

    # ------------------------------------------------------------------ 9 hypotheses from events
    def _test_events(
        self, events: list[EvidenceRef], focus: str, seg: Segment, root_rel: float, onset: datetime
    ) -> tuple[list[EvidenceRef], list[RuledOut]]:
        supported: list[EvidenceRef] = []
        ruled_out: list[RuledOut] = []
        exact = {k: [v] for k, v in seg.items()}
        for i, ev in enumerate(events):
            if self.ledger.remaining <= 1:  # keep one check for the placebo
                self.claims.append(
                    cl.hypothesis(
                        f"{len(events) - i} candidate event(s) were not tested (check budget).",
                        "stopping rule: at most 12 checks",
                        "a re-run with a larger budget",
                    )
                )
                break
            confined = ev.scope == exact or all(d in ev.scope and ev.scope[d] == [v] for d, v in seg.items())
            h = Hypothesis(
                statement=f"{ev.description} ({ev.ref}) caused the change",
                prediction=(
                    f"the change is confined to {segment_text(seg) if seg else scope_text(ev.scope)}; "
                    f"where the event did not apply, {focus} is normal"
                    if confined
                    else f"everything in the event's scope moves, not only {segment_text(seg)}"
                ),
                tool="holdout_check",
                input=HoldoutCheckInput(event=ev, node=focus, segment=seg, window=self.window).model_dump(mode="json"),
                expect="consistent",
            )

            def run(hyp: Hypothesis, ev: EvidenceRef = ev) -> ToolOutput:
                return self.tools.holdout_or_control(ev, focus, seg, self.window, root_rel)

            tested = self.ledger.test(h, run)
            assert tested is not None
            entry, out = tested
            self._ledger_step(entry, out, data={"event": ev.model_dump(mode="json")})
            if entry.status == "validated":
                supported.append(ev)
            elif entry.status == "refuted":
                ruled_out.append(
                    RuledOut(
                        hypothesis=ev.description,
                        prediction=h.prediction,
                        result="refuted",
                        reason=entry.summary,
                        evidence=ev,
                        receipts=entry.receipts,
                    )
                )
                self.claims.append(
                    cl.evidence(
                        f"{ev.description} ({ev.ref}) did not cause it: {entry.summary}.",
                        "holdout_check: refuted",
                        entry.receipts,
                    )
                )
        return supported, ruled_out

    def _ledger_step(self, entry: LedgerEntry, out: ToolOutput | None, data: dict[str, Any] | None = None) -> None:
        h = entry.hypothesis
        extra: dict[str, Any] = {"ledger": entry.model_dump()}
        if out is not None:
            extra["output"] = out.model_dump(mode="json")
        self.step(
            TRAIL_KIND.get(h.tool, "holdout"),
            h.tool,
            entry.summary,
            DECISION.get(h.tool, DEFAULT_DECISION)[entry.status],
            hypothesis=h.statement,
            prediction=h.prediction,
            why=f"expected '{h.expect}', the check says '{entry.outcome or 'in between'}' ({h.source})",
            receipts=entry.receipts,
            data={**extra, **(data or {})},
        )

    # ------------------------------------------------------------------ 10 placebo
    def _placebo(self, focus: str, seg: Segment, direction: str) -> LedgerEntry | None:
        h = Hypothesis(
            statement=f"the deviation of {focus} in {segment_text(seg)} is unusual for these hours of the week",
            prediction=f"none of up to {PLACEBO_WEEKS} earlier weeks deviates with |z| >= 3 in the same direction",
            tool="placebo_test",
            input=PlaceboTestInput(node=focus, segment=seg, window=self.window, weeks=PLACEBO_WEEKS).model_dump(
                mode="json"
            ),
            expect="unusual",
        )
        detail: dict[str, Any] = {}

        def run(hyp: Hypothesis) -> ToolOutput:
            out, more = self.tools.placebo_test(
                focus, seg, self.window, PLACEBO_WEEKS, direction=-1.0 if direction == "down" else 1.0
            )
            detail.update(more)
            return out

        tested = self.ledger.test(h, run)
        if tested is None:
            return None
        entry, out = tested
        self._ledger_step(entry, out, data={"placebo": detail})
        return entry

    # ------------------------------------------------------------------ 12 planner
    def _plan(self, focus: str, seg: Segment, explained: float, events: list[EvidenceRef]) -> list[RuledOut]:
        if self.planner is None or explained >= self.thresholds.stop or self.ledger.remaining <= 0:
            return []
        ctx = PlannerContext(
            anomaly=self.anomaly,
            focus=focus,
            segment=seg,
            window=self.window,
            explained_share=round(explained, 4),
            neighbourhood=self._neighbourhood(focus),
            edges=[
                {"id": e.id, "kind": e.kind.value, "target": e.target, "sources": e.sources, "status": e.status.value}
                for e in self.graph.edges
                if e.target == focus or focus in e.sources
            ],
            events=events,
            tried=list(self.ledger.entries),
            budget=min(MAX_PROPOSALS, self.ledger.remaining),
        )
        proposals = self.planner.propose(ctx)[: ctx.budget]
        if self.planner.uses_llm:
            self.llm_calls += 1
        ruled_out: list[RuledOut] = []
        for h in proposals:
            tested = self.ledger.test(h, lambda hyp: self.tools.run(hyp.tool, hyp.input))
            if tested is None:
                break
            entry, out = tested
            self._ledger_step(entry, out)
            if entry.status == "refuted":
                ruled_out.append(
                    RuledOut(
                        hypothesis=h.statement,
                        prediction=h.prediction,
                        result="refuted",
                        reason=entry.summary,
                        receipts=entry.receipts,
                    )
                )
                self.claims.append(
                    cl.evidence(f"Not the case: {h.statement} ({entry.summary}).", f"{h.tool}: refuted", entry.receipts)
                )
            elif entry.status == "validated":
                self.claims.append(
                    cl.evidence(
                        f"Checked and true: {h.statement} ({entry.summary}).", f"{h.tool}: validated", entry.receipts
                    )
                )
            else:
                self.claims.append(
                    cl.hypothesis(
                        f"Open: {h.statement} ({entry.summary}).",
                        f"{h.tool}: inconclusive",
                        f"a {h.tool} result of '{h.expect}'",
                        entry.receipts,
                    )
                )
        return ruled_out

    def _neighbourhood(self, focus: str) -> list[str]:
        out: set[str] = set()
        for e in self.graph.edges:
            if e.kind is EdgeKind.EVIDENCE:
                continue
            if e.target == focus:
                out.update(e.sources)
            if focus in e.sources:
                out.add(e.target)
        out.discard(focus)
        return sorted(out)

    def _scope_share(self, focus: str, seg0: Segment, seg: Segment, event: EvidenceRef) -> ScopeShare | None:
        """Share of the focus node's deviation (and of its volume) that sits inside the event's scope."""
        node = self.graph.node(focus)
        scope = {d: v for d, v in event.scope.items() if d in node.dims}
        total, _ = self.tools.cells(focus, self.window, None, segment_where(seg0, node.dims))
        inside, rid = self.tools.cells(
            focus, self.window, None, f"({segment_where(seg, node.dims)}) AND ({scope_where(scope)})"
        )
        if not total or not inside or not total[0].deviation or not total[0].volume:
            return None
        ep = max(0.0, min(1.0, inside[0].deviation / total[0].deviation))
        volume = inside[0].volume / total[0].volume
        self.claims.append(
            cl.evidence(
                f"The scope of {event.ref} ({scope_text(scope)}) carries {ep:.0%} of the deviation of {focus} "
                f"with {volume:.0%} of its volume.",
                "segment cells inside the event's scope",
                [rid],
            )
        )
        return ScopeShare(ep=round(ep, 4), volume_share=round(volume, 4), excess=round(ep - volume, 4), receipt=rid)

    # ------------------------------------------------------------------ verdict helpers
    @staticmethod
    def _pick(supported: list[EvidenceRef], onset: datetime) -> EvidenceRef:
        """Prefer a single log entry over a grouped rollout, then the most specific scope, then the closest."""
        return min(supported, key=lambda e: (is_batch(e), -len(e.scope), abs((e.ts - onset).total_seconds())))

    @staticmethod
    def _root_change(cell: Cell, receipt: str) -> Quantity:
        return Quantity(value=round(cell.rel_change * 100, 2), unit="pct", receipt=receipt)

    def _uncertain_all(
        self,
        verdict: Verdict,
        seg: Segment,
        evidence: EvidenceRef | None,
        explained: float,
        placebo: LedgerEntry | None,
        events: list[EvidenceRef],
    ) -> list[str]:
        out: list[str] = []
        if verdict is Verdict.UNEXPLAINED:
            out.append("Nothing localises and no logged change explains it; 100% of the deviation stays unexplained.")
        else:
            out += [u for u in self._uncertain(seg, evidence, explained) if not u.startswith("0% ")]
        if placebo is not None and placebo.status == "inconclusive":
            out.append(f"Placebo: {placebo.summary}; the deviation is not clearly unusual.")
        if placebo is not None and placebo.status == "refuted":
            out.append(f"Placebo: {placebo.summary}; deviations like this recur, so it may be noise.")
        if self.planner is None and self.selector is None and explained < self.thresholds.stop:
            out.append(f"{PROCESS_NOTE}, so the remainder was not explored further.")
        return out

    def _cause_claims(
        self,
        verdict: Verdict,
        focus: str,
        seg: Segment,
        evidence: EvidenceRef | None,
        placebo: LedgerEntry | None,
        impact: Any,
        uncertain: list[str],
        pending_history: EvidenceRef | None,
    ) -> None:
        if placebo is not None:
            text = f"Placebo on {focus} in {segment_text(seg)}: {placebo.summary}."
            if placebo.status == "inconclusive":
                self.claims.append(cl.hypothesis(text, "placebo_test", "no hit in the earlier weeks", placebo.receipts))
            else:
                self.claims.append(cl.evidence(text, f"placebo_test: {placebo.outcome}", placebo.receipts))
        cause_entries = [
            e
            for e in self.ledger.entries
            if e.hypothesis.tool == "holdout_check" and e.hypothesis.source in ("graph", AGENT_SOURCE)
        ]
        if verdict is Verdict.SUPPORTED_CAUSE and evidence is not None:
            entry = next((e for e in cause_entries if evidence.ref in e.hypothesis.statement), None)
            self.claims.append(
                cl.evidence(
                    f"{evidence.description} ({evidence.ref}) caused it, logged at {evidence.ts:%Y-%m-%d %H:%M} "
                    f"next to the onset: {entry.summary if entry else 'consistent'}.",
                    "holdout_check: consistent, aligned with the onset",
                    entry.receipts if entry else [],
                )
            )
        elif verdict is Verdict.HYPOTHESIS and pending_history is not None:
            self.claims.append(
                cl.hypothesis(
                    f"{pending_history.description} ({pending_history.ref}) may explain the deviation.",
                    "aligned event with a validated holdout or control check",
                    "a validated historical placebo check",
                )
            )
        elif verdict is Verdict.HYPOTHESIS:
            open_events = [e for e in cause_entries if e.status == "inconclusive"]
            self.claims.append(
                cl.hypothesis(
                    f"A change inside {segment_text(seg)} drives {focus}"
                    + (
                        f"; {', '.join(e.hypothesis.statement for e in open_events)} stays open."
                        if open_events
                        else "; no logged change confirms what it is."
                    ),
                    "segment_search + onset, no validated event",
                    "a provider status entry, deploy or budget change in scope whose holdout check is consistent",
                )
            )
        if impact is not None:
            self.claims.append(
                cl.evidence(
                    f"Impact: {impact.per_hour.value:+,.1f} {impact.node} per hour, "
                    f"EUR {impact.gmv_eur_per_hour.value:+,.0f} per hour.",
                    "counterfactual_impact: against the 4-week expectation",
                    [r for r in (impact.per_hour.receipt, impact.gmv_eur_per_hour.receipt) if r],
                )
            )
        for text in uncertain:
            if not text.startswith(PROCESS_NOTE):
                self.claims.append(cl.Claim(text=text, label="hypothesis", basis="still uncertain"))

    @staticmethod
    def _headline(
        verdict: Verdict, label: str, seg: Segment, rel: float, evidence: EvidenceRef | None, a: Anomaly
    ) -> str:
        if verdict is Verdict.SUPPORTED_CAUSE and evidence is not None:
            where = segment_text(seg) if seg else scope_text(evidence.scope)
            return f"{label} {pct(rel)} in {where}: {evidence.description}"
        if verdict is Verdict.HYPOTHESIS:
            return f"{label} {pct(rel)} in {segment_text(seg)}: cause not confirmed"
        return f"{label} {a.direction}: nothing localises and no logged change lines up"

    @staticmethod
    def _why(
        verdict: Verdict, evidence: EvidenceRef | None, significant: bool, recurring: bool, localised: bool
    ) -> str:
        if verdict is Verdict.SUPPORTED_CAUSE and evidence is not None:
            return f"aligned event {evidence.ref} validated by its holdout or control check; placebo did not recur"
        if recurring:
            return "the placebo test finds deviations like this in earlier weeks"
        if not localised:
            return "no segment carries the change and no factor moved beyond its normal spread"
        if not significant:
            return "the root segment's own deviation is not significant"
        return "localised and significant, but no aligned event survived its check"

    def _suggest(
        self, verdict: Verdict, focus: str, seg: Segment, evidence: EvidenceRef | None, search: SearchResult
    ) -> SuggestedAction | None:
        if verdict is Verdict.UNEXPLAINED:
            return None
        if evidence is not None and evidence.log == "log_deploys":
            # The supported cause is our own change: undo it rather than route around the segment it hit.
            where = segment_text(seg) if seg else scope_text(evidence.scope)
            return SuggestedAction(text=f"Roll back {evidence.ref} for {where} and watch {focus}.")
        return self._action(focus, seg, search.last_level)

    def _close(
        self, stop: tuple[Verdict, str], observed: Any, started: float, queries0: int, headline: str
    ) -> Findings:
        verdict = stop[0]
        self.step(
            "verdict",
            "verdict",
            verdict.value,
            f"stop: {stop[1]}",
            data={
                "claims": [c.model_dump() for c in self.claims],
                "ledger": [e.model_dump() for e in self.ledger.entries],
                "explained_share": 1.0 if verdict is Verdict.EXPECTED else 0.0,
                "checks_used": len(self.ledger.entries),
                "checks_budget": self.ledger.budget,
                "playbook_run": self._playbook_run(),
            },
        )
        return self._with_llm_cost(
            self._finish(
                verdict,
                observed,
                started,
                queries0,
                headline=headline,
                explained=1.0 if verdict is Verdict.EXPECTED else 0.0,
            )
        )

    def _with_llm_cost(self, findings: Findings) -> Findings:
        if not self.llm_calls:
            return findings
        return findings.model_copy(update={"cost": findings.cost.model_copy(update={"llm_calls": self.llm_calls})})


def investigate(
    graph: Graph,
    runner: Runner,
    anomaly: Anomaly,
    as_of: datetime,
    on_step: Callable[[TrailStep], None] | None = None,
    planner: Planner | None = None,
    selector: EvidenceSelector | None = None,
    settings: Settings | None = None,
) -> Findings:
    """Drop-in replacement for `argus.investigator.procedure.investigate` with the Stage-2 layer."""
    return StageTwoInvestigation(graph, runner, anomaly, as_of, on_step, planner, selector, settings).run()
