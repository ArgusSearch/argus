# Argus Agent (extension contract)

The Argus Agent is an autonomous LLM agent inside the investigation: on an actionable anomaly the model chooses the next check before any verdict, deterministic code runs every check, judges it, gates the verdict and checks every number.
Business actions run only after a human approves them, and every run replays offline from its recording.
Contracts C1 to C6 are unchanged; the agent publishes C4 findings and C5 events through the existing paths (agent metadata rides in `TrailStep.data["agent"]`) and its own records through the routes below.

## Frozen interface

`src/argus/agent/types.py` (interface version `agent-types/1`) holds every type that crosses a lane boundary.
It changes only by request to lane A.
`src/argus/agent/examples.py` builds one example per type from the recorded S1 seed-1 run, and `tests/agent_runtime/test_types.py` keeps them valid.
`src/argus/agent/fake.py` provides `FakeLlmClient` for tests and adversarial recordings.

| Seam | Type or protocol | Owner | Consumer |
| --- | --- | --- | --- |
| Run scope | `RunContext(run_id, stream, through_seq, world_revision, as_of, anomaly_id?, incident_id?, kind, mode)` | A | B, C, D |
| Evidence reference | `ReceiptLink(run_id, world_revision, receipt_id)`; receipt ids are unique only within a run and revision | A | all |
| Tool dispatch | `Dispatcher.specs(kind) -> list[ToolSpec]`, `Dispatcher.dispatch(ctx, name, args) -> Observation` | B | A |
| Observation | `Observation(call_id, tool, args, hypothesis, prediction, expect, outcome, ledger, summary, data, fact_handles, receipt_refs, availability)` | B | A, D, E |
| Number binding | `FactHandle`, `ClaimDraft`, `Verifier.verify(ctx, draft) -> VerifiedClaim \| Rejection` | B | A |
| Proposal | `ProposalService.propose(ctx, incident_id, playbook_id, evidence) -> ProposalView \| Rejection`, `get`, `decide(id, digest, Decision, idempotency_key)` | C | A |
| Proposal state | `ProposalView(id, digest, state, run_id, incident_ref, playbook_id, action, scope, effective_at, expires_at, success_rule, evidence_refs, decision, effect)` | C | A, E, F |
| Activity log | `ActivityRecord(seq, run_id, sim_ts, kind, stage, actor, role, text, ..., observation, receipt_links, model, tokens, usd, gate_action)` | A | D, E, F |
| Runs and spend | `RunSummary`, `GateResult`, `UsageRecord` | A | D, E |
| Provider | `LlmClient.create(LlmRequest) -> LlmResponse`; live, recording and replaying clients | A | D |

Rules every implementation keeps:

- The model never types a number into findings or reports: it cites fact handles or receipts, and the host renders figures.
- Prose that still contains numbers passes the number check (`argus.agent.numbers`): every number must come from a receipted tool result of the run, and every sentence with a number carries a receipt tag.
- The verdict is admitted by the deterministic gate (freshness and identities, localisation, a validated holdout or control for the named event, a non-recurring placebo, explained share at least 0.20); anything less is downgraded with the check that would upgrade it.
- Any agent failure (budget, provider error, gate) falls back to the Stage-2 investigator in the same tick; quiet hours call no model; the bench runs Stage 2 and stays 18 of 18.
- No tool accepts SQL, a shell, a path or an approval; the model never sees credentials; actuator parameters come from the admitted incident, never from prose.
- Times are naive UTC simulated time; a model's `...Z` timestamps are normalised before validation.
- `ActivityRecord.role` names the avatar (watcher, detective, skeptic, market, narrator, operator, cartographer); the journal derives it from kind, tool and actor when the writer does not set it.
- Model-written activity text carries only numbers a receipted result of the run backs; others read `[unverified]`.

## State machine

