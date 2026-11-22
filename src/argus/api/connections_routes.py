"""Local operator routes for connector status and credential changes."""

from __future__ import annotations

import json
from collections import deque
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from argus.connectors import plausible, stripe
from argus.connectors.provider import PROVIDERS, ProviderError, ProviderId
from argus.connectors.service import ConnectionBusy, Connections, Status
from argus.connectors.vault import Credentials
from argus.remediation.api import CSRF_HEADER, OperatorGate, OperatorSession, is_local

NO_STORE = {"Cache-Control": "no-store"}


class RateLimit:
    """Bound attempts across sessions so re-opening a session cannot bypass the provider budget."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {"access": deque(), "sync": deque()}
        self._lock = Lock()

    def check(self, operation: str, maximum: int) -> None:
        now = monotonic()
        with self._lock:
            events = self._events[operation]
            while events and events[0] <= now - 60:
                events.popleft()
            if len(events) >= maximum:
                raise HTTPException(
                    429, "Too many connection requests. Try again shortly.", headers={**NO_STORE, "Retry-After": "60"}
                )
            events.append(now)


def local_only(request: Request) -> None:
    # Never accept a proxied public request even when the HTTP server sees a loopback peer.
    if any(header in request.headers for header in ("cf-connecting-ip", "forwarded", "x-forwarded-for")):
        raise HTTPException(403, "Connections require the local Argus API.", headers=NO_STORE)
    try:
        authority = request.headers.get("host", "")
        host = urlsplit(f"//{authority}").hostname
        origin = request.headers.get("origin")
        if origin is not None and origin not in {f"http://{authority}", f"https://{authority}"}:
            raise HTTPException(403, "Cross-origin connections are refused.", headers=NO_STORE)
    except ValueError:
        host = None
    if not is_local(host) or not (request.client and is_local(request.client.host)):
        raise HTTPException(403, "Connections require the local Argus API.", headers=NO_STORE)


async def credentials(request: Request, provider: ProviderId) -> Credentials:
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise HTTPException(415, "Send the key and connection settings as JSON.", headers=NO_STORE)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 4096:
            raise HTTPException(413, "Connection settings are too large.", headers=NO_STORE)
        raw.extend(chunk)
    try:
        payload = json.loads(raw)
    except (UnicodeError, ValueError, RecursionError):
        raise HTTPException(422, "Enter an API key and connection settings.", headers=NO_STORE) from None
    if not isinstance(payload, dict) or set(payload) != {"key", "target"}:
        raise HTTPException(422, "Enter an API key and connection settings.", headers=NO_STORE)
    key, target = payload["key"], payload["target"]
    if not isinstance(key, str) or not 1 <= len(key) <= 512 or not all(33 <= ord(char) <= 126 for char in key):
        raise HTTPException(422, "Enter a valid API key.", headers=NO_STORE)
    if not isinstance(target, str) or target == key:
        raise HTTPException(422, "Enter valid connection settings.", headers=NO_STORE)
    try:
        if provider == "plausible":
            target = plausible.site_id(target)
        else:
            stripe.validate_key(key)
            target = stripe.currency_code(target)
    except ProviderError as err:
        raise HTTPException(422, str(err), headers=NO_STORE) from None
    return Credentials.model_validate({"key": key, "target": target})


def create_router(connections: Connections) -> APIRouter:
    router = APIRouter(prefix="/connections", tags=["Connections"], dependencies=[Depends(local_only)])
    gate = OperatorGate(cookie="argus_connections", cookie_path="/connections")
    rate = RateLimit()

    def authorize(request: Request, response: Response) -> None:
        if not request.headers.get(CSRF_HEADER, "").isascii():
            raise HTTPException(403, "An operator session and its CSRF token are required.", headers=NO_STORE)
        gate.check(request)
        rate.check("access", 60)
        response.headers.update(NO_STORE)

    protected = [Depends(authorize)]

    @router.post("/operator/session")
    def open_session(request: Request, response: Response) -> OperatorSession:
        rate.check("access", 60)
        response.headers.update(NO_STORE)
        return gate.open(request, response, resume=True)

    @router.get("", dependencies=protected)
    def list_connections() -> list[Status]:
        return [connections.status(provider) for provider in PROVIDERS]

    @router.get("/{provider}", dependencies=protected)
    def get_connection(provider: ProviderId) -> Status:
        return connections.status(provider)

    @router.post("/{provider}/connect", dependencies=protected)
    async def connect(provider: ProviderId, request: Request) -> Status:
        rate.check("sync", 8)
        new = await credentials(request, provider)
        try:
            return await run_in_threadpool(connections.sync, provider, new)
        except ConnectionBusy:
            raise HTTPException(409, "A test is already running for this provider.", headers=NO_STORE) from None

    @router.post("/{provider}/test", dependencies=protected)
    def test(provider: ProviderId) -> Status:
        rate.check("sync", 8)
        try:
            return connections.sync(provider)
        except ConnectionBusy:
            raise HTTPException(409, "A test is already running for this provider.", headers=NO_STORE) from None

    @router.post("/{provider}/disconnect", dependencies=protected)
    def disconnect(provider: ProviderId) -> Status:
        try:
            return connections.disconnect(provider)
        except ConnectionBusy:
            raise HTTPException(409, "Wait for the test to finish before disconnecting.", headers=NO_STORE) from None

    return router
