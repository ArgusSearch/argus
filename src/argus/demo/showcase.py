"""The ordered Mission Control walkthrough and its graph placement hook."""

from typing import Literal

from pydantic import BaseModel

from argus.demo.contracts import StartDemo


class PlaybackChapter(BaseModel):
    kind: Literal["playback"] = "playback"
    id: Literal["fault", "expected_change", "agent"]
    title: str
    start: StartDemo


class PlacementCase(BaseModel):
    name: str
    placed_as: Literal["EXACT", "AMBIGUOUS"]
    show: bool = True


class PlacementChapter(BaseModel):
    kind: Literal["metric_placement"] = "metric_placement"
    id: Literal["metric_placement"] = "metric_placement"
    title: str = "Place a new metric"
    catalog: Literal["/graph/metrics"] = "/graph/metrics"
    method: Literal["POST"] = "POST"
    path: Literal["/graph/metrics"] = "/graph/metrics"
    expected: tuple[Literal["EXACT"], Literal["AMBIGUOUS"]] = ("EXACT", "AMBIGUOUS")
    cases: tuple[PlacementCase, ...]


Chapter = PlaybackChapter | PlacementChapter

SHOWCASE: tuple[Chapter, ...] = (
    PlaybackChapter(id="fault", title="Explain a real fault", start=StartDemo(scenario="s1", speed=8)),
    PlaybackChapter(id="expected_change", title="Recognize a planned change", start=StartDemo(scenario="s2")),
    PlacementChapter(
        cases=(
            PlacementCase(name="cost_per_impression", placed_as="EXACT"),
            PlacementCase(name="conversions_per_impression", placed_as="EXACT", show=False),
            PlacementCase(name="revenue_per_conversion", placed_as="EXACT", show=False),
            PlacementCase(name="revenue_per_impression", placed_as="AMBIGUOUS"),
        )
    ),
    PlaybackChapter(
        id="agent", title="Investigate and verify a rollback", start=StartDemo(scenario="s4", variant="agent")
    ),
)