| State | Transition |
| --- | --- |
| `WATCH -> TRIAGE` | Each tick; quiet hours end here with a `watch` record and no model call. |
| `TRIAGE -> PLAN` | An actionable anomaly: the existing data, calendar and market checks run first; the case packet is built. |
| `PLAN -> ACT -> OBSERVE -> PLAN` | The model names a hypothesis and a prediction, picks one check; the host journals the prediction, dispatches, returns the observation and the remaining budget. |
| `OBSERVE -> VERIFY -> REPORT` | The gate admits a verdict; C4 findings and C5 steps go out through `on_step` and `IncidentBook.record`. |
| `REPORT -> PROPOSE -> AWAIT_OPERATOR` | A supported, eligible case yields an immutable proposal; the watcher keeps running. |
| `AWAIT_OPERATOR -> ...` | `DENIED`, `EXPIRED` or `APPLYING -> APPLIED -> VERIFYING -> VERIFIED \| NO_EFFECT \| INCONCLUSIVE`, driven by the operator and lane C. |
| `ASK -> PLAN -> ACT -> VERIFY -> ANSWER` | A human question: same dispatcher and number check, read-only, its own budget; a chat message never authorises an action. |

## Modes

| Mode | Provider | Used by |
| --- | --- | --- |
| `live` | Anthropic Messages API (`claude-sonnet-5-5` for the loop, `claude-opus-5-5` for one final synthesis) | `ARGUS_AGENT=live` with `ANTHROPIC_API_KEY` |
| `record` | live, plus the recording | re-recording fixtures (needs the key, appends to the spend ledger) |
| `replay` | none is constructed | the demo, CI, evals |
| `off` | none | default without a key; Stage 2 only |

Cost: every provider call becomes a `UsageRecord` priced from one tariff table (cache tiers included); each finished run appends one line per model to the JSONL ledger named by `ARGUS_SPEND_LEDGER` as `{"provider": "anthropic", "model": ..., "usd": ...}`; a replay appends nothing.

## Routes

All routes sit outside the C5 `ROUTES` tuple, mounted like the narrator and demo routers.

| Route | Returns |
| --- | --- |
| `GET /agent/health` | `{enabled, mode, models, caps, usd}`; a feature probe for the web |
| `GET /agent/activity?since=<seq>` | `{stream, mode, records: [ActivityRecord]}`, ordered by `seq` |
| `GET /agent/runs` | `[RunSummary]` |
| `GET /agent/actions`, `GET /agent/actions/{id}` | `ProposalView` |
| `POST /agent/actions/{id}/approve`, `POST /agent/actions/{id}/deny` | `{digest, idempotency_key}`; the `ProposalView`; 409 when stale or decided, 404 when unknown |
| `POST /agent/ask` | `{question, incident_id?, conversation_id?}` -> `{status, answer, claims, receipt_links, activity_cursor}` |
| `GET /agent/receipts/{run_id}/{world_revision}/{receipt_id}` | the receipt behind a `ReceiptLink` |

## Examples

One redacted example per type, rendered from `src/argus/agent/examples.py`.

### RunContext

```json
{
 "run_id": "run_0001",
 "stream": "9f3c2a1b",
 "through_seq": 125,
 "world_revision": "factual",
 "as_of": "2026-11-21T20:00:00",
 "anomaly_id": "an_0001",
 "incident_id": null,
 "kind": "investigate",
 "mode": "replay"
}
```

### ReceiptLink

```json
{
 "run_id": "run_0001",
 "world_revision": "factual",
 "receipt_id": "a7"
}
```

### ToolSpec

```json
{
 "name": "holdout_check",
 "description": "Is the event's scope outside the anomalous segment normal? Runs SQL with a receipt.",
 "input_schema": {
  "type": "object",
  "properties": {
   "event": {
    "type": "object"
   },
   "node": {
    "type": "string"
   }
  }
 },
 "kinds": [
  "investigate",
  "ask"
 ]
}
```

### FactHandle

```json
{
 "id": "f:run_0001:run_0001:2:1",
 "label": "payment_success_rate DE/android/PayCo 18:00, observed",
 "value": 0.607383,
 "unit": "ratio",
 "receipts": [
  {
   "run_id": "run_0001",
   "world_revision": "factual",
   "receipt_id": "a2"
  }
 ]
}
```

### Observation

