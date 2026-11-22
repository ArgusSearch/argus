"""Operator-approved remediation inside the simulator: one fixed, typed action that changes only the future.

`python -m mockmart.remediation apply --request <request.json>` is the only entry point. Argus writes the
request (it never imports this package) and opens the resulting world read-only, exactly as it does with
`mockmart.cli generate` for the counterfactual replay.

The one action is `rollback_pacer`: every requested budget line whose pacer is 1.7 at the effective hour goes
back to the 1.6 delivery profile from that hour on. The effective hour is a budget-day boundary (00:00 UTC),
so a day whose budget is already spent is never redistributed. Rows of those lines with `ts >= effective_at`
are re-drawn with the simulator's own ads sampler and micro-batch delivery; every other row of every table is
copied unchanged, so every query at an `as_of` before the effective hour returns the same rows as before.
"""

from __future__ import annotations

from mockmart.remediation.rollback import REQUEST_VERSION, RemediationError, RemediationRequest, apply

__all__ = ["REQUEST_VERSION", "RemediationError", "RemediationRequest", "apply"]
