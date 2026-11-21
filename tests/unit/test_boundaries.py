"""Module boundaries that four parallel lanes rely on, and the truth wall ("it could not have peeked")."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def _imports(package: str) -> dict[Path, set[str]]:
    out: dict[Path, set[str]] = {}
    for path in (SRC / package).rglob("*.py"):
        names: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        out[path] = names
    return out


def test_argus_never_imports_the_simulator_or_the_bench() -> None:
    for path, names in _imports("argus").items():
        bad = {n for n in names if n.split(".")[0] in ("mockmart", "bench")}
        assert not bad, f"{path.relative_to(SRC)} imports {bad}"


def test_argus_never_mentions_the_truth_database() -> None:
    for path in (SRC / "argus").rglob("*.py"):
        text = path.read_text()
        assert "truth.duckdb" not in text and "injected_events" not in text, path.relative_to(SRC)


def test_simulator_only_uses_the_shared_contracts() -> None:
    for path, names in _imports("mockmart").items():
        bad = {n for n in names if n.startswith("argus") and not n.startswith("argus.contracts")}
        assert not bad, f"{path.relative_to(SRC)} imports {bad}"


def test_runtime_opens_the_world_read_only(tmp_path: Path) -> None:
    import duckdb
    import pytest

    from argus.contracts.world import render_schema_sql
    from argus.semantic.runner import Runner

    world = tmp_path / "world.duckdb"
    con = duckdb.connect(str(world))
    con.execute(render_schema_sql())
    con.close()
    runner = Runner(world)
    with pytest.raises(duckdb.Error):
        runner._con.execute("CREATE TABLE sneaky (x INT)")