```json
{
 "call_id": "run_0001:2",
 "tool": "holdout_check",
 "args": {
  "node": "payment_success_rate",
  "segment": {
   "country": "DE",
   "platform": "android",
   "provider": "PayCo"
  },
  "window": {
   "start": "2026-11-21T18:00:00",
   "end": "2026-11-21T18:00:00"
  }
 },
 "hypothesis": "The Android release 8.3.0 caused the drop",
 "prediction": "Android outside DE/PayCo also drops",
 "expect": "consistent",
 "outcome": "refuted",
 "ledger": null,
 "summary": "holdout normal: -0.1% (z -0.4) outside the segment vs -34.3% inside",
 "data": {
  "rel_change": -0.001,
  "z": -0.4,
  "result": "refuted"
 },
 "fact_handles": [
  {
   "id": "f:run_0001:run_0001:2:1",
   "label": "payment_success_rate DE/android/PayCo 18:00, observed",
   "value": 0.607383,
   "unit": "ratio",
   "receipts": [
    {
     "run_id": "run_0001",
     "world_revision": "factual",
     "receipt_id": "a2"
    }
   ]
  }
 ],
 "receipt_refs": [
  {
   "run_id": "run_0001",
   "world_revision": "factual",
   "receipt_id": "a7"
  }
 ],
 "availability": "ok"
}
```

### ClaimDraft

```json
{
 "kind": "observed",
 "subject": "payment_success_rate",
 "segment": {
  "country": "DE",
  "platform": "android",
  "provider": "PayCo"
 },
 "window": {
  "start": "2026-11-21T18:00:00",
  "end": "2026-11-21T18:00:00"
 },
 "fact_ids": [
  "f:run_0001:run_0001:2:1"
 ],
 "text": "payment success in the segment"
}
```

### VerifiedClaim

```json
{
 "claim_id": "c:run_0001:1",
 "kind": "observed",
 "subject": "payment_success_rate",
 "segment": {
  "country": "DE",
  "platform": "android",
  "provider": "PayCo"
 },
 "window": {
  "start": "2026-11-21T18:00:00",
  "end": "2026-11-21T18:00:00"
 },
 "as_of": "2026-11-21T20:00:00",
 "world_revision": "factual",
 "value": 0.607383,
 "unit": "ratio",
 "display": "Payment success in DE / android / PayCo was 0.607 at 18:00 [a2].",
 "receipts": [
  {
   "run_id": "run_0001",
   "world_revision": "factual",
   "receipt_id": "a2"
  }
 ]
}
```

### Rejection

```json
{
 "reason": "missing_check",
 "detail": "no placebo_test for the root segment",
 "upgrade": "placebo_test on DE/android/PayCo"
}
```

### ProposalView

```json
{
 "id": "act_0001",
 "digest": "sha256:0f1e...",
 "state": "AWAIT_OPERATOR",
 "run_id": "run_0001",
 "incident_ref": "INC-0001",
 "playbook_id": "rollback_pacer",
 "action": "Roll the ad pacer back from 1.7.0 for the DE and FR budget lines from 2026-11-21 00:00.",
 "scope": {
  "country": [
   "DE",
   "FR"
  ]
 },
 "effective_at": "2026-11-21T00:00:00",
 "expires_at": "2026-11-21T02:00:00",
 "success_rule": {
  "node": "pacing_ratio",
  "scope": {
   "country": [
    "DE",
    "FR"
   ]
  },
  "rule": "|ratio - 1| <= 0.15 and gap at most half the untreated twin's, 3 complete hours",
  "hours": 3,
  "comparator": "untreated_twin"
 },
 "evidence_refs": [
  {
   "run_id": "run_0001",
   "world_revision": "factual",
   "receipt_id": "r184"
  }
 ],
 "decision": null,
 "effect": null
}
```

### Decision

```json
{
 "decision": "approve",
 "principal": "operator",
 "at": "2026-11-20T03:00:00"
}
```

### EffectResult

```json
{
 "state": "VERIFIED",
 "checked_at": "2026-11-21T05:00:00",
 "summary": "DE/FR pacing back in band for 3 hours",
 "claims": [],
 "receipt_refs": [
  {
   "run_id": "run_0001",
   "world_revision": "factual",
   "receipt_id": "a31"
  }
 ]
}
```

### ActivityRecord

