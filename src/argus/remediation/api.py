"""Operator routes: list proposals, approve or deny one. Only an authenticated local operator decides.

An operator session is opened from the local machine (`POST /agent/operator/session`): it sets an HttpOnly,
SameSite=Strict cookie and returns a CSRF token. A decision needs that cookie, the token in `X-Argus-CSRF`
and, when the browser sends an Origin, a local or same-host origin. The model has no path to any of this:
it never sees the token and has no HTTP tool. The principal recorded on the decision comes from the session,
never from the request body.
"""

from __future__ import annotations

import ipaddress
import secrets
import threading
from collections.abc import Callable
from time import monotonic
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from argus.agent.types import Decision, ProposalView
from argus.remediation.models import ProposalConflict, ProposalNotFound
from argus.remediation.service import RemediationService

COOKIE = "argus_operator"
CSRF_HEADER = "X-Argus-CSRF"
LOCAL_NAMES = {"localhost"}


def is_local(host: str | None) -> bool:
    if not host:
        return False
    if host in LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    digest: str = Field(min_length=8, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=128)


class OperatorSession(BaseModel):
    principal: str
    csrf_token: str


class OperatorGate:
    """In-memory operator sessions for Mission Control. A restarted server asks for a new session."""

    def __init__(
        self,
        principal: str = "operator",
        allow_client: Callable[[str | None], bool] = is_local,
        *,
        cookie: str = COOKIE,
        cookie_path: str = "/agent",
        session_ttl: int | None = None,
        max_sessions: int = 1024,
    ) -> None:
        self.principal = principal
        self.allow_client = allow_client
        self.cookie = cookie
        self.cookie_path = cookie_path
        self.session_ttl = session_ttl
        self.max_sessions = max_sessions
        self._sessions: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _origin_ok(self, request: Request) -> bool:
        origin = request.headers.get("origin")
        if origin is None:
            return True  # not a browser cross-site request; the cookie and token still apply
        try:
            host = urlsplit(origin).hostname
            own = urlsplit(f"//{request.headers.get('host', '')}").hostname
        except ValueError:
            return False
        return is_local(host) or (host is not None and host == own)

    def open(self, request: Request, response: Response, *, resume: bool = False) -> OperatorSession:
        client = request.client.host if request.client else None
        if not self.allow_client(client) or not self._origin_ok(request):
            raise HTTPException(403, "operator sessions open only from the local machine")
        with self._lock:
            now = monotonic()
            self._prune(now)
            if resume or self.session_ttl is not None:
                existing = self._sessions.get(request.cookies.get(self.cookie, ""))
                if existing is not None:
                    return OperatorSession(principal=self.principal, csrf_token=existing[0])
            if len(self._sessions) >= self.max_sessions:
                if self.session_ttl is not None:
                    raise HTTPException(429, "Too many operator sessions", headers={"Retry-After": "60"})
                del self._sessions[next(iter(self._sessions))]
            sid, token = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
            self._sessions[sid] = (token, now)
        response.set_cookie(
            self.cookie, sid, httponly=True, samesite="strict", path=self.cookie_path, max_age=self.session_ttl
        )
        return OperatorSession(principal=self.principal, csrf_token=token)

    def _prune(self, now: float) -> None:
        if self.session_ttl is not None:
            while self._sessions:
                sid = next(iter(self._sessions))
                if now - self._sessions[sid][1] < self.session_ttl:
                    break
                del self._sessions[sid]

    def active_sessions(self) -> set[str]:
        with self._lock:
            self._prune(monotonic())
            return set(self._sessions)

    def session_id(self, request: Request) -> str | None:
        sid = request.cookies.get(self.cookie, "")
        with self._lock:
            self._prune(monotonic())
            return sid if sid in self._sessions else None

    def check(self, request: Request) -> str:
        self.require_session(request)
        return self.principal

    def require_session(self, request: Request) -> str:
        sid = request.cookies.get(self.cookie, "")
        token = request.headers.get(CSRF_HEADER)
        with self._lock:
            self._prune(monotonic())
            expected = self._sessions.get(sid)
        if expected is None or token is None or not secrets.compare_digest(expected[0].encode(), token.encode()):
            raise HTTPException(403, "an operator session and its CSRF token are required")
        if not self._origin_ok(request):
            raise HTTPException(403, "cross-origin decisions are refused")
        return sid


def create_router(service: RemediationService, gate: OperatorGate | None = None) -> APIRouter:
    gate = gate or OperatorGate()
    routes = APIRouter(tags=["agent actions"])

    @routes.post("/agent/operator/session")
    def open_session(request: Request, response: Response) -> OperatorSession:
        return gate.open(request, response)

    @routes.get("/agent/actions")
    def list_actions() -> list[ProposalView]:
        return service.proposals()

    @routes.get("/agent/actions/{proposal_id}", responses={404: {}})
    def get_action(proposal_id: str) -> ProposalView:
        found = service.get(proposal_id)
        if found is None:
            raise HTTPException(404, f"no action {proposal_id}")
        return found

    def decide(proposal_id: str, body: DecisionBody, request: Request, verb: Literal["approve", "deny"]) -> Any:
        principal = gate.check(request)
        now = service.now()
        if now is None:
            raise HTTPException(409, "the run has not started; there is no simulated time to decide at")
        try:
            return service.decide(
                proposal_id, body.digest, Decision(decision=verb, principal=principal, at=now), body.idempotency_key
            )
        except ProposalNotFound as exc:
            raise HTTPException(404, f"no action {proposal_id}") from exc
        except ProposalConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    @routes.post("/agent/actions/{proposal_id}/approve", responses={403: {}, 404: {}, 409: {}})
    def approve(proposal_id: str, body: DecisionBody, request: Request) -> ProposalView:
        return decide(proposal_id, body, request, "approve")

    @routes.post("/agent/actions/{proposal_id}/deny", responses={403: {}, 404: {}, 409: {}})
    def deny(proposal_id: str, body: DecisionBody, request: Request) -> ProposalView:
        return decide(proposal_id, body, request, "deny")

    return routes
