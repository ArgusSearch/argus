"""Watcher: quiet worlds stay quiet; z-scores are calibrated."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np

from argus.contracts.graph import Graph
from argus.semantic.runner import Runner
from argus.watcher.detect import Detector
from mockmart.world import WorldPaths


def test_quiet_world_opens_no_anomaly_and_z_is_calibrated(graph: Graph, quiet_world: WorldPaths) -> None:
    runner = Runner(quiet_world.world)
    det = Detector(graph, runner)
    live = datetime.fromisoformat(json.loads(quiet_world.manifest.read_text())["live_start"])
    zs: list[float] = []
    for h in range(120):
        hour = live + timedelta(hours=h)
        as_of = hour + timedelta(hours=2)
        det.refresh(hour, as_of, {})
        for node in det.nodes:
            score = det.score(node, hour)
            assert score is not None
            zs.append(score.z)
            opened, _ = det.observe(score, as_of)
            assert opened is None, f"false alarm on {node} at {hour}: z {score.z:.2f}"
    assert 0.8 < float(np.std(zs)) < 1.2
