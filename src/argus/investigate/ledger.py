"""Hypothesis ledger: prediction first, typed check second, deterministic verdict third.

A `Hypothesis` names a C6 tool, fills that tool's typed input model and states which *outcome* of the
check would support it (`expect`). Whoever proposes it (the graph, or an LLM planner) never sees a
number before the check runs and never decides the result: `outcome_of` reads the outcome from the
tool's output and `judge` compares it with `expect`.

| tool              | outcomes (what `expect` may say)          |
|-------------------|-------------------------------------------|
| holdout_check     | consistent, refuted                       |
| placebo_test      | unusual, recurring                        |
| mix_rate_split    | mix, rate                                 |
| segment_search    | localized, diffuse                        |
| decompose_formula | factor:<node id> (the dominant factor)    |
| list_events       | found, none                               |
| check_freshness   | complete, incomplete                      |
| check_identities  | hold, broken                              |

The ledger also enforces the check budget of one investigation (stopping rule: at most 12 checks).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from argus.contracts.tools import (
    TOOL_MODELS,
    CheckFreshnessOutput,
    CheckIdentitiesOutput,
    DecomposeFormulaOutput,
    HoldoutCheckOutput,
    ListEventsOutput,
    MixRateSplitOutput,
    PlaceboTestOutput,
    SegmentSearchOutput,
    ToolOutput,
)

Status = Literal["validated", "refuted", "inconclusive"]

MAX_CHECKS = 12
RECURRING_HITS = 2
MIX_DOMINANT = 0.67
LOCALIZED_EP = 0.67

OUTCOMES: dict[str, tuple[str, ...]] = {
    "holdout_check": ("consistent", "refuted"),
    "placebo_test": ("unusual", "recurring"),
    "mix_rate_split": ("mix", "rate"),
    "segment_search": ("localized", "diffuse"),
    "decompose_formula": ("factor:",),
    "list_events": ("found", "none"),
    "check_freshness": ("complete", "incomplete"),
    "check_identities": ("hold", "broken"),
}
"""Outcome vocabulary per tool. `decompose_formula` outcomes are `factor:<node id>`."""

TRAIL_KIND: dict[str, str] = {
    "check_freshness": "freshness",
    "check_identities": "identities",
    "decompose_formula": "decompose",
    "mix_rate_split": "decompose",
    "segment_search": "segment",
    "get_series": "segment",
    "list_events": "events",
    "holdout_check": "holdout",
    "placebo_test": "holdout",
    "lag_test": "events",
    "counterfactual_impact": "impact",
}


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, description="what would be true if the hypothesis holds")
    prediction: str = Field(min_length=1, description="what the check should show, written before it runs")
    tool: str = Field(description="C6 tool name (argus.contracts.tools.TOOLS)")
    input: dict[str, Any] = Field(description="the tool's typed input model, as JSON")
    expect: str = Field(description="the tool outcome that supports the hypothesis (see OUTCOMES)")
    source: str = Field(default="graph", description="'graph' (fixed opening) or 'planner:<name>'")

    @model_validator(mode="after")
    def _typed(self) -> Hypothesis:
        if self.tool not in TOOL_MODELS:
            raise ValueError(f"unknown tool {self.tool!r}")
        if self.tool not in OUTCOMES:
            raise ValueError(f"{self.tool} has no judgeable outcome; pick one of {sorted(OUTCOMES)}")
        TOOL_MODELS[self.tool][0].model_validate(self.input)
        allowed = OUTCOMES[self.tool]
        if self.tool == "decompose_formula":
            if not self.expect.startswith("factor:") or len(self.expect) <= len("factor:"):
                raise ValueError("decompose_formula expects 'factor:<node id>'")
        elif self.expect not in allowed:
            raise ValueError(f"{self.tool} outcomes are {list(allowed)}, not {self.expect!r}")
        return self


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    hypothesis: Hypothesis
    status: Status
    outcome: str | None
    summary: str
    receipts: list[str] = Field(default_factory=list)


def outcome_of(tool: str, output: ToolOutput) -> str | None:
    """The outcome label of a check, or None when the result is in between (inconclusive)."""
    if isinstance(output, HoldoutCheckOutput):
        return output.result if output.result in ("consistent", "refuted") else None
    if isinstance(output, PlaceboTestOutput):
        if output.weeks == 0:
            return None
        if output.hits == 0:
            return "unusual"
        return "recurring" if output.hits >= RECURRING_HITS else None
    if isinstance(output, MixRateSplitOutput):
        if not output.change:
            return None
        if output.rates_flat and output.mix / output.change >= MIX_DOMINANT:
            return "mix"
        return "rate" if output.rate / output.change >= MIX_DOMINANT else None
    if isinstance(output, SegmentSearchOutput):
        if not output.segment:
            return "diffuse"
        return "localized" if output.explained_share >= LOCALIZED_EP else None
    if isinstance(output, DecomposeFormulaOutput):
        return f"factor:{output.contributions[0].node}" if output.contributions else None
    if isinstance(output, ListEventsOutput):
        return "found" if output.events else "none"
    if isinstance(output, CheckFreshnessOutput):
        return "complete" if output.ok else "incomplete"
    if isinstance(output, CheckIdentitiesOutput):
        return "hold" if output.ok else "broken"
    return None


def judge(hypothesis: Hypothesis, outcome: str | None) -> Status:
    if outcome is None:
        return "inconclusive"
    if outcome == hypothesis.expect:
        return "validated"
    if hypothesis.tool == "decompose_formula" or outcome in OUTCOMES.get(hypothesis.tool, ()):
        return "refuted"
    return "inconclusive"


class Ledger:
    """Every hypothesis an investigation tested, in order, with its typed check and verdict."""

    def __init__(self, budget: int = MAX_CHECKS):
        self.budget = budget
        self.entries: list[LedgerEntry] = []

    @property
    def remaining(self) -> int:
        return self.budget - len(self.entries)

    def test(
        self, hypothesis: Hypothesis, run: Callable[[Hypothesis], ToolOutput]
    ) -> tuple[LedgerEntry, ToolOutput | None] | None:
        """Run the hypothesis' check and record the verdict; None when the budget is spent.
        A check that cannot run (tool unavailable, bad input) is recorded as inconclusive."""
        if self.remaining <= 0:
            return None
        hid = f"h{len(self.entries) + 1}"
        try:
            output: ToolOutput | None = run(hypothesis)
        except (KeyError, ValueError, RuntimeError) as err:
            entry = LedgerEntry(
                id=hid, hypothesis=hypothesis, status="inconclusive", outcome=None, summary=f"check failed: {err}"
            )
            self.entries.append(entry)
            return entry, None
        assert output is not None
        outcome = outcome_of(hypothesis.tool, output)
        entry = LedgerEntry(
            id=hid,
            hypothesis=hypothesis,
            status=judge(hypothesis, outcome),
            outcome=outcome,
            summary=output.summary,
            receipts=list(output.receipts),
        )
        self.entries.append(entry)
        return entry, output
