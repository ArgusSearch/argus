"""The executable playbook `rollback_pacer`: its parameters come from the admitted incident and the world, never prose.

A proposal is possible only for a SUPPORTED_CAUSE incident whose root is the pacing ratio (or ad spend) and
whose cited evidence is an ad-pacer deploy (or the grouped pacer changes it produced). The countries and the
version to roll back are read from that log row in the world, with a receipt; the incident's own segment must
lie inside that scope.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from argus.agent.types import Rejection
from argus.contracts.findings import EvidenceRef, Incident, IncidentState, Receipt, Verdict
from argus.contracts.world import COUNTRIES
from argus.semantic.compile import quote
from argus.semantic.runner import Runner, sql_ts

ROOT_NODES = ("pacing_ratio", "ad_spend")
PACER_SERVICE = "ad-pacer"
BASE_PACER = "1.6"
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
# The runtime must switch worlds before it can see a treated row: the first batch of the effective hour lands
# one hour and five minutes after it. An approval is therefore accepted up to one hour before the effective
# hour, which leaves a full simulated hour for the simulator run.
APPROVAL_MARGIN = HOUR


@dataclass(frozen=True)
class PacerRollback:
    countries: list[str]
    from_version: str
    evidence: EvidenceRef
    receipt: Receipt
    effective_at: datetime
    expires_at: datetime


def schedule(as_of: datetime) -> tuple[datetime, datetime]:
    """(effective_at, expires_at): the first budget-day boundary that leaves at least an hour to decide.

    A new budget day never redistributes a budget already spent, so the rollback starts at 00:00 UTC.
    """
    effective = (as_of + APPROVAL_MARGIN).replace(hour=0, minute=0, second=0, microsecond=0) + DAY
    return effective, effective - APPROVAL_MARGIN


def derive_rollback(incident: Incident, runner: Runner, as_of: datetime) -> PacerRollback | Rejection:
    findings, root = incident.findings, incident.findings.root
    if incident.state is IncidentState.RESOLVED:
        return Rejection(reason="stale", detail=f"{incident.id} is resolved; there is nothing to roll back")
    if findings.verdict is not Verdict.SUPPORTED_CAUSE or root is None or root.evidence is None:
        return Rejection(
            reason="missing_check",
            detail="rollback_pacer needs a SUPPORTED_CAUSE incident with a cited cause",
            upgrade="a holdout check that supports the pacer rollout",
        )
    if root.node not in ROOT_NODES:
        return Rejection(reason="wrong_subject", detail=f"rollback_pacer acts on pacing, not on {root.node}")
    event = root.evidence
    if event.log == "log_deploys":
        sql = (
            "SELECT id, ts, service, version, scope FROM log_deploys "
            f"WHERE id = {quote(event.ref)} AND ts = {sql_ts(event.ts)}"
        )
        rows, receipt = runner.query(sql, as_of, purpose="the deployment the rollback undoes")
        if len(rows) != 1 or rows[0]["service"] != PACER_SERVICE:
            return Rejection(reason="wrong_subject", detail=f"{event.ref} is not an ad-pacer deploy in this world")
        scope = json.loads(rows[0]["scope"] or "{}")
        countries = sorted(set(scope.get("country", [])))
        version = str(rows[0]["version"])
    elif event.log == "log_ad_budgets" and event.kind == "pacer_change":
        sql = (
            "SELECT id, ts, country, pacer_version FROM log_ad_budgets "
            f"WHERE kind = 'pacer_change' AND ts = {sql_ts(event.ts)} ORDER BY id"
        )
        rows, receipt = runner.query(sql, as_of, purpose="the pacer changes the rollback undoes")
        versions = {str(r["pacer_version"]) for r in rows}
        if not rows or event.ref not in {r["id"] for r in rows} or len(versions) != 1:
            return Rejection(reason="wrong_subject", detail=f"{event.ref} is not one pacer rollout in this world")
        countries = sorted({str(r["country"]) for r in rows})
        version = versions.pop()
    else:
        return Rejection(reason="wrong_subject", detail=f"{event.log}/{event.ref} is not a pacer change")
    if not countries or any(c not in COUNTRIES for c in countries):
        return Rejection(reason="policy", detail="the rollout names no rollable country scope")
    if version.startswith(BASE_PACER):
        return Rejection(reason="stale", detail=f"the cited change already serves pacer {BASE_PACER}")
    segment_country = root.segment.get("country") or incident.segment.get("country")
    if segment_country is not None and segment_country not in countries:
        return Rejection(reason="wrong_subject", detail=f"{segment_country} lies outside the rollout scope")
    effective_at, expires_at = schedule(as_of)
    return PacerRollback(countries, version, event, receipt, effective_at, expires_at)


def sentence(rollback: PacerRollback) -> str:
    where = " and ".join(rollback.countries)
    return (
        f"Roll the ad pacer back from {rollback.from_version} to {BASE_PACER} for the {where} budget lines "
        f"from {rollback.effective_at:%Y-%m-%d %H:%M} UTC."
    )
