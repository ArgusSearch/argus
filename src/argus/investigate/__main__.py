"""`python -m argus.investigate --world runs/s1-7/world.duckdb [--out runs/s1-7/argus]`

Runs the full runtime (freshness, watcher, incidents) over the world's live window with the Stage-2
investigator in place of the Stage-1 one, writes the runtime export plus one Stage-2 report per incident,
and prints one line per incident. Argus only receives the world path, never the truth.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from argus.contracts.findings import Incident
from argus.investigate.procedure import investigate
from argus.investigate.report import render_findings
from argus.runtime import loop
from argus.runtime.loop import Runtime


@contextmanager
def stage_two() -> Iterator[None]:
    """Route the runtime's investigations through the Stage-2 investigator for the duration of the block.
    The runtime binds `investigate` at import time; integration replaces that import with this module's."""
    original = loop.investigate
    loop.investigate = investigate
    try:
        yield
    finally:
        loop.investigate = original


def run_world(world: Path, out: Path | None = None) -> Runtime:
    runtime = Runtime(world)
    with stage_two():
        runtime.run()
    if out is not None:
        runtime.export(out)
        reports = out / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        for inc in runtime.book.incidents.values():
            (reports / f"{inc.id}.stage2.md").write_text(render_findings(inc.findings, runtime.graph))
    return runtime


def summary(inc: Incident) -> dict[str, object]:
    f = inc.findings
    return {
        "id": inc.id,
        "verdict": inc.verdict.value,
        "root": inc.root_node,
        "segment": inc.segment,
        "evidence": f.root.evidence.ref if f.root and f.root.evidence else None,
        "ruled_out": [r.evidence.ref for r in f.ruled_out if r.evidence],
        "explained": f.explained_share,
        "opened_at": inc.opened_at.isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m argus.investigate", description=__doc__.splitlines()[0])
    parser.add_argument("--world", type=Path, required=True, help="path to world.duckdb")
    parser.add_argument("--out", type=Path, default=None, help="export directory (incidents, events, reports)")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    runtime = run_world(args.world, args.out)
    for inc in runtime.book.incidents.values():
        print(json.dumps(summary(inc)))
    print(json.dumps({"incidents": len(runtime.book.incidents), "seconds": round(time.perf_counter() - started, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
