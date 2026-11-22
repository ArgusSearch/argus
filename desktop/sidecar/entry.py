"""Private entry point for Electron's frozen, loopback-only FastAPI process."""

from __future__ import annotations

import asyncio
import hmac
import json
import mimetypes
import os
import socket
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from credentials import backend, get_key, update_key
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HOST = "127.0.0.1"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; worker-src 'self' blob:; object-src 'none'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


class DesktopAccess:
    def __init__(self, app: ASGIApp, host: str, token: str) -> None:
        self.app = app
        self.host = host
        self.token = token.encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        token = headers.get("x-argus-desktop", "").encode("latin-1")
        if headers.get("host") != self.host or not hmac.compare_digest(token, self.token):
            await PlainTextResponse("Forbidden", status_code=403)(scope, receive, send)
            return

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response = MutableHeaders(scope=message)
                response["Content-Security-Policy"] = CSP
                response["Cache-Control"] = "no-store"
                response["X-Content-Type-Options"] = "nosniff"
            await send(message)

        await self.app(scope, receive, secured_send)


def make_source(data: Path, replay_only: bool):
    from argus.api.sources import LiveSource, ReplaySource
    from mockmart.sim import WorldConfig
    from mockmart.world import generate

    unavailable = False
    key = None
    if not replay_only:
        try:
            key = get_key()
        except Exception:
            unavailable = True
    if key is None:
        return ReplaySource(loop=True), unavailable

    # Publish only a complete simulator world, so a failed generation can be retried.
    worlds = data / "worlds"
    worlds.mkdir(parents=True, exist_ok=True)
    world_dir = worlds / "s1-seed1-v1"
    if not (world_dir / "world.duckdb").is_file():
        with TemporaryDirectory(dir=worlds) as temp:
            generated = Path(temp) / "world"
            generate("s1", WorldConfig(seed=1), generated)
            generated.replace(world_dir)

    os.environ["ANTHROPIC_API_KEY"] = key
    try:
        return LiveSource(world_dir / "world.duckdb", agent="live"), unavailable
    finally:
        del os.environ["ANTHROPIC_API_KEY"]


async def serve(command: dict) -> None:
    from argus.api.app import WEB_DIST, create_app

    data = Path(command["data"])
    # Replay diagnostics remain in the user's app data. The packaged resources can be read-only.
    os.environ["ARGUS_RUNS_DIR"] = str(data / "runs")
    source, unavailable = make_source(data, command["replayOnly"])
    if not (WEB_DIST / "index.html").is_file():
        raise RuntimeError("The Mission Control build is missing")
    # Serve the bundled web entry point and modules independently of the Windows MIME registry.
    mimetypes.add_type("text/html", ".html")
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/javascript", ".mjs")
    mimetypes.add_type("text/css", ".css")
    app = create_app(
        source,
        bench_out=data / "runs" / "bench",
        connections_path=data / "connections",
        connection_keyring=backend(),
    )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((HOST, 0))
        listener.listen(socket.SOMAXCONN)
        port = listener.getsockname()[1]
        config = uvicorn.Config(
            DesktopAccess(app, f"{HOST}:{port}", command["token"]),
            host=HOST,
            port=port,
            loop="asyncio",
            http="h11",
            ws="none",
            lifespan="on",
            access_log=False,
            log_level="critical",
            timeout_graceful_shutdown=4,
            proxy_headers=False,
        )
        server = uvicorn.Server(config)
        loop = asyncio.get_running_loop()

        def stop() -> None:
            source.bus.close()
            server.should_exit = True

        def watch_parent() -> None:
            # A pipe close works on Windows and also stops the sidecar if Electron exits abruptly.
            sys.stdin.read(1)
            if not loop.is_closed():
                loop.call_soon_threadsafe(stop)

        threading.Thread(target=watch_parent, daemon=True).start()
        print(json.dumps({"port": port, "mode": source.mode, "keychainUnavailable": unavailable}), flush=True)
        await server.serve(sockets=[listener])


def main() -> int:
    sys.stdin.reconfigure(encoding="utf-8")
    command = json.loads(sys.stdin.readline())
    operation = command["operation"]
    if operation == "serve":
        asyncio.run(serve(command))
    elif operation == "save":
        update_key(command["key"])
    elif operation == "remove":
        update_key(None)
    else:
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Provider and credential errors can include sensitive inputs. Report only the exit code.
        raise SystemExit(1) from None
