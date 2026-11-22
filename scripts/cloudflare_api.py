"""Loopback origin for the public Argus demo. Run with an allowlisted environment."""

import argparse
import os
from collections import Counter
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs

import uvicorn
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from argus.api.app import BENCH_OUT, create_app
from argus.api.sources import LiveSource, ReplaySource

WEB_ORIGINS = ("https://argus.caniberk.dev", "https://argus-eye.pages.dev")
PAGES_ORIGIN = WEB_ORIGINS[1]
MAX_BODY = 128 * 1024


def origin_app(world: Path | None, *, bench_out: Path = BENCH_OUT):
    # Refuse inherited provider credentials and the provider helper's repository-local fallback.
    if any(key.startswith(("ANTHROPIC_", "OPENAI_")) for key in os.environ) or Path(".env").exists():
        raise RuntimeError("Public demo requires a clean checkout and a credential-free environment")
    replay_source = ReplaySource(loop=world is None)
    live_source = LiveSource(world, agent="off") if world else replay_source
    replay = create_app(replay_source, bench_out=bench_out)
    live = create_app(live_source, bench_out=bench_out) if world else replay
    apps = [live, replay] if world else [replay]
    for app in apps:
        app.user_middleware[:] = [entry for entry in app.user_middleware if entry.cls is not CORSMiddleware]

    @asynccontextmanager
    async def running():
        async with AsyncExitStack() as stack:
            for app in apps:
                await stack.enter_async_context(app.router.lifespan_context(app))
            yield

    requests: Counter[str] = Counter()
    window = 0

    async def dispatch(scope, receive, send):
        nonlocal window
        if scope["type"] == "lifespan":
            await uvicorn_lifespan(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if headers.get("origin") not in (None, *WEB_ORIGINS):
            await JSONResponse({"detail": "Origin refused"}, status_code=403)(scope, receive, send)
            return
        minute = int(monotonic() // 60)
        if minute != window:
            requests.clear()
            window = minute
        peer = headers.get("cf-connecting-ip", "loopback")
        if requests["total"] >= 1200 or requests[f"ip:{peer}"] >= 240:
            limit = JSONResponse({"detail": "Rate limit"}, status_code=429, headers={"Retry-After": "60"})
            await limit(scope, receive, send)
            return
        requests["total"] += 1
        requests[f"ip:{peer}"] += 1

        path, method = scope["path"], scope["method"]
        sealed = path.startswith("/sealed-run/")
        if sealed:
            path = path.removeprefix("/sealed-run")
            scope = {**scope, "path": path, "raw_path": path.encode()}
        if method == "POST" and path.rstrip("/") == "/graph/metrics":
            refusal = JSONResponse({"detail": "Public Argus uses the checked-in metric catalog"}, status_code=403)
            await refusal(scope, receive, send)
            return
        content_length = int(headers.get("content-length", "0"))
        too_large = JSONResponse({"detail": "Request body too large"}, status_code=413)
        if content_length > MAX_BODY:
            await too_large(scope, receive, send)
            return
        if content_length or headers.get("transfer-encoding") or method in {"POST", "PUT", "PATCH", "DELETE"}:
            buffer = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                buffer.extend(message.get("body", b""))
                if len(buffer) > MAX_BODY:
                    await too_large(scope, receive, send)
                    return
                if not message.get("more_body"):
                    break
            original_receive = receive
            body = bytes(buffer)

            async def receive_body():
                nonlocal body
                if body is not None:
                    payload, body = body, None
                    return {"type": "http.request", "body": payload, "more_body": False}
                return await original_receive()

            receive = receive_body

        query = parse_qs(scope["query_string"].decode("ascii", errors="replace"))
        recorded = (
            sealed
            or path in {"/demo", "/openapi.json"}
            or path.startswith("/demo/")
            or (path.startswith("/agent/") and "run_id" in query)
        )
        if method == "GET" and path == "/events/snapshot":
            source = replay_source if recorded else live_source
            try:
                after = max(0, int(query.get("after", ["0"])[0]))
            except ValueError:
                await JSONResponse({"detail": "Invalid event cursor"}, status_code=400)(scope, receive, send)
                return
            stream, events, more = source.bus.page(query.get("stream", [None])[0], after, 500)
            snapshot = JSONResponse(
                {
                    "stream": stream,
                    "mode": source.mode,
                    "events": [event.model_dump(mode="json") for event in events],
                    "more": more,
                },
                headers={"Cache-Control": "no-store"},
            )
            await snapshot(scope, receive, send)
            return
        if path.startswith("/agent/") and headers.get("origin") in WEB_ORIGINS:
            # The outer middleware has verified the public demo origin. OperatorGate still requires its
            # loopback session and CSRF token, and recorded decisions only update the sealed playback.
            scope = {**scope, "headers": [(key, value) for key, value in scope["headers"] if key != b"origin"]}

        async def secure_cookie(message):
            if message["type"] == "http.response.start" and path == "/agent/operator/session":
                values = MutableHeaders(scope=message)
                if cookie := values.get("set-cookie"):
                    if sealed:
                        cookie = cookie.replace("Path=/agent", "Path=/sealed-run/agent")
                    if headers.get("origin") == PAGES_ORIGIN:
                        cookie = cookie.replace("SameSite=strict", "SameSite=None") + "; Partitioned"
                    values["set-cookie"] = cookie + "; Secure"
            await send(message)

        await (replay if recorded else live)(scope, receive, secure_cookie)

    async def uvicorn_lifespan(scope, receive, send):
        await receive()
        async with running():
            await send({"type": "lifespan.startup.complete"})
            await receive()
        await send({"type": "lifespan.shutdown.complete"})

    return CORSMiddleware(
        dispatch,
        allow_origins=list(WEB_ORIGINS),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Argus-CSRF"],
        allow_credentials=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--world", type=Path)
    parser.add_argument("--bench-out", type=Path, default=BENCH_OUT)
    args = parser.parse_args()
    uvicorn.run(
        origin_app(args.world, bench_out=args.bench_out),
        host="127.0.0.1",
        port=args.port,
        proxy_headers=False,
        ws="none",
        lifespan="on",
    )
