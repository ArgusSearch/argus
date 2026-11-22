"""Operator-scoped settings, with a private store for each public simulator session."""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path
from time import monotonic
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from argus.api.sources import Source
from argus.narrator.playbooks import playbook_registry
from argus.notifications import DeliveryError, check_url, send_email, send_https
from argus.remediation.api import OperatorGate, OperatorSession
from argus.settings import (
    DataSources,
    Notifications,
    Playbooks,
    Section,
    Settings,
    SettingsConflict,
    SettingsStore,
    secret_fields,
)

Area = Literal[
    "autonomy",
    "playbooks",
    "thresholds",
    "budgets",
    "quiet-hours",
    "channels",
    "sources",
    "ai",
    "notifications",
    "appearance",
    "account",
]
MAX_BODY = 32 * 1024
COOKIE = "argus_settings_operator"
PREFIX = "/settings"


def public_settings(settings: Settings) -> dict[str, Any]:
    payload = settings.model_dump(mode="json")
    for key, section in settings:
        for field, raw in secret_fields(section).items():
            del payload[key][field]
            payload[key][f"{field}_configured"] = raw is not None
    return payload


def envelope(revision: int, settings: Settings, undoable: tuple[str, ...], simulator: bool) -> dict[str, Any]:
    return {"revision": revision, "settings": public_settings(settings), "undoable": undoable, "simulator": simulator}


