# Remediation: approved actions that change only the simulated future

Argus can propose one business action, an operator approves or denies it, the simulator applies it, and Argus checks the effect against an untouched twin of the world.
The action is `rollback_pacer`: put the budget lines that ad-pacer 1.7 broke back on pacer 1.6 (scenario S4).
The model never reaches any of this directly: it may ask for a proposal, but every parameter comes from the admitted incident and the world, the decision comes from an authenticated operator, and execution and verification run on the simulated clock.

Owner: lane C (`src/argus/remediation/`, `src/mockmart/remediation/`, `tests/remediation/`).
Frozen types: `ProposalView`, `SuccessRule`, `EffectResult`, `Decision` and the `ProposalService` protocol in `src/argus/agent/types.py`.

## Lifecycle

```
propose -> AWAIT_OPERATOR --deny--> DENIED
               |   \--clock passes expires_at, or the incident resolved--> EXPIRED
            approve (operator session, matching digest, before expires_at)
               v
            APPLYING --simulator--> APPLIED --clock reaches effective_at--> VERIFYING
                                                                              |
                     twin contrast holds and the incident resolved -> VERIFIED
                     the action changed nothing or pacing stayed off plan -> NO_EFFECT
                     data missing, worlds not comparable, no recovery by the deadline -> INCONCLUSIVE
```

A simulator refusal also ends in `INCONCLUSIVE`, with an effect summary starting `not applied:`, because the frozen state list has no failure state.

## Timing

All times are simulated, naive UTC.

| Field | Rule | S4 seed 1 |
| --- | --- | --- |
| `effective_at` | the first 00:00 at least one hour after the proposal: a new budget day never redistributes a budget already spent | proposal at 2026-11-20 02:00 -> 2026-11-21 00:00 |
| `expires_at` | `effective_at - 1h`: the last moment an approval is accepted | 2026-11-20 23:00 |
| switch deadline | the runtime must read the treated world before `effective_at + 1h`, because the first batch of the effective hour lands at `effective_at + 1h05` | 2026-11-21 01:00 |
| verdict | when the 3 hours from `effective_at` are complete in both worlds (`effective_at + 4h` with the 2-hour lag), and the incident lifecycle has resolved | 2026-11-21 04:00 |
| deadline | `effective_at + 12h`: without a verdict by then the effect is `INCONCLUSIVE` | 2026-11-21 12:00 |

`holds_clock()` is true while a proposal waits for an operator or for the simulator.
A source that paces the clock (live or replay) should pause on it, so the approval lands in the same simulated hour on every run and the switch never races the clock.

## The simulator command

```
python -m mockmart.remediation apply --request <request.json>
```

Argus never imports `mockmart`; like the counterfactual replay it calls this fixed command in a subprocess with a request file it wrote itself.

```json
{
  "version": "remediation-request/1",
  "action": "rollback_pacer",
  "world": "<directory of the factual world>",
  "out": "<empty staging directory>",
  "countries": ["DE", "FR"],
  "to_version": "1.6",
  "effective_at": "2026-11-21T00:00:00",
  "decided_at": "2026-11-20T03:00:00",
  "action_id": "act_0001",
  "digest": "sha256:..."
}
```

The simulator rebuilds the world's causal parameters from its own configuration (the world's `truth.duckdb` and manifest, which Argus never reads), checks that they reproduce the world's deploy and budget logs, and refuses otherwise.
Every requested budget line whose pacer at `effective_at` is not 1.6 gets its pre-rollout delivery profile back from that hour on.
Only those lines' `fact_ads_hourly` rows with `ts >= effective_at` are re-drawn, with the simulator's own ads sampler and micro-batch delivery and a generator seeded by the world seed and the action's typed content.
One `log_deploys` row (`dep_ad-pacer_1.6.0_rollback_<id>`) and one `log_ad_budgets` `pacer_change` row per line are logged at `effective_at`.
Every other row of every table is copied unchanged, so any query at an `as_of` before `effective_at` returns the same rows on both worlds.
Lines already on pacer 1.6 (for example `"countries": ["UK"]`) make the action a no-op: the treated world equals the factual one and the effect reads `NO_EFFECT`.

The output directory holds `world.duckdb`, `manifest.json` (unchanged), the simulator's private `truth.duckdb`, and `remediation.json`, the execution manifest (`noop`, `lines`, `rows`, `log_rows`, `digest`).
A refusal prints `{"error": ...}` and exits 2.
A treated branch is never remediated again.

## Proposal

