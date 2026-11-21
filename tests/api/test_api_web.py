"""Mission Control's own checks (TypeScript and vitest), run when its dependencies are installed."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from argus.graph.store import REPO

WEB = REPO / "web"
pytestmark = pytest.mark.skipif(
    not (WEB / "node_modules").exists() or shutil.which("npm") is None,
    reason="web dependencies not installed (npm --prefix web install)",
)


@pytest.mark.parametrize("script", ["typecheck", "test"])
def test_web(script: str) -> None:
    done = subprocess.run(["npm", "--prefix", str(WEB), "run", script], capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
