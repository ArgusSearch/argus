"""Start the demo CLI on an OS-assigned loopback port and consume its SSE frames."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx2

from argus.contracts.events import Event

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ("quiet", "s1", "s2", "s3", "s4", "s5")
RECORDING_SEED = 1  # `make fixtures` records every scenario at this seed.
BOUND = re.compile(r"Uvicorn running on (http://127\.0\.0\.1:[0-9]+)")
TIMEOUT = 45


def recording(scenario: str) -> Path:
    root = ROOT / "fixtures"
    return root if scenario == "s1" else root / scenario


def api_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "argus.cli", "api", "--host", "127.0.0.1", "--port", "0", *args]


@dataclass(frozen=True)
class Server:
    process: subprocess.Popen[bytes]
    url: str
    started: float

    def client(self, *, transport: httpx2.HTTPTransport | None = None) -> httpx2.Client:
        return httpx2.Client(base_url=self.url, timeout=TIMEOUT, trust_env=False, transport=transport)


@contextmanager
def serve(*args: str) -> Iterator[Server]:
    with tempfile.TemporaryDirectory(prefix="argus-api-") as tmp:
        log_path = Path(tmp) / "server.log"
        started = time.perf_counter()
        with (
            log_path.open("wb") as log,
            subprocess.Popen(api_command(*args), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT) as process,
        ):
            try:
                deadline = started + TIMEOUT
                while time.perf_counter() < deadline and process.poll() is None:
                    if match := BOUND.search(log_path.read_text(errors="replace")):
                        yield Server(process, match[1], started)
                        return
                    time.sleep(0.01)
                raise AssertionError(f"Argus failed to start (exit={process.poll()}):\n{log_path.read_text()}")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                        raise AssertionError(f"Argus required SIGKILL to stop:\n{log_path.read_text()}") from None


@dataclass(frozen=True)
class Frame:
    name: str
    id: str | None
    data: str

    def event(self) -> Event:
        event = Event.model_validate_json(self.data)
        assert self.id == str(event.seq)
        assert self.name == event.type.value
        return event


def frames(response: httpx2.Response) -> Iterator[Frame]:
    response.raise_for_status()
    assert response.headers["content-type"].split(";")[0] == "text/event-stream"
    fields: dict[str, str] = {}
    data: list[str] = []
    deadline = time.monotonic() + TIMEOUT
    for line in response.iter_lines():
        if time.monotonic() >= deadline:
            raise TimeoutError("SSE stream did not finish before the deadline")
        if not line:
            if data:
                yield Frame(fields.get("event", "message"), fields.get("id"), "\n".join(data))
            fields.clear()
            data.clear()
        elif not line.startswith(":"):
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "data":
                data.append(value)
            else:
                fields[field] = value
    assert not data, "SSE response ended in the middle of a frame"
