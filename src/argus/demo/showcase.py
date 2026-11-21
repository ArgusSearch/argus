"""The ordered Mission Control walkthrough and its graph placement hook."""

from typing import Literal

from pydantic import BaseModel

from argus.demo.contracts import StartDemo


class PlaybackChapter(BaseModel):
    kind: Literal["playback"] = "playback"
    id: Literal["fault", "expected_change", "agent"]
    title: str
    start: StartDemo


class PlacementChapter(BaseModel):
    kind: Literal["metric_placement"] = "metric_placement"
    id: Literal["metric_placement"] = "metric_placement"
    title: str = "Place a new metric"
    method: Literal["POST"] = "POST"
    path: Literal["/graph/metrics"] = "/graph/metrics"
    expected: tuple[Literal["EXACT"], Literal["AMBIGUOUS"]] = ("EXACT", "AMBIGUOUS")


Chapter = PlaybackChapter | PlacementChapter

SHOWCASE: tuple[Chapter, ...] = (
    PlaybackChapter(id="fault", title="Explain a real fault", start=StartDemo(scenario="s1", speed=8)),
    PlaybackChapter(id="expected_change", title="Recognize a planned change", start=StartDemo(scenario="s2")),
    PlacementChapter(),
    PlaybackChapter(
        id="agent", title="Investigate and verify a rollback", start=StartDemo(scenario="s4", variant="agent")
    ),
)
