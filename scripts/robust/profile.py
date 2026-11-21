"""Measure a fresh Argus API process. Run with `uv run python -m scripts.robust.profile`."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tests.robust.api_harness import RECORDING_SEED, SCENARIOS, Server, frames, recording, serve

from argus.contracts.graph import Graph
from mockmart.sim import WorldConfig
from mockmart.world import generate

RSS_INTERVAL_SECONDS = 0.1


def measure_graph(server: Server, expected: Graph) -> float:
    with server.client() as client:
        graph = Graph.model_validate_json(client.get("/graph").raise_for_status().content)
        complete_at = time.perf_counter()
    assert {node.id for node in graph.nodes} == {node.id for node in expected.nodes}
    assert {edge.id for edge in graph.edges} == {edge.id for edge in expected.edges}
    return complete_at


def peak_rss_kib(pid: int, stop: threading.Event) -> int:
    peak = 0
    while True:
        result = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, check=True, timeout=3)
        peak = max(peak, int(result.stdout))
        if stop.wait(RSS_INTERVAL_SECONDS):
            return peak


def profile(source: tuple[str, str], graph: Graph, count: int) -> dict[str, float]:
    with serve(*source) as server, ThreadPoolExecutor(max_workers=2) as pool:
        stop = threading.Event()
        rss = pool.submit(peak_rss_kib, server.process.pid, stop)
        try:
            graph_request = pool.submit(measure_graph, server, graph)
            with (
                server.client() as control,
                server.client() as subscriber,
                subscriber.stream("GET", "/events", params={"limit": count}) as response,
            ):
                stream = frames(response)
                first = next(stream).event()
                first_at = time.perf_counter()
                graph_at = graph_request.result()
                control.post("/replay", json={"action": "end"}).raise_for_status()
                seqs = [first.seq, *(frame.event().seq for frame in stream)]
                complete_at = time.perf_counter()
                assert seqs == list(range(1, count + 1)), "incomplete or unordered SSE stream"
        finally:
            stop.set()
        return {
            "first_event_ms": round(1000 * (first_at - server.started), 1),
            "full_graph_ms": round(1000 * (graph_at - server.started), 1),
            "stream_complete_ms": round(1000 * (complete_at - server.started), 1),
            "sampled_peak_rss_mib": round(rss.result() / 1024, 1),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS)
    parser.add_argument("--mode", choices=("replay", "live"))
    parser.add_argument("--repetitions", type=int, default=1)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")

    cases = []
    for scenario in (args.scenario,) if args.scenario else SCENARIOS:
        fixture = recording(scenario)
        graph = Graph.model_validate_json((fixture / "graph.json").read_bytes())
        count = len((fixture / "events.jsonl").read_text().splitlines())
        with tempfile.TemporaryDirectory(prefix="argus-profile-") as tmp:
            sources = {}
            if args.mode != "live":
                sources["replay"] = ("--replay", str(fixture))
            if args.mode != "replay":
                world = generate(scenario, WorldConfig(seed=RECORDING_SEED), Path(tmp)).world
                sources["live"] = ("--world", str(world))
            for mode, source in sources.items():
                for repetition in range(1, args.repetitions + 1):
                    cases.append(
                        {
                            "scenario": scenario,
                            "seed": RECORDING_SEED,
                            "mode": mode,
                            "repetition": repetition,
                            "events": count,
                            **profile(source, graph, count),
                        }
                    )

    print(json.dumps({"platform": platform.platform(), "samples": cases}, indent=2))


if __name__ == "__main__":
    main()
