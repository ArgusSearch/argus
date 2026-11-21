"""Evidence versus hypothesis, per claim.

Every sentence a report can say is a `Claim` with a label:

* `evidence`: a deterministic check with receipts backs it (a refutation is evidence too);
* `hypothesis`: consistent with the data but not confirmed; `upgrade` names what would confirm it.

The investigator stores the claims in the data of its final trail step (`data["claims"]`), so they
travel inside the C4 findings and the C5 `investigation_step` events without a contract change.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from argus.contracts.findings import Findings

Label = Literal["evidence", "hypothesis"]


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    label: Label
    basis: str = Field(description="which check backs the claim, e.g. 'holdout_check: consistent'")
    receipts: list[str] = Field(default_factory=list)
    upgrade: str | None = Field(default=None, description="hypothesis only: the evidence that would confirm it")


def evidence(text: str, basis: str, receipts: list[str] | None = None) -> Claim:
    return Claim(text=text, label="evidence", basis=basis, receipts=list(receipts or []))


def hypothesis(text: str, basis: str, upgrade: str, receipts: list[str] | None = None) -> Claim:
    return Claim(text=text, label="hypothesis", basis=basis, upgrade=upgrade, receipts=list(receipts or []))


def claims_of(findings: Findings) -> list[Claim]:
    """The labelled claims of an investigation (empty for Stage-1 findings)."""
    for step in reversed(findings.trail):
        if step.kind == "verdict" and "claims" in step.data:
            return [Claim.model_validate(c) for c in step.data["claims"]]
    return []
