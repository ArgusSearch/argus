"""Agent evals exercise real code using local worlds and offline providers."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

# The release tools are scripts outside the installed application packages.
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block network I/O in the eval process, including calls with inherited credentials."""
    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "OPENAI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "ARGUS_SPEND_LEDGER",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ARGUS_DISABLE_PROVIDER", "1")

    def deny(*args: object, **kwargs: object) -> None:
        pytest.fail("deterministic agent eval attempted network access")

    monkeypatch.setattr("argus.agent.provider.AnthropicClient", deny)
    for method in ("connect", "connect_ex", "sendto", "sendmsg"):
        if not hasattr(socket.socket, method):
            continue
        original = getattr(socket.socket, method)

        def local_only(sock: socket.socket, *args: object, _original=original, **kwargs: object):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                deny()
            return _original(sock, *args, **kwargs)

        monkeypatch.setattr(socket.socket, method, local_only)
    for method in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"):
        monkeypatch.setattr(socket, method, deny)