async def read_body(request: Request) -> dict[str, Any]:
    size = request.headers.get("content-length")
    if size is not None and (not size.isdecimal() or len(size) > 9 or int(size) > MAX_BODY):
        raise HTTPException(413, "Settings request exceeds 32 KiB.")
    if request.headers.get("content-type", "").partition(";")[0].strip() != "application/json":
        raise HTTPException(415, "Send a JSON settings request.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            raise HTTPException(413, "Settings request exceeds 32 KiB.")
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        raise HTTPException(422, "The settings request must contain a JSON object.") from None
    if not isinstance(data, dict):
        raise HTTPException(422, "The settings request must contain a JSON object.")
    return data


def validate_section(previous: Section, changes: dict[str, Any]) -> Section:
    try:
        current = previous.model_dump()
        if "provider" in changes and changes["provider"] != current.get("provider"):
            current.update(api_key=None, model="")
        current.update(changes)
        updated = type(previous).model_validate(current)
    except ValidationError as exc:
        # Never echo arbitrary keys or submitted values, including secrets in malformed requests.
        errors = exc.errors(include_input=False, include_url=False, include_context=False)
        names = {str(error["loc"][0]) for error in errors if error["loc"]}
        fields = sorted(names & set(type(previous).model_fields))
        if fields:
            raise HTTPException(422, "Check these fields: " + ", ".join(fields) + ".") from None
        safe = next((error["msg"].removeprefix("Value error, ") for error in errors if not error["loc"]), None)
        raise HTTPException(422, safe or "The request contains an unknown setting.") from None
    return updated


class _RateLimit:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.minute = -1
        self.total = 0
        self.counts: dict[str, int] = {}

    def check(self, key: str, limit: int) -> None:
        minute = int(monotonic() // 60)
        with self.lock:
            if minute != self.minute:
                self.minute = minute
                self.counts.clear()
                self.total = 0
            count = self.counts.get(key, 0)
            if self.total >= 600 or count >= limit:
                raise HTTPException(429, "Settings requests are temporarily limited.", headers={"Retry-After": "60"})
            self.total += 1
            self.counts[key] = count + 1


def create_router(source: Source, local: SettingsStore, *, simulator: bool = False) -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["settings"])
    # Same HttpOnly cookie and CSRF handshake as approvals, with a cookie scoped to the settings API.
    gate = OperatorGate(cookie=COOKIE, cookie_path=PREFIX)
    limit = _RateLimit()
    sessions: OrderedDict[str, SettingsStore] = OrderedDict()
    session_lock = threading.Lock()

    def store_for(request: Request, bucket: str = "settings", maximum: int = 60) -> SettingsStore:
        sid = gate.require_session(request)
        limit.check(f"{bucket}:{sid}", maximum)
        if not simulator:
            return local
        with session_lock:
            if sid not in sessions:
                if len(sessions) >= 256:
                    sessions.popitem(last=False)
                sessions[sid] = SettingsStore(None, local.defaults)
            sessions.move_to_end(sid)
            return sessions[sid]

    def reply(response: Response, store: SettingsStore) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return envelope(*store.snapshot(), simulator)

    @router.post("/operator/session")
    def session(request: Request, response: Response) -> OperatorSession:
        client = request.client.host if request.client else ""
        # The public dispatcher validates the origin and also applies its own per-client limit.
        limit.check(f"open:{client}", 240 if simulator else 60)
        response.headers["Cache-Control"] = "no-store"
        return gate.open(request, response, resume=True)

    @router.get("")
    def read(request: Request, response: Response) -> dict[str, Any]:
        return reply(response, store_for(request))

    @router.get("/export")
    def export(request: Request, response: Response) -> dict[str, Any]:
        response.headers["Content-Disposition"] = 'attachment; filename="argus-settings.json"'
        return reply(response, store_for(request))

    @router.get("/export/run")
    def export_run(request: Request, response: Response) -> dict[str, Any]:
        store_for(request)
        response.headers["Content-Disposition"] = 'attachment; filename="argus-run.json"'
        response.headers["Cache-Control"] = "no-store"
        return {"graph": source.graph(), "incidents": source.incidents(), "notes": source.notes()}

    def revision(body: dict[str, Any]) -> int:
        value = body.get("revision")
        if type(value) is not int or value < 0:
            raise HTTPException(422, "Send the current settings revision.")
        return value

    def change(area: str, previous: Section, patch: dict[str, Any]) -> Section:
        if simulator and (
            (area == "ai" and "api_key" in patch)
            or (area == "notifications" and any(key.endswith("_url") for key in patch))
            or (area == "sources" and patch.get("sources"))
        ):
            raise HTTPException(403, "Credentials and external connections are available on the local API.")
        result = validate_section(previous, patch)
        try:
            if isinstance(result, DataSources):
                for item in result.sources:
                    check_url(item.url)
            if isinstance(result, Notifications):
                for raw in secret_fields(result).values():
                    if raw is not None:
                        check_url(raw)
        except DeliveryError as exc:
            raise HTTPException(422, str(exc)) from None
        if isinstance(result, Playbooks) and not set(result.disabled) <= {book.id for book in playbook_registry()}:
            raise HTTPException(422, "Select a known playbook.")
        return result

    @router.patch("/{area}")
    async def update(area: Area, request: Request, response: Response) -> dict[str, Any]:
        store = store_for(request, "write", 30)
        body = await read_body(request)
        rev = revision(body)
        patch = body.get("changes")
        if set(body) != {"revision", "changes"} or not isinstance(patch, dict) or not patch:
            raise HTTPException(422, "Send one or more changed settings.")
        metrics = patch.get("per_metric")
        if area == "thresholds" and isinstance(metrics, dict):
            graph = await run_in_threadpool(source.graph)
            if not metrics.keys() <= {node.id for node in graph.north_stars()}:
                raise HTTPException(422, "Select a metric the Watcher monitors.")
        name = area.replace("-", "_")
        try:
            saved = await run_in_threadpool(store.update, name, rev, lambda old: change(name, old, patch))
        except SettingsConflict:
            raise HTTPException(409, "Settings changed in another request. Reload them and try again.") from None
        response.headers["Cache-Control"] = "no-store"
        return envelope(*saved, simulator)

    @router.post("/{area}/undo")
    async def undo(area: Area, request: Request, response: Response) -> dict[str, Any]:
        store = store_for(request, "write", 30)
        body = await read_body(request)
        try:
            saved = await run_in_threadpool(
                store.update, area.replace("-", "_"), revision(body), lambda old: old, undo=True
            )
        except SettingsConflict:
            raise HTTPException(409, "This edit can no longer be undone.") from None
        response.headers["Cache-Control"] = "no-store"
        return envelope(*saved, simulator)

    @router.post("/reset")
    async def reset(request: Request, response: Response) -> dict[str, Any]:
        store = store_for(request, "write", 30)
        body = await read_body(request)
        if body.get("confirm") != "reset":
            raise HTTPException(422, "Confirm the settings reset.")
        try:
            saved = await run_in_threadpool(store.reset, revision(body))
        except SettingsConflict:
            raise HTTPException(409, "Settings changed in another request. Reload them and try again.") from None
        response.headers["Cache-Control"] = "no-store"
        return envelope(*saved, simulator)

    @router.post("/notifications/test")
    async def test_notification(request: Request) -> dict[str, bool]:
        store = store_for(request, "connection", 6)
        if simulator:
            raise HTTPException(403, "External notifications are available on the local API.")
        body = await read_body(request)
        channel = body.get("channel")
        configured = store.read().notifications
        try:
            if channel == "email" and configured.email:
                await run_in_threadpool(
                    send_email, configured.email, "Argus notification test", "Your email is connected."
                )
            elif channel in ("slack", "webhook", "pagerduty") and (url := getattr(configured, f"{channel}_url")):
                await run_in_threadpool(send_https, url.get_secret_value(), {"text": "Argus notification test"})
            else:
                raise HTTPException(422, "Save the notification destination before testing it.")
        except DeliveryError as exc:
            raise HTTPException(502, str(exc)) from None
        return {"ok": True}

    @router.post("/sources/test")
    async def test_source(request: Request) -> dict[str, bool]:
        store = store_for(request, "connection", 6)
        if simulator:
            raise HTTPException(403, "External sources are available on the local API.")
        body = await read_body(request)
        selected = next((item for item in store.read().sources.sources if item.id == body.get("id")), None)
        if selected is None:
            raise HTTPException(404, "Save the data source before testing it.")
        try:
            await run_in_threadpool(send_https, selected.url)
        except DeliveryError as exc:
            raise HTTPException(502, str(exc)) from None
        return {"ok": True}

    return router


def local_settings_path(source: Source) -> Path:
    runtime = getattr(source, "runtime", None)
    return (
        runtime.world.parent / ".argus-settings.json" if runtime else Path.home() / ".local/state/argus/settings.json"
    )
