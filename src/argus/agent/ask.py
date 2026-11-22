"""Ask Argus: a question answered with the same read tools, every figure a verified claim.

The run gets its own `RunContext` (kind "ask"), its own read-only runner and receipt namespace, and a
session in lane B's `EvidenceStore` bound to what the stream has shown so far. The model reads with the
store's tools and finishes with `answer`: prose without digits plus claims that cite fact handles. The host
verifies each claim (`EvidenceStore.verify` re-derives its value from the receipts) and renders the figures;
a claim that does not verify is dropped, and prose with a digit is sent back once. A chat message can never
approve or execute an action.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from argus.agent import prompts
from argus.agent.journal import Journal
from argus.agent.numbers import FactBook, check, scrub, scrub_answer
from argus.agent.provider import LOOP_MODEL, ProviderUnavailable, SpendLedger, call_model
from argus.agent.types import (
    AgentMode,
    ClaimDraft,
    LlmClient,
    LlmRequest,
    ReceiptLink,
    Rejection,
    RunContext,
    RunSummary,
    VerifiedClaim,
)
from argus.connectors.data import SourceData
from argus.contracts.findings import Incident
from argus.contracts.graph import Graph
from argus.evidence import EvidenceStore
from argus.semantic.runner import Runner

ANSWER = "answer"
MAX_REQUESTS = int(os.environ.get("ARGUS_ASK_MAX_REQUESTS", 6))
MAX_TOOL_CALLS = int(os.environ.get("ARGUS_ASK_MAX_TOOL_CALLS", 8))
MAX_USD = float(os.environ.get("ARGUS_ASK_MAX_USD", 0.25))
MAX_RESULT_CHARS = 5000

ANSWER_TOOL = {
    "name": ANSWER,
    "description": "Finish with the answer. `text` is plain prose WITHOUT digits; every figure goes into a claim "
    "that cites one fact id from a tool result (fact_handles[].id). The host renders the figures with their "
    "receipts and drops any claim it cannot verify.",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "the answer in a few sentences, no digits"},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fact_id": {"type": "string"},
                        "wording": {"type": "string", "description": "what the figure shows, no digits"},
                    },
                    "required": ["fact_id", "wording"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["text", "claims"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class AskScope:
    """What the asking human can see: the stream prefix, its clock and the source's state."""

    stream: str
    through_seq: int
    as_of: datetime
    latest_hour: datetime
    graph: Graph
    incidents: list[Incident]
    world: Any  # path of the world the runner opens read-only
    proposals: list[dict[str, Any]] = field(default_factory=list)  # ProposalView JSON, visible to the human
    world_revision: str = "factual"  # the branch `world` is: an applied action switches the run to its branch
    source_data: SourceData | None = None
    source_clocks: dict[str, tuple[datetime, datetime]] = field(default_factory=dict)


@dataclass
class AskResult:
    status: str  # answered | refused | unavailable
    run_id: str
    answer: str = ""
    claims: list[VerifiedClaim] = field(default_factory=list)
    receipt_links: list[ReceiptLink] = field(default_factory=list)
    reason: str | None = None
    usd: float = 0.0
    conversation_id: str | None = None

    def to_json(self, cursor: int) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "answer": self.answer,
            "claims": [c.model_dump(mode="json") for c in self.claims],
            "receipt_links": [r.model_dump(mode="json") for r in self.receipt_links],
            "reason": self.reason,
            "usd": self.usd,
            "activity_cursor": cursor,
        }


def case_view(incident: Incident) -> dict[str, Any]:
    """An incident as Ask context: what, where, when, the named cause and what was ruled out."""
    f = incident.findings
    evidence = f.root.evidence if f.root else None
    return {
        "id": incident.id,
        "title": incident.title,
        "verdict": incident.verdict.value,
        "state": incident.state.value,
        "root_node": incident.root_node,
        "segment": incident.segment,
        "window": f.window.model_dump(mode="json"),
        "cause": evidence.model_dump(mode="json") if evidence else None,
        "ruled_out": [r.evidence.ref if r.evidence else r.hypothesis for r in f.ruled_out],
        "suggested_action": f.suggested_action.text if f.suggested_action else None,
    }


