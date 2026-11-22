"""Public projection of the investigator's named playbooks and executed trail."""

from __future__ import annotations

from collections.abc import Sequence
from functools import cache
from typing import Literal

from pydantic import BaseModel

from argus.contracts.findings import Direction, TrailStep
from argus.contracts.graph import Graph
from argus.graph.store import load_seed_graph
from argus.investigate.playbook import GENERAL_PLAYBOOK, STEPS, Playbook, PlaybookStep, choose_playbook


class PlaybookDefinition(BaseModel):
    id: str
    name: str
    steps: tuple[PlaybookStep, ...]


@cache
def playbook_registry() -> tuple[PlaybookDefinition, ...]:
    seed = load_seed_graph()
    variants = [
        choose_playbook(seed, node, direction)
        for node in ("ad_spend", "orders", "sessions")
        for direction in ("down", "up")
    ]
    return tuple(PlaybookDefinition(id=book.id, name=book.name, steps=STEPS) for book in variants)


class MappedStep(BaseModel):
    step_id: str
    status: Literal["done", "skipped", "pending"]
    trail_steps: list[int]


class PlaybookRun(BaseModel):
    anomaly_id: str
    incident_id: str | None
    playbook_id: str
    finished: bool
    steps: list[MappedStep]


def map_playbook(
    graph: Graph,
    node: str,
    direction: Direction,
    anomaly_id: str,
    incident_id: str | None,
    trail: Sequence[TrailStep],
) -> PlaybookRun | None:
    """Map C4 findings.trail or the published C5 steps, including untagged Stage-1 steps."""
    if not trail:
        return None
    registry = {book.id: book for book in playbook_registry()}
    registry[GENERAL_PLAYBOOK.id] = PlaybookDefinition(id=GENERAL_PLAYBOOK.id, name=GENERAL_PLAYBOOK.name, steps=STEPS)
    known_steps = {step.id for step in STEPS}
    tags = [step.data.get("playbook") for step in trail]
    tagged_book = next(
        (
            registry[tag["id"]]
            for tag in tags
            if isinstance(tag, dict) and isinstance(tag.get("id"), str) and tag["id"] in registry
        ),
        None,
    )
    if tagged_book is None:
        try:
            book = choose_playbook(graph, node, direction)
        except KeyError:
            return None
    else:
        book = Playbook(tagged_book.id, tagged_book.name)

    trail_numbers: dict[str, list[int]] = {step.id: [] for step in STEPS}
    for step, tag in zip(trail, tags, strict=True):
        if isinstance(tag, dict) and isinstance(tag.get("step"), str) and tag["step"] in known_steps:
            step_id = tag["step"]
        else:
            step_id = book.step_for(step.kind, step.tool, step.data).id
        trail_numbers[step_id].append(step.step)

    finished = any(step.kind == "verdict" for step in trail)
    return PlaybookRun(
        anomaly_id=anomaly_id,
        incident_id=incident_id,
        playbook_id=book.id,
        finished=finished,
        steps=[
            MappedStep(
                step_id=step.id,
                status="done" if trail_numbers[step.id] else "skipped" if finished else "pending",
                trail_steps=trail_numbers[step.id],
            )
            for step in STEPS
        ],
    )
