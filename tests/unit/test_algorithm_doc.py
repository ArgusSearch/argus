"""README "How Argus decides" and docs/ALGORITHM.md quote the decision rules as numbers; keep them true.

Each row pins one constant to the phrase the docs use for it. When a rule changes, this test fails and
names the phrase to update in README.md, docs/ALGORITHM.md and docs/algorithm.svg.
"""

from __future__ import annotations

import inspect
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

import argus.runtime.loop as runtime_loop
from argus.contracts.graph import EdgeKind, EdgeStatus, Graph
from argus.decompose import segments
from argus.detect.watcher import WatcherConfig
from argus.investigate import ledger, procedure, tools, walk
from argus.investigator import tools as stage_one_tools
from argus.watcher import detect

REPO = Path(__file__).resolve().parents[2]
README = (REPO / "README.md").read_text(encoding="utf-8")
ALGORITHM = (REPO / "docs" / "ALGORITHM.md").read_text(encoding="utf-8")
SVG = (REPO / "docs" / "algorithm.svg").read_text(encoding="utf-8")

# (rule, value in the code, value the docs state, phrase, documents that quote it)
RULES: list[tuple[str, object, object, str, tuple[str, ...]]] = [
    ("open on one hour", detect.Z_OPEN, 5.0, "|z| > 5", ("README", "ALGORITHM", "SVG")),
    ("open on a run", detect.Z_PAIR, 3.5, "|z| > 3.5 in 2 of", ("README", "ALGORITHM", "SVG")),
    ("planned-change watch", WatcherConfig().planned_watch_hours, 24, "for 24 hours", ("README", "ALGORITHM")),
    ("planned-change watch", WatcherConfig().planned_watch_hours, 24, "for 24 h", ("SVG",)),
    ("attention looks per tick", WatcherConfig().budget, 6, "6 more looks per tick", ("README",)),
    ("attention looks per tick", WatcherConfig().budget, 6, "6 extra looks per tick", ("ALGORITHM",)),
    ("follow a factor", walk.FOLLOW_Z, 3.0, "(|z| >= 3)", ("README", "ALGORITHM", "SVG")),
    ("segment target", segments.EP_TARGET, 0.67, "at least 67%", ("README", "ALGORITHM")),
    ("segment target", segments.EP_TARGET, 0.67, ">= 67%", ("SVG",)),
    ("segment size", segments.MAX_CELLS, 3, "at most 3 values", ("README", "ALGORITHM", "SVG")),
    ("segment value floor", segments.EP_MIN, 0.10, "at least 10%", ("ALGORITHM",)),
    ("descent excess", segments.EXCESS_MIN, 0.25, "25 points", ("README", "ALGORITHM", "SVG")),
    ("descent significance", segments.Z_DESCEND, 3.0, "|z| >= 3", ("README", "ALGORITHM", "SVG")),
    ("suspects before onset", procedure.EVENT_BEFORE, timedelta(hours=3), "3 h", ("SVG",)),
    ("suspects before onset", procedure.EVENT_BEFORE, timedelta(hours=3), "3 hours before", ("README", "ALGORITHM")),
    ("suspects after onset", procedure.EVENT_AFTER, timedelta(hours=1), "1 hour after", ("README", "ALGORITHM")),
    ("holdout normal", stage_one_tools.HOLDOUT_Z, 2.0, "|z| < 2", ("ALGORITHM",)),
    ("placebo weeks", tools.PLACEBO_WEEKS, 8, "8 earlier weeks", ("README", "ALGORITHM", "SVG")),
    ("placebo recurs", ledger.RECURRING_HITS, 2, "2 or more", ("ALGORITHM",)),
    ("check budget", ledger.MAX_CHECKS, 12, "at most 12", ("README", "ALGORITHM", "SVG")),
    ("stop explained", procedure.STOP_EXPLAINED, 0.80, "80%", ("README", "ALGORITHM", "SVG")),
    ("supported share", procedure.SUPPORTED_MIN_EXPLAINED, 0.20, "at least 20% explained", ("README", "ALGORITHM")),
    ("significant root", procedure.ROOT_Z, 3.0, "|z| >= 3", ("README", "ALGORITHM")),
]

DOCS = {"README": README, "ALGORITHM": ALGORITHM, "SVG": SVG}


@pytest.mark.parametrize(("rule", "actual", "expected", "phrase", "docs"), RULES, ids=[f"{r[0]}-{r[3]}" for r in RULES])
def test_documented_rule_matches_the_code(
    rule: str, actual: object, expected: object, phrase: str, docs: tuple[str, ...]
) -> None:
    assert actual == expected, f"{rule} is {actual} in the code; update '{phrase}' in {', '.join(docs)}"
    for name in docs:
        text = DOCS[name].replace("&lt;", "<").replace("&gt;", ">")
        assert phrase in text, f"{name} no longer says '{phrase}' ({rule})"


def test_documented_graph_counts(graph: Graph) -> None:
    kinds = Counter(e.kind for e in graph.edges)
    assert (len(graph.nodes), len(graph.edges)) == (27, 44)
    assert kinds == {EdgeKind.FORMULA: 7, EdgeKind.BREAKDOWN: 27, EdgeKind.EVIDENCE: 9, EdgeKind.CAUSE: 1}
    assert "27 nodes and 44 typed edges: 7 formula, 27 breakdown, 9 evidence, 1 cause" in ALGORITHM
    assert [e.status for e in graph.edges if e.kind is EdgeKind.CAUSE] == [EdgeStatus.PROPOSED]
    assert len(graph.north_stars()) == 7
    for text in (README, ALGORITHM):
        assert "7 north-star metrics" in text


def test_the_walk_does_not_follow_cause_edges() -> None:
    for module in (walk, procedure):
        assert "EdgeKind.CAUSE" not in inspect.getsource(module), "the docs say cause edges are not followed"


def test_the_runtime_does_not_use_the_attention_budget_yet() -> None:
    """README and docs/ALGORITHM.md say the attention budget is built but not in the runtime; once the runtime
    uses it, rewrite "What it watches" in both and drop this test."""
    source = inspect.getsource(runtime_loop)
    assert "AttentionBudget" not in source
    assert "plan_watch.tick(" not in source