```json
{
 "seq": 7,
 "run_id": "run_0001",
 "sim_ts": "2026-11-21T20:00:00",
 "kind": "tool_result",
 "stage": "OBSERVE",
 "actor": "host",
 "text": "holdout normal: -0.1% (z -0.4) outside the segment vs -34.3% inside [a7]",
 "anomaly_id": "an_0001",
 "incident_id": "INC-0001",
 "action_id": null,
 "tool": "holdout_check",
 "args": null,
 "observation": {
  "call_id": "run_0001:2",
  "tool": "holdout_check",
  "args": {
   "node": "payment_success_rate",
   "segment": {
    "country": "DE",
    "platform": "android",
    "provider": "PayCo"
   },
   "window": {
    "start": "2026-11-21T18:00:00",
    "end": "2026-11-21T18:00:00"
   }
  },
  "hypothesis": "The Android release 8.3.0 caused the drop",
  "prediction": "Android outside DE/PayCo also drops",
  "expect": "consistent",
  "outcome": "refuted",
  "ledger": null,
  "summary": "holdout normal: -0.1% (z -0.4) outside the segment vs -34.3% inside",
  "data": {
   "rel_change": -0.001,
   "z": -0.4,
   "result": "refuted"
  },
  "fact_handles": [
   {
    "id": "f:run_0001:run_0001:2:1",
    "label": "payment_success_rate DE/android/PayCo 18:00, observed",
    "value": 0.607383,
    "unit": "ratio",
    "receipts": [
     {
      "run_id": "run_0001",
      "world_revision": "factual",
      "receipt_id": "a2"
     }
    ]
   }
  ],
  "receipt_refs": [
   {
    "run_id": "run_0001",
    "world_revision": "factual",
    "receipt_id": "a7"
   }
  ],
  "availability": "ok"
 },
 "receipt_links": [
  {
   "run_id": "run_0001",
   "world_revision": "factual",
   "receipt_id": "a7"
  }
 ],
 "model": null,
 "input_tokens": null,
 "output_tokens": null,
 "usd": null,
 "gate_action": null
}
```

### UsageRecord

```json
{
 "run_id": "run_0001",
 "call_index": 1,
 "provider": "anthropic",
 "model": "claude-sonnet-5-5",
 "request_id": "req_redacted",
 "input_tokens": 5329,
 "output_tokens": 412,
 "cache_read_tokens": 12388,
 "cache_write_tokens": 0,
 "usd": 0.01065,
 "tariff": "anthropic-2026-11",
 "stop_reason": "tool_use",
 "wall_ms": 3120
}
```

### RunSummary

```json
{
 "run_id": "run_0001",
 "kind": "investigate",
 "mode": "replay",
 "sim_ts": "2026-11-21T20:00:00",
 "anomaly_id": "an_0001",
 "incident_id": "INC-0001",
 "status": "done",
 "stop_reason": null,
 "llm_calls": 6,
 "tool_calls": 9,
 "input_tokens": 48881,
 "output_tokens": 4833,
 "usd": 0.1096,
 "gate": {
  "claimed": "SUPPORTED_CAUSE",
  "admitted": "SUPPORTED_CAUSE",
  "reasons": []
 },
 "fallback": null
}
```

### LlmRequest

```json
{
 "model": "claude-sonnet-5-5",
 "system": "You are Argus Agent ...",
 "tools": [
  {
   "name": "holdout_check",
   "description": "Is the event's scope outside the anomalous segment normal? Runs SQL with a receipt.",
   "input_schema": {
    "type": "object",
    "properties": {
     "event": {
      "type": "object"
     },
     "node": {
      "type": "string"
     }
    }
   }
  }
 ],
 "messages": [
  {
   "role": "user",
   "content": "Case INC-0001 ..."
  }
 ],
 "max_tokens": 4000,
 "key": "investigate:an_0001:1"
}
```

### LlmResponse

```json
{
 "model": "claude-sonnet-5-5",
 "content": [
  {
   "type": "text",
   "text": "The release went to every country; if it caused this, Android elsewhere drops too."
  },
  {
   "type": "tool_use",
   "id": "toolu_redacted",
   "name": "holdout_check",
   "input": {
    "node": "payment_success_rate"
   }
  }
 ],
 "stop_reason": "tool_use",
 "usage": {
  "input_tokens": 5329,
  "output_tokens": 412,
  "cache_read_input_tokens": 12388,
  "cache_creation_input_tokens": 0
 },
 "request_id": "req_redacted"
}
```
