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
- The number check (`argus.agent.numbers`) requires each measured number in a sentence to match a tool result from a receipt cited in that sentence.
- The deterministic gate admits a supported cause after freshness and identity checks, localisation, a validated holdout or control for the named event, a validated non-recurring historical placebo, and an explained share of at least 0.20. Missing or inconclusive history blocks confirmation, and the finding names the check needed to confirm the cause.
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
| `live` | OpenAI Responses (GPT‑6.2 Sol) or Anthropic Messages (Claude Sonnet) chooses checks and answers questions. The verdict comes from the evidence gate. | `ARGUS_AGENT=live` with a provider key |
| `record` | live, plus the recording | re-recording fixtures (needs the key, appends to the spend ledger) |
| `replay` | none is constructed | the demo, CI, evals |
| `off` | none | default without a key; Stage 2 only |

Set `ARGUS_PROVIDER=openai` or `ARGUS_PROVIDER=anthropic` to select a provider explicitly. With the setting omitted, the live agent tries `OPENAI_API_KEY` first, then `ANTHROPIC_API_KEY`. Both keys can come from the process environment or the repository's git-ignored `.env`. If the selected provider has no configured key, `/agent/health` reports why the agent is disabled.

For the OpenAI v2 critic, Argus checks the provider's model listing and uses GPT‑6.2 Astra when available. Otherwise the critic starts a fresh GPT‑6.2 Sol session with the critic prompt and evidence packet. The session recording stores the critic choice so strict replay can use it offline. The Anthropic synthesis model setting is reserved.

Metered calls produce a `UsageRecord`. OpenAI costs use Standard rates for [GPT‑6.2 Sol](https://developers.openai.com/api/docs/models/gpt-6.2-sol) and [GPT‑6.2 Astra](https://developers.openai.com/api/docs/models/gpt-6.2-astra), including cached reads and 30-minute cache writes. Each finished live run appends one line per model to `ARGUS_SPEND_LEDGER` with its provider, token counts and cost. Replay computes costs from the recorded usage and leaves the spend ledger alone.

## Routes

All routes sit outside the C5 `ROUTES` tuple, mounted like the narrator and demo routers (`src/argus/agent/routes.py`).

| Route | Returns |
| --- | --- |
| `GET /agent/health` | `{enabled, mode, reason, interface_version, models, caps, runs, usd, profile, features, board_version}` |
| `GET /agent/activity?since=<seq>` | `{stream, mode, records: [ActivityRecord], next_cursor}`, ordered by `seq` |
| `GET /agent/runs` | `[RunSummary]` |
| `GET /agent/boards?since=<seq>` | `{boards: [Board], next_cursor}` with a snapshot of every visible agent investigation |
| `GET /agent/boards/incident/{incident_id}` | The incident's `Board`, including Stage 2 when the agent is off. Returns 404 until the incident is visible. |
| `POST /agent/ask` | `{question, incident_id?, conversation_id?}` -> `{status, run_id, conversation_id, answer, claims, receipt_links, reason, usd, activity_cursor}`; 404 for an unknown conversation, 409 when the agent is off |
| `GET /agent/receipts/{run_id}/{world_revision}/{receipt_id}` | the receipt behind a `ReceiptLink`; only in the run and revision that minted or cited it |
| `POST /agent/operator/session` | lane C: `{principal, csrf_token}` plus a session cookie; local clients only |
| `GET /agent/actions`, `GET /agent/actions/{id}` | lane C: `ProposalView` |
| `POST /agent/actions/{id}/approve`, `POST /agent/actions/{id}/deny` | lane C: `{digest, idempotency_key}` with the session cookie and `X-Argus-CSRF`; the `ProposalView`; 409 when stale or decided |

Ask runs with its own `RunContext`, a read-only runner with its own receipt namespace (`q1`, `q2`, ...) and a session in lane B's `EvidenceStore`.
The model finishes with prose without digits plus claims that cite fact handles; the host verifies every claim and renders its figure with its receipt.
Ask retries once when the model puts digits in prose. If the model repeats the error, Ask masks the digits and returns the verified claims that remain. If no verified claim remains, the response has status `refused`.
A follow-up with the same `conversation_id` keeps the incident scope and sees the earlier turns as context, never as evidence.
After an approved action is applied, the run, its investigations and Ask read the treated branch (`world_revision` `<action id>-treated`).

## Investigation board

`agent-board/1` derives the hypotheses, step groups, discarded paths, cause chain and cost from the activity and findings already available. The board runs without a provider or a recording step. Profile `stage2` uses the incident's findings. Profile `v1` also works with the sealed S1 and S4 presentations. Activity emitted by profile `v2` can supply declared hypotheses, critic results and precedents. Clients should display unfamiliar activity kinds as plain activity lines.

Pass `run_id=<playback>` to read either board route at the presentation's current position. The list returns full snapshots, including when `since` equals `next_cursor`, because findings can become visible independently of activity. `next_cursor` is the greatest board activity sequence or the supplied `since`, whichever is greater. `through_seq` identifies the final activity record included in an individual board and is zero for a Stage-2-only board.

For example, the sealed S1 board names PayCo as supported and the Android release as ruled out. The release card's `holdout_check` cites `run_0001/factual/r240` through `/agent/receipts`. Step groups expand to activity by their `first_seq` and `last_seq`, and `cost.replayed` marks spend from the recording. Cause chains cite the admitted event, localisation, formula steps and impact. When an incident lists a silenced symptom without a symptom-specific check, the link is `untested` and cites the supporting root evidence.

## Running it

| Command | What it does |
| --- | --- |
| `uv run argus api --world runs/s4-1/world.duckdb --agent live` | live run with the agent and its configured provider. The clock holds while an action waits for the operator. |
| `uv run argus agent record --world W --out DIR [--decide approve\|deny\|none] [--ask 'YYYY-MM-DDTHH:MM\|question' ...] [--incident ID]` | a live session over a world, recorded: `turns.jsonl` (lane D's line format), `activity.jsonl`, `events.jsonl`, `runs.json`, `usage.jsonl`, `incidents.json`, `ask.jsonl`, `session.json` |
| `uv run argus agent replay --world W --recording DIR` | the same session again from its turns, no provider constructed; prints the first difference, exit 1 on any |

`ARGUS_AGENT` (`live`, `record`, `off`) sets the default mode, `ARGUS_SPEND_LEDGER` names the JSONL spend ledger, and `ARGUS_AGENT_MAX_*` and `ARGUS_ASK_MAX_*` override the budgets.
Budgets per investigation: 10 model requests, 12 tool calls, 150,000 input and 12,000 output tokens, USD 0.50, 120 seconds; per question: 6 requests, 8 tool calls, USD 0.25.

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
