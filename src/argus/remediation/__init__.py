"""Approval and simulator (lane C): operator-approved actions that change only the simulated future.

* `RemediationService` implements `argus.agent.types.ProposalService`: `propose` derives a `rollback_pacer`
  proposal from an admitted incident, `decide` records an authenticated operator's decision, `tick` drives
  expiry, execution and the clock-based effect check against the untouched twin world.
* `create_router(service)` serves `GET /agent/actions[/{id}]`, `POST /agent/actions/{id}/approve|deny` and
  `POST /agent/operator/session`.
* `switch_world(runner, path)` points the runtime at the treated branch.

The simulator runs out of process (`python -m mockmart.remediation apply`); see docs/ext/remediation.md.
"""

from argus.remediation.api import OperatorGate, create_router
from argus.remediation.executor import switch_world
from argus.remediation.models import Execution, ProposalConflict, ProposalNotFound, RemediationEvent
from argus.remediation.service import RemediationService

__all__ = [
    "Execution",
    "OperatorGate",
    "ProposalConflict",
    "ProposalNotFound",
    "RemediationEvent",
    "RemediationService",
    "create_router",
    "switch_world",
]
