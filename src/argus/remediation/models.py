"""Lane C records beyond the frozen agent types: errors, the execution record and the published events."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from argus.agent.types import ProposalView, ReceiptLink

FACTUAL = "factual"
PLAYBOOKS = ("rollback_pacer",)
FINAL_STATES = frozenset({"DENIED", "EXPIRED", "VERIFIED", "NO_EFFECT", "INCONCLUSIVE"})


class ProposalNotFound(LookupError):
    """No proposal with this id (HTTP 404)."""


class ProposalConflict(RuntimeError):
    """The decision does not apply to the proposal as it stands (HTTP 409): stale digest, decided, expired."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Execution(_Strict):
    """What the simulator did for an approved proposal. The branch is the treated world, opened read-only."""

    world_revision: str = Field(description="'<proposal id>-treated'")
    branch: str = Field(description="directory of the treated world (world.duckdb, manifest.json)")
    noop: bool = Field(description="the requested lines were not on the faulty pacer; the world is unchanged")
    lines: list[dict[str, str]] = Field(description="budget lines rolled back: advertiser_id, country, from_version")
    rows_replaced: int
    past_receipt: ReceiptLink | None = Field(
        default=None, description="the pre-action receipt re-run on the treated world (same hash = past unchanged)"
    )
    activated: bool = Field(default=False, description="the runtime reads the treated world")


RemediationEventKind = Literal["action_proposed", "action_decided", "action_applied", "effect_checked"]


class RemediationEvent(_Strict):
    """Published to lane A for every transition; A turns it into an `ActivityRecord` (A assigns `seq`)."""

    kind: RemediationEventKind
    sim_ts: datetime
    actor: Literal["host", "operator"]
    text: str
    proposal: ProposalView
    receipt_links: list[ReceiptLink] = Field(default_factory=list)