def fact_draft(store: EvidenceStore, ctx: RunContext, fact_id: str, wording: str) -> ClaimDraft | None:
    """The claim a fact handle carries, built from the fact itself (subject, segment, window, kind)."""
    session = store._session(ctx)
    if session is None:
        return None
    entry = session.facts.get(fact_id)
    if entry is None:
        return None
    call, index = entry
    fact = call.facts[index]
    return ClaimDraft(
        kind=fact.kind,
        subject=fact.subject,
        segment=fact.segment,
        window=fact.window,
        fact_ids=[fact_id],
        text=re.sub(r"\d", "", wording),
    )


class AskRunner:
    def __init__(
        self,
        client: LlmClient,
        journal: Journal,
        store: EvidenceStore,
        mode: AgentMode = "live",
        spend: SpendLedger | None = None,
        model: str = LOOP_MODEL,
    ) -> None:
        self.client = client
        self.journal = journal
        self.store = store
        self.mode = mode
        self.spend = spend or SpendLedger(path=None)
        self.model = model
        self.tools = [
            {"name": s.name, "description": s.description, "input_schema": s.input_schema} for s in store.specs("ask")
        ] + [ANSWER_TOOL]

    def ask(
        self,
        question: str,
        scope: AskScope,
        incident_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> AskResult:
        run_id = self.journal.new_run_id()
        ctx = RunContext(
            run_id=run_id,
            stream=scope.stream,
            through_seq=scope.through_seq,
            world_revision=scope.world_revision,
            as_of=scope.as_of,
            incident_id=incident_id,
            kind="ask",
            mode=self.mode,
        )
        self.journal.start_run(
            RunSummary(
                run_id=run_id, kind="ask", mode=self.mode, sim_ts=scope.as_of, incident_id=incident_id, status="running"
            )
        )
        self.journal.add(
            "chat_question", "ASK", scope.as_of, run_id, actor="operator", text=question[:500], incident_id=incident_id
        )
        runner = Runner(scope.world, receipt_prefix="q")
        runner.source_data = scope.source_data
        result = AskResult(status="unavailable", run_id=run_id)
        try:
            self.store.bind(
                ctx,
                graph=scope.graph,
                runner=runner,
                latest_hour=scope.latest_hour,
                incidents=scope.incidents,
                source_clocks=scope.source_clocks,
            )
            result = self._loop(ctx, question, scope, history or [])
        except ProviderUnavailable as exc:
            result.reason = f"the model is unavailable: {exc}"
        except Exception as exc:  # the provider SDK raises its own types; an answer must not crash the API
            result.reason = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            runner.close()
        usage = [u for u in self.journal.usage if u.run_id == run_id]
        result.usd = round(sum(u.usd or 0.0 for u in usage), 6)
        self.journal.add(
            "chat_answer",
            "ASK",
            scope.as_of,
            run_id,
            actor="host",
            text=result.answer or (result.reason or "no answer"),
            incident_id=incident_id,
            receipt_links=result.receipt_links,
            usd=result.usd,
        )
        self.journal.finish_run(
            run_id,
            status="done" if result.status == "answered" else "failed",
            stop_reason=result.reason or result.status,
            llm_calls=len(usage),
            tool_calls=sum(1 for r in self.journal.records if r.run_id == run_id and r.kind == "tool_result"),
            input_tokens=sum(u.input_tokens + u.cache_read_tokens + u.cache_write_tokens for u in usage),
            output_tokens=sum(u.output_tokens for u in usage),
            usd=result.usd,
        )
        if self.mode in ("live", "record"):
            self.spend.append_run(run_id, "ask", usage)
        return result

    def _loop(self, ctx: RunContext, question: str, scope: AskScope, history: list[dict[str, Any]]) -> AskResult:
        earlier = (
            "Earlier in this conversation (context only; re-check any figure you use):\n<data>\n"
            + json.dumps([{"question": t["question"], "answer": t["answer"]} for t in history[-4:]], indent=1)
            + "\n</data>\n"
            if history
            else ""
        )
        scope_line = (
            f"Data is complete through the data hour {scope.latest_hour:%Y-%m-%d %H:%M}. Every window must end at or "
            "before that hour and span 1 to 48 whole hours; times are UTC without a zone. Segments use the "
            "metric's own dimensions.\n"
        )
        if scope.source_clocks:
            available = [
                f"{node.id} ({node.label}; dimensions: {', '.join(node.dims) or 'none'}; "
                f"latest date: {scope.source_clocks[node.source][1]:%Y-%m-%d})"
                for node in scope.graph.nodes
                if node.source in scope.source_clocks
            ]
            scope_line += (
                "Imported metrics use daily provider reporting dates at 00:00. "
                "Use get_series, segment_search, or placebo_test with those dates. "
                "The simulator clock above applies to shop metrics. "
                "Plausible visitor counts are distinct per day.\n<data>\n" + "\n".join(available) + "\n</data>\n"
            )
        if ctx.incident_id:
            scope_line += f"The question is about incident {ctx.incident_id}.\n"
        cases = [i for i in scope.incidents if i.id == ctx.incident_id] or scope.incidents[-3:]
        if cases:
            scope_line += (
                "Incidents Argus filed (context; re-measure any figure you cite):\n<data>\n"
                + json.dumps([case_view(i) for i in cases], indent=1, default=str)
                + "\n</data>\n"
            )
        if scope.proposals:
            actions = [
                {
                    "id": p.get("id"),
                    "state": p.get("state"),
                    "incident": p.get("incident_ref"),
                    "action": p.get("action"),
                    "approve_by": p.get("expires_at"),  # the last hour a human can approve it
                    "takes_effect_at": p.get("effective_at"),  # the next budget day after approval
                    "success_rule": p.get("success_rule"),
                }
                for p in scope.proposals
            ]
            scope_line += (
                "Actions Argus proposed (a human decides them in the actions panel; you cannot):\n<data>\n"
                + json.dumps(actions, indent=1)
                + "\n</data>\n"
            )
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": f"It is {scope.as_of:%Y-%m-%d %H:%M} (simulated).\n{scope_line}{earlier}"
                f"Question:\n<data>\n{question}\n</data>",
            }
        ]
        calls = 0
        retried = False
        nudged = False
        seen = FactBook()  # numbers the conversation has seen with receipts, for the activity log
        for round_ in range(1, MAX_REQUESTS + 1):
            usage = [u for u in self.journal.usage if u.run_id == ctx.run_id]
            if sum(u.usd or 0.0 for u in usage) >= MAX_USD or any(u.usd is None for u in usage):
                break
            request = LlmRequest(
                model=self.model,
                system=prompts.ASK,
                tools=self.tools,
                messages=messages,
                max_tokens=1500,
                key=f"ask:{ctx.run_id}:{round_}",
            )
            response, _ = call_model(self.client, request, self.journal, ctx.run_id, round_)
            if response.stop_reason == "refusal":
                return AskResult(status="refused", run_id=ctx.run_id, reason="the model declined the question")
            messages.append({"role": "assistant", "content": response.content})
            results: list[dict[str, Any]] = []
            for block in response.content:
                if block.get("type") == "text" and str(block.get("text", "")).strip():
                    self.journal.add(
                        "thought",
                        "ASK",
                        ctx.as_of,
                        ctx.run_id,
                        actor="model",
                        text=scrub(str(block["text"]).strip(), seen),
                        model=response.model,
                    )
                if block.get("type") != "tool_use":
                    continue
                name, args = str(block["name"]), dict(block.get("input") or {})
                if name == ANSWER:
                    answered = self._answer(ctx, args, retried)
                    if answered is not None:
                        return answered
                    retried = True
                    content = json.dumps({"error": "the text contains digits; put every figure into a claim"})
                    results.append(
                        {"type": "tool_result", "tool_use_id": block["id"], "content": content, "is_error": True}
                    )
                    continue
                if calls >= MAX_TOOL_CALLS:
                    content = json.dumps({"error": f"tool budget spent: call {ANSWER}"})
                    results.append(
                        {"type": "tool_result", "tool_use_id": block["id"], "content": content, "is_error": True}
                    )
                    continue
                calls += 1
                self.journal.add("tool_call", "ACT", ctx.as_of, ctx.run_id, actor="model", tool=name, args=args)
                obs = self.store.dispatch(ctx, name, args)
                seen.add({"summary": obs.summary, "data": obs.data}, [r.receipt_id for r in obs.receipt_refs])
                self.journal.add(
                    "tool_result",
                    "OBSERVE",
                    ctx.as_of,
                    ctx.run_id,
                    text=obs.summary,
                    tool=name,
                    observation=obs,
                    receipt_links=obs.receipt_refs,
                )
                reply = {
                    "summary": obs.summary,
                    "availability": obs.availability,
                    "outcome": obs.outcome,
                    "data": obs.data,
                    "fact_handles": [
                        {"id": f.id, "label": f.label, "value": f.value, "unit": f.unit} for f in obs.fact_handles
                    ],
                }
                text = json.dumps(reply, separators=(",", ":"), default=str)
                if len(text) > MAX_RESULT_CHARS:
                    reply["data"] = {"truncated": True}
                    text = json.dumps(reply, separators=(",", ":"), default=str)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": text,
                        "is_error": obs.availability in ("rejected", "error"),
                    }
                )
            if not results:
                if nudged:
                    break
                nudged = True  # the model wrote its answer as text: ask once for the answer tool
                messages.append(
                    {
                        "role": "user",
                        "content": f"Call {ANSWER} with that answer: prose without digits, figures as claims.",
                    }
                )
                continue
            messages.append({"role": "user", "content": results})
        return AskResult(status="unavailable", run_id=ctx.run_id, reason="no answer within the budget")

    def _answer(self, ctx: RunContext, args: dict[str, Any], retried: bool) -> AskResult | None:
        text = str(args.get("text", "")).strip()
        masked = scrub_answer(text)
        if masked != text and not retried:
            return None
        verified: list[VerifiedClaim] = []
        lines = []
        for claim in args.get("claims") or []:
            draft = fact_draft(self.store, ctx, str(claim.get("fact_id", "")), str(claim.get("wording", "")))
            if draft is None:
                continue
            outcome = self.store.verify(ctx, draft)
            if isinstance(outcome, Rejection):
                self.journal.add(
                    "rejected", "VERIFY", ctx.as_of, ctx.run_id, text=f"{outcome.reason}: {outcome.detail}"
                )
                continue
            verified.append(outcome)
            wording = re.sub(r"\d", "", str(claim.get("wording", ""))).strip()
            lines.append(f"- {wording}: {outcome.display}" if wording else f"- {outcome.display}")
        answer = masked + ("\n\n" + "\n".join(lines) if lines else "")
        facts = FactBook()
        for c in verified:
            facts.add({"value": c.value, "display": c.display}, [r.receipt_id for r in c.receipts])
        checked = check(answer, facts)
        if not checked.ok:
            self.journal.add("rejected", "VERIFY", ctx.as_of, ctx.run_id, text=checked.problems())
            if not retried:
                return None
        if not checked.ok or (masked != text and not verified):
            return AskResult(status="refused", run_id=ctx.run_id, reason="The answer's figures could not be verified.")
        links = [r for c in verified for r in c.receipts]
        return AskResult(status="answered", run_id=ctx.run_id, answer=answer, claims=verified, receipt_links=links)