`RemediationService.propose(ctx, incident_id, "rollback_pacer", evidence)` returns a `ProposalView` or a `Rejection`.
It needs a `SUPPORTED_CAUSE` incident whose root is `pacing_ratio` or `ad_spend` and whose cited evidence is an ad-pacer deploy (or the grouped `pacer_change` rows), evidence links from the same run and world revision, and the factual world revision.
The countries and the version come from that log row in the world, read with a receipt (`act_0001/factual/e1`).
The same incident, scope and effective hour always yield the same proposal, so a runtime that re-runs after a restart gets the original back.
The digest covers the run, the world revision, the world identity, the incident and its fingerprint, every evidence link, the deploy receipt's hash, the playbook, scope, versions, `effective_at`, `expires_at` and the success rule.

## Effect

The success rule is fixed before approval (`SuccessRule`, comparator `untreated_twin`).
Over the first 3 complete hours from `effective_at`, pacing in scope (spend / planned spend, ratio of sums) must be within 0.15 of 1 in every hour, and its gap from 1 at most half the untreated twin's.
The untreated gap must be at least 0.20, and the ads rows outside the scope must hash the same in both worlds.
A treated series identical to the untreated one is `NO_EFFECT`.
`VERIFIED` additionally needs the incident lifecycle to resolve the incident on the treated world (three consecutive calm hours of the root segment).

Every number is a receipt in the proposal's own namespace: `ReceiptLink(run_id=<proposal id>, world_revision="factual" | "<proposal id>-treated", receipt_id="e<n>")`.
`EffectResult.claims` holds two `VerifiedClaim`s (treated `recovered`, untreated `observed`) and `receipt_refs` holds the treated, untreated and both control receipts plus the pre-action receipt.
The pre-action receipt (pacing in scope over the 24 complete hours before the decision) is re-run on the treated branch at apply time; the same hash is the proof that the past did not change.
`service.receipt(link)` and `service.rerun(link)` resolve and re-run any of them on its own world.

## Operator routes

`create_router(service)` serves:

| Route | Body | Returns |
| --- | --- | --- |
| `POST /agent/operator/session` | - | `{principal, csrf_token}` and an HttpOnly, SameSite=Strict cookie on `/agent`; 403 unless the client is local |
| `GET /agent/actions` | - | `[ProposalView]` |
| `GET /agent/actions/{id}` | - | `ProposalView`, 404 when unknown |
| `POST /agent/actions/{id}/approve` | `{digest, idempotency_key}` | `ProposalView` |
| `POST /agent/actions/{id}/deny` | `{digest, idempotency_key}` | `ProposalView` |

A decision needs the session cookie and the token in the `X-Argus-CSRF` header, and a browser `Origin`, when sent, must be local or the API's own host: 403 otherwise.
The principal comes from the session; a body naming one is rejected (422).
A retry with the same decision, digest and `idempotency_key` returns the current view and runs nothing again.
A different key on a decided proposal, a stale digest, an expired proposal or a resolved incident answer 409.
An approval answers with the proposal in `APPLYING`; poll `GET /agent/actions/{id}` for `APPLIED` and the verdict.

## Wiring it into a run (lane A)

```python
from argus.remediation import RemediationService, create_router

service = RemediationService.for_runtime(runtime, publish=on_remediation_event)
app.include_router(create_router(service))
# after every Runtime.tick(as_of):
service.tick(as_of)
```

`for_runtime` reads incidents from `runtime.book` and the clock from `runtime.as_of`, and switches `runtime.runner` to the treated world under `runtime.lock` (`switch_world`).
The detector, edge tester, watcher and incident book share that runner, so they all follow; receipts minted before the switch keep re-running to the same hash.
`publish` receives a `RemediationEvent` (`action_proposed`, `action_decided`, `action_applied`, `effect_checked`) with the current `ProposalView` and its receipt links; lane A turns it into an `ActivityRecord`.

State lives in SQLite at `<world dir>/remediation/<world identity>/actions.sqlite`, with the treated branches under `branches/`.
Every transition is a conditional update with a journal row, so concurrent approvals execute exactly once.
On start the service reopens that state: an execution interrupted in `APPLYING` is finished (a published branch with the same digest is reused), and the runtime is pointed at the applied branch.
A restarted live run replays from the start of the live window on the treated world, which is safe because its past equals the factual one.

## Lifecycle calm test

`IncidentBook.monitor` judges a ratio of amounts such as pacing (unit `ratio`, not `share`) by its relative change against a 6% noise scale (`calm_z`).
`Cell.z` gave such a ratio a binomial variance whenever it dipped just below 1, so healthy pacing hours read as abnormal a third of the time and a recovered pacing incident never resolved.
Shares (payment success rate, S1) keep `Cell.z` unchanged.

## Tests

`tests/remediation/`: the simulator (only future DE/FR ads rows change, every pre-effective view reads the same, determinism, no-op, refusals), the service (derivation, rejections, denial, retries, stale and expired approvals, concurrent clicks, restart during apply), the routes (session, CSRF, origin, 403/404/409/422) and S4 end to end (`e2e`: approve, apply, `VERIFIED` against the twin at 2026-11-21 04:00 with the incident resolved, while the untouched twin's incident stays open).
