"""Serve replay evidence from the active Argus incident stream."""

from __future__ import annotations

import os
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException

from argus.api.sources import FIXTURES, LiveSource, ReplaySource, Source
from argus.counterfactual.models import CounterfactualResult, WorldConfig
from argus.counterfactual.replay import ReplayUnavailable, counterfactual


def _world_config(source: Source) -> WorldConfig:
    configured_seed = os.environ.get("ARGUS_COUNTERFACTUAL_SEED")
    if isinstance(source, ReplaySource):
        manifest = source.recording.manifest
        recording = source.recording.path
        if recording is not None and recording.resolve() in {FIXTURES.resolve(), (FIXTURES / "s4").resolve()}:
            configured_seed = "1"
    elif isinstance(source, LiveSource):
        manifest = source.runtime.manifest
        conventional_name = re.fullmatch(r"s[14]-(\d+)", source.runtime.world.parent.name)
        if configured_seed is None and conventional_name is not None:
            configured_seed = conventional_name[1]
    else:
        raise ReplayUnavailable("This source has no MockMart replay configuration.")
    if configured_seed is None:
        raise ReplayUnavailable("The MockMart seed is unavailable. Set ARGUS_COUNTERFACTUAL_SEED for this world.")
    try:
        start = datetime.fromisoformat(str(manifest["world_start"]))
        end = datetime.fromisoformat(str(manifest["world_end"]))
        live_start = datetime.fromisoformat(str(manifest["live_start"]))
        return WorldConfig(seed=int(configured_seed), days=(end - start).days, live_days=(end - live_start).days)
    except (KeyError, ValueError) as exc:
        raise ReplayUnavailable("The MockMart seed or world manifest is invalid for replay.") from exc


def router(source: Source) -> APIRouter:
    routes = APIRouter()

    @routes.get("/incidents/{incident_id}/counterfactual", responses={404: {}, 409: {}})
    def replay_incident(incident_id: str) -> CounterfactualResult:
        incident = next((item for item in source.incidents() if item.id == incident_id), None)
        if incident is None:
            raise HTTPException(404, f"no incident {incident_id}")
        root = incident.findings.root
        reference_id = root.change_pct.receipt if root else None
        reference = source.receipt(reference_id) if reference_id else None
        if reference is None:
            raise HTTPException(409, "This incident has no factual root receipt to match.")
        sim_ts = source.status().get("sim_ts")
        as_of = datetime.fromisoformat(sim_ts) if sim_ts else incident.findings.as_of
        try:
            return counterfactual(incident, config=_world_config(source), as_of=as_of, reference=reference)
        except ReplayUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc

    return routes
