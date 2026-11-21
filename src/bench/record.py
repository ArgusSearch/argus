"""Record a replayable Argus run of any scenario: `argus-bench record s3 --seed 1 --out fixtures/s3`.

The world is generated and its truth sealed exactly as for a bench case. Argus (the runtime) runs over the
world alone, and its export plus the public manifest becomes the recording `argus api --replay` serves
(`argus.api.recording`). Only after the run is the truth revealed, to grade what the recording shows.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from argus.runtime.loop import Runtime
from bench.agents import output_from_runtime
from bench.grade import RunGrade
from bench.runner import grade_case, prepare_case, reveal

AGENT = "argus"


def record(scenario: str, seed: int, target: Path, work_root: Path) -> RunGrade:
    """Run Argus over a fresh sealed world of `scenario` and write the recording to `target`."""
    if target.exists():
        if not (target / "events.jsonl").exists():
            raise FileExistsError(f"{target} exists and is not a recording; refusing to replace it")
        shutil.rmtree(target)  # a re-recording replaces the old one whole, so no stale report survives
    case = prepare_case(scenario, seed, work_root)
    started = time.perf_counter()
    runtime = Runtime(case.world)  # Argus gets the world, never the truth
    try:
        runtime.run()
        seconds = time.perf_counter() - started
        runtime.export(target)
    finally:
        runtime.runner.close()
    shutil.copy(case.manifest, target / "manifest.json")
    output = output_from_runtime(runtime, seconds)
    return grade_case(case, AGENT, output, seconds, reveal(case))
