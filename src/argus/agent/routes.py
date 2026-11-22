"""HTTP routes of the agent (docs/ext/agent.md), outside the C5 `ROUTES` tuple like the narrator and demo routers.

Live sources carry an `AgentService` (`source.agent`). Any other source answers health with `enabled: false`
and an empty activity log, so the web can probe once and hide its panels.

A replay server also carries the demo `Playback` (docs/pitch/agent-scene.md): a request with `run_id` reads the
sealed agent presentation at its clock instead (activity, actions, Ask, receipts), and approve or deny decide its
pending action through the same local operator gate as a live run.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import nullcontext
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from argus.agent.ask import AskScope
from argus.agent.board import DETECTIVE_CAPS, build_board, build_boards, revision_of, run_of
from argus.agent.chain import STAGE2_RUN
from argus.agent.journal import Journal
from argus.agent.provider import ProviderUnavailable
from argus.agent.service import AgentService
from argus.agent.types import (
    BOARD_VERSION,
    FEATURES,
    ActivityRecord,
    Board,
    ProfileName,
    ProposalView,
    ReceiptLink,
    RunSummary,
)
from argus.api.sources import LiveSource, Source
from argus.contracts.events import EventType
from argus.contracts.findings import Incident, Receipt
from argus.demo.agent import AgentView
from argus.demo.bundle import AskAnswer, ReceiptProof, receipt_keys
from argus.demo.playback import ControlError, Playback
from argus.remediation.api import DecisionBody, OperatorGate, OperatorSession

if TYPE_CHECKING:
    from argus.api.public_limits import PublicLimits


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    incident_id: str | None = None
    conversation_id: str | None = None
    request_id: str | None = None


def _service(source: Source) -> AgentService:
    found = getattr(source, "agent", None)
    if isinstance(found, AgentService):
        return found
    reason = "Live investigations require a connected live source." if source.mode == "replay" else "The agent is off."
    return AgentService("off", Journal(stream=source.bus.stream), reason=reason)


def _scope(source: Source) -> AskScope:
    if not isinstance(source, LiveSource):
        raise HTTPException(409, "Ask needs a connected live source.")
    hub = source.bus
    tick = next((e for e in reversed(hub.history) if e.type is EventType.TICK), None)
    if tick is None or hub.state.last_tick is None:
        raise HTTPException(409, "The run has not completed its first hour yet.")
    return AskScope(
        stream=hub.stream,
        through_seq=hub.last_seq,
        as_of=tick.sim_ts,
        latest_hour=hub.state.last_tick.hour,
        graph=source.graph(),
        incidents=source.incidents(),
        # the world the run reads now: after an applied action that is the treated branch, not the factual one
        world=source.runtime.runner.world_path,
        world_revision=source.world_revision(),
        proposals=[p.model_dump(mode="json") for p in source.remediation.proposals()] if source.remediation else [],
    )


def _recorded_runs(activity: Iterable[ActivityRecord]) -> list[RunSummary]:
    """The run summaries of a sealed presentation, from the activity visible at its clock."""
    runs: dict[str, RunSummary] = {}
    for record in activity:
        if record.run_id is None:
            continue
        run = runs.get(record.run_id) or RunSummary(
            run_id=record.run_id,
            kind="ask" if record.stage == "ASK" else "investigate",
            mode="replay",
            sim_ts=record.sim_ts,
            anomaly_id=record.anomaly_id,
            status="running",
        )
        update: dict[str, Any] = {
            "incident_id": run.incident_id or record.incident_id,
            "llm_calls": run.llm_calls + (record.model is not None),
            "tool_calls": run.tool_calls + (record.kind == "tool_result"),
            "input_tokens": run.input_tokens + (record.input_tokens or 0),
            "output_tokens": run.output_tokens + (record.output_tokens or 0),
        }
        if record.kind == "run_finished":
            # the host's closing line carries the run's billed total
            update |= {"status": "done", "usd": record.usd if record.usd is not None else run.usd}
        elif record.model is not None:
            update["usd"] = run.usd + (record.usd or 0)
        runs[record.run_id] = run.model_copy(update=update)
    return list(runs.values())


def _incident_cites(ref: ReceiptLink, incidents: Iterable[Incident], records: Sequence[ActivityRecord]) -> bool:
    for incident in incidents:
        run = run_of(incident, records)
        if (ref.run_id, ref.world_revision) != (run or STAGE2_RUN, revision_of(run, records)):
            continue
        if ref.receipt_id in receipt_keys(incident.findings.model_dump(mode="json")):
            return True
    return False


def router(
    source: Source,
    playback: Playback | None = None,
    operator_gate: OperatorGate | None = None,
    *,
    public_limits: PublicLimits | None = None,
) -> APIRouter:
    routes = APIRouter(prefix="/agent", tags=["agent"])
    off = _service(source)
    gate = None
    if playback is not None and getattr(source, "remediation", None) is None:
        gate = operator_gate or OperatorGate()

    def presentation(run_id: str) -> AgentView:
        if playback is None:
            raise HTTPException(409, "this server plays no agent presentation")
        try:
            return playback.agent_view(run_id)
        except ControlError as exc:
            raise HTTPException(409, str(exc)) from exc

    def proposal(view: AgentView, action_id: str) -> ProposalView:
        found = next((p for p in view.actions if p.id == action_id), None)
        if found is None:
            raise HTTPException(404, f"no action {action_id}")
        return found

    def service() -> AgentService:
        found = getattr(source, "agent", None)
        return found if isinstance(found, AgentService) else off

    def can_read_run(svc: AgentService, request: Request, run_id: str | None) -> bool:
        if public_limits is None or run_id is None:
            return True
        owner = svc.ask_owners.get(run_id)
        return owner is None or public_limits.gate.session_id(request) == owner

    def profile_name(svc: AgentService) -> ProfileName:
        return "v2" if getattr(getattr(svc, "profile", None), "name", None) == "v2" else "v1"

    def live_settings(playback_id: str | None) -> tuple[ProfileName | None, tuple[float, int]]:
        svc = service()
        if playback_id is not None or svc.selector is None:
            return None, DETECTIVE_CAPS
        budget = svc.selector.budget
        return profile_name(svc), (budget.usd, budget.tool_calls)

    def evidence(run_id: str | None) -> tuple[list[ActivityRecord], list[Incident], dict[str, RunSummary]]:
        """What the board reads: the presentation at its clock, or the live journal and the source's incidents."""
        if run_id is not None:
            view = presentation(run_id)
            records = list(view.activity)
            return records, list(view.incidents), {r.run_id: r for r in _recorded_runs(records)}
        svc = service()
        lock = source.runtime.lock if isinstance(source, LiveSource) else nullcontext()
        with lock:
            incidents = source.incidents()
            with svc.journal.lock:
                return list(svc.journal.records), incidents, dict(svc.journal.runs)

    @routes.get("/health")
    def health() -> dict[str, Any]:
        svc = service()
        features = getattr(getattr(svc, "profile", None), "features", ())
        return {
            **svc.health(),
            "profile": profile_name(svc),
            "features": [f for f in FEATURES if f in features],
            "board_version": BOARD_VERSION,
            **({"public_limits": public_limits.status()} if public_limits is not None else {}),
        }

    @routes.get("/boards")
    async def boards(since: int = 0, run_id: str | None = None) -> dict[str, Any]:
        """One board per agent investigation visible now. Boards are recomputed whole and small, so every visible
        board is returned; `next_cursor` is the last activity seq they reflect (poll again when it moves)."""
        records, incidents, runs = await run_in_threadpool(evidence, run_id)
        profile, caps = live_settings(run_id)
        shown = await run_in_threadpool(build_boards, records, incidents, runs, profile=profile, detective_caps=caps)
        return {
            "boards": [b.model_dump(mode="json") for b in shown],
            "next_cursor": max([since, *(b.through_seq for b in shown)]),
        }

    @routes.get("/boards/incident/{incident_id}", responses={404: {}})
    async def incident_board(incident_id: str, run_id: str | None = None) -> Board:
        """The board of one incident; with the agent off it derives from the findings alone (profile stage2)."""
        records, incidents, runs = await run_in_threadpool(evidence, run_id)
        incident = next((i for i in incidents if i.id == incident_id), None)
        if incident is None:
            raise HTTPException(404, f"no incident {incident_id}")
        agent_run = run_of(incident, records)
        run = runs.get(agent_run) if agent_run is not None else None
        profile, caps = live_settings(run_id)
        return await run_in_threadpool(
            build_board,
            records,
            None,
            run,
            incident=incident,
            run_id=agent_run,
            profile=profile if agent_run is not None else None,
            detective_caps=caps,
        )

    @routes.get("/activity")
    async def activity(request: Request, since: int = 0, run_id: str | None = None) -> dict[str, Any]:
        if run_id is not None:
            shown = [r for r in presentation(run_id).activity if r.seq > since]
            return {
                "stream": f"demo:{run_id}",
                "mode": "replay",
                "records": [r.model_dump(mode="json") for r in shown],
                "next_cursor": shown[-1].seq if shown else since,
            }
        svc = service()
        records = svc.journal.since(since)
        return {
            "stream": source.bus.stream,
            "mode": svc.mode,
            "records": [r.model_dump(mode="json") for r in records if can_read_run(svc, request, r.run_id)],
            "next_cursor": records[-1].seq if records else since,
        }

    @routes.get("/runs")
    async def runs(request: Request, run_id: str | None = None) -> list[RunSummary]:
        if run_id is not None:
            return _recorded_runs(presentation(run_id).activity)
        svc = service()
        with svc.journal.lock:
            return [run for run in svc.journal.runs.values() if can_read_run(svc, request, run.run_id)]

    @routes.post("/ask")
    async def ask(body: AskBody, request: Request, run_id: str | None = None) -> dict[str, Any]:
        if run_id is not None:
            answer: AskAnswer = presentation(run_id).ask(body.question, body.incident_id, body.conversation_id)
            return answer.model_dump(mode="json")
        svc = service()
        if not svc.enabled:
            raise HTTPException(409, svc.reason)
        with public_limits.ask_slot() if public_limits is not None else nullcontext():
            owner = await run_in_threadpool(public_limits.admit_ask, request) if public_limits is not None else None
            scope = await run_in_threadpool(_scope, source)
            cursor = svc.journal.records[-1].seq if svc.journal.records else 0
            try:
                result = await run_in_threadpool(
                    svc.ask, body.question, scope, body.incident_id, body.conversation_id, owner=owner
                )
            except ProviderUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
        if result.status == "unknown_conversation":
            raise HTTPException(404, result.reason or "unknown conversation")
        return result.to_json(cursor)

    if getattr(source, "remediation", None) is None:  # otherwise lane C's operator router serves /agent/actions

        @routes.get("/actions")
        async def actions(run_id: str | None = None) -> list[ProposalView]:
            return presentation(run_id).actions if run_id is not None else []

        @routes.get("/actions/{action_id}", responses={404: {}})
        async def action(action_id: str, run_id: str | None = None) -> ProposalView:
            if run_id is None:
                raise HTTPException(404, f"no action {action_id}")
            return proposal(presentation(run_id), action_id)

    if gate is not None and playback is not None:
        # the presentation's approval takes the same local operator session as a live run's (docs/ext/remediation.md)
        @routes.post("/operator/session")
        def open_session(request: Request, response: Response) -> OperatorSession:
            return gate.open(request, response)

        async def decide(
            action_id: str, body: DecisionBody, request: Request, run_id: str | None, verb: Literal["approve", "deny"]
        ) -> ProposalView:
            gate.check(request)
            if run_id is None:
                raise HTTPException(404, f"no action {action_id}")
            proposal(presentation(run_id), action_id)
            try:
                playback.decide(run_id, action_id, verb, body.digest, body.idempotency_key)
            except ControlError as exc:
                raise HTTPException(409, str(exc)) from exc
            return proposal(presentation(run_id), action_id)

        @routes.post("/actions/{action_id}/approve", responses={403: {}, 404: {}, 409: {}})
        async def approve(
            action_id: str, body: DecisionBody, request: Request, run_id: str | None = None
        ) -> ProposalView:
            return await decide(action_id, body, request, run_id, "approve")

        @routes.post("/actions/{action_id}/deny", responses={403: {}, 404: {}, 409: {}})
        async def deny(action_id: str, body: DecisionBody, request: Request, run_id: str | None = None) -> ProposalView:
            return await decide(action_id, body, request, run_id, "deny")

    @routes.get("/receipts/{run_id}/{world_revision}/{receipt_id}", response_model=None)
    async def receipt(run_id: str, world_revision: str, receipt_id: str, request: Request) -> Receipt | ReceiptProof:
        ref = ReceiptLink(run_id=run_id, world_revision=world_revision, receipt_id=receipt_id)
        if (presented := request.query_params.get("run_id")) is not None:
            view = presentation(presented)
            proof = view.receipts.get(ref.key())
            # a board cites the investigation's C4 receipts qualified with its run; the presentation releases them
            # under their bare ids (only what the visible findings reference)
            if (
                proof is None
                and ref.receipt_id in view.receipts
                and _incident_cites(ref, view.incidents, view.activity)
            ):
                proof = view.receipts[ref.receipt_id]
            if proof is None:
                raise HTTPException(404, f"no released receipt {ref.key()}")
            return proof
        if not can_read_run(service(), request, run_id):
            raise HTTPException(404, "No receipt found.")
        return await run_in_threadpool(live_receipt, ref)

    def live_receipt(ref: ReceiptLink) -> Receipt:
        svc = service()
        receipt_id = ref.receipt_id
        if svc.store is not None:
            ctx = svc.store.context_for(source.bus.stream, ref, through_seq=source.bus.last_seq, as_of=datetime.max)
            if ctx is not None:
                found = svc.store.inspect_receipt(ctx, ref)
                if found is not None:
                    return found
        remediation = getattr(source, "remediation", None)
        if remediation is not None and (found := remediation.receipt(ref)) is not None:
            return found
        # an investigation run cites the runtime's own receipts: serve only those it cited, in its revision
        if svc.journal.cited(ref) and (found := source.receipt(receipt_id)) is not None:
            return found
        # a board cites the C4 receipts of an incident's findings (also the C5 /receipts route serves those)
        if _incident_cites(ref, source.incidents(), svc.journal.since(0)):
            found = source.receipt(receipt_id)
            if found is not None:
                return found
        raise HTTPException(404, f"no receipt {ref.key()}")

    return routes
