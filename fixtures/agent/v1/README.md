# Agent recordings v1

Use one directory per scenario, for example `fixtures/agent/v1/s4/`. Capture the
provider exchange and presentation export from the same run. Keep synthetic tests
outside the accepted scenario directories.

## Provider exchange

Lane A owns the provider adapter, request hash and cassette matcher. Each line of
`turns.jsonl` is one completed `LlmClient.create` exchange in capture order.
It contains `key`, `request_sha`, and the frozen `LlmResponse` under `response`.
The key is `<kind>:<subject>:<round>`. The request digest uses the adapter's
`sha256:<hex>` format. The hash covers the model, prompt, tool
schemas and ordered messages after normalizing provider tool IDs. The response
preserves the returned model, stop reason, token usage and visible text/tool calls.
Use deterministic tool IDs and omit provider request IDs and private reasoning.
Keep credentials, HTTP headers, hidden grading truth and full request bodies out of
every fixture. The evaluator can match observations and receipt hashes against
the activity and receipt exports.

## Presentation export

Lane F owns export and playback. The root contains the common prefix. S4 ends its
prefix when the rollback is pending. Decision directories `approve/` and `deny/`
extend this prefix. A decision must come from the operator before playback can
consume either directory. Event and activity sequence numbers stay monotonic across
the prefix and its chosen continuation.

| File | Contents |
| --- | --- |
| `events.jsonl` | C5 Event objects in sequence order |
| `activity.jsonl` | Frozen ActivityRecord objects in sequence order |
| `actions.json` | ProposalView array representing the latest state in this prefix or continuation |
| `receipts.json` | Object keyed by ReceiptLink.key(), with entries `{receipt, columns, rows, verified_at_capture}`. Each receipt is C4, columns name the cells in the bounded row sample, and verification means a pinned rerun matched. |
| `ask.jsonl` | Frozen Ask response paired with its question and visibility cursor, `{question, through_seq, response}` |
| `graph.json` | C2 Graph captured for the session, shared across both continuations |
| `incidents.json`, `notes.json` | C4 snapshots for the emitted prefix, when needed by the source |

The receipt map may also use unqualified C4 receipt IDs for C5 links, with the same
proof shape. Only expose receipts referenced by the current visible prefix.
Decision directories can add receipts, Ask records, and snapshots as needed.
Replays return the recorded proof labelled “verified at capture.” A matching local
world is required to offer a rerun.

## Manifest and modes

`manifest.json` contains `schema_version: 1`, `provenance` (`live_capture` or
`synthetic_test`), `source_commit` (full Git SHA), `scenario`, `seed`,
`interface_version`, `prompt_sha`, `tools_sha`, `models` (returned model IDs),
`world` (public generation settings), `graph_sha`, `artifacts` (relative path to
SHA-256 over exact bytes), and `bundle_sha` (SHA-256 over canonical JSON of all
other manifest fields). Digests are lowercase hex. Canonical JSON is UTF-8 with
keys sorted, compact separators, and non-ASCII preserved. Acceptance receives
the expected bundle digest separately.

Seal a staged capture with `uv run python -m scripts.agent_eval.bundle /path/to/staging --seal`.
Once the real cassette dispatch and event playback pass, install the bundle in
its scenario directory and add its digest to `accepted.json`, an object mapping
`"s1"` and `"s4"` to their seed-one bundle hashes. Include the C4 incident snapshot
in each root and the resolved snapshot in the S4 approval continuation for grading.

The initial live investigations are sealed separately under `cassettes/{s1,s4}/`,
with independent pins in `cassettes/accepted.json`. They include the live
provider exchange, activity, C4/C5 exports, and the graph and receipt proofs
recovered by a strict cold replay. Use
`uv run python -m scripts.agent_eval.capture_cassette RAW_EXPORT STAGING --scenario s4 --source-commit SHA`
to rebuild an investigation cassette. A cassette has no operator decision or
recorded Ask, so a full presentation requires a separate release bundle.

1. Strict cassette replay matches the next key and request hash and dispatches
   real tools on the matching world. A miss fails offline with the first bad turn.
2. Lenient cassette replay accepts a known key with a changed request hash and
   records drift. A missing key triggers same-tick Stage 2 fallback.
3. Event replay serves the verified bundle without constructing a provider or
   generating a world. On S4, it stops at the approval cut until the operator
   decides. Seek and reconnect follow the same visibility rules.

## Release evidence

`make agent-eval` writes a JUnit report and a scorecard for all 17 deterministic
invariants. A skipped, absent or failed case keeps the release gate red. Results
carry the checked-out commit. `make bench` separately checks the Stage 2 grades,
the scorecard totals, and the original commitment and reveal for every case.

Run `make agent-eval-live TRIALS=/path/to/trials` against the retained live archive
from the release commit. Store each attempt under `{scenario}-{seed}-{trial}/`
for S1/S4, seeds 1/3/7, trials 1/2/3. Each directory has `trial.json` with
`scenario`, `seed`, `trial`, `source_commit`, `elapsed_seconds`, `bundle_sha`,
sealed Stage 3 `grade`, frozen run summaries under `runs`, and billed
`UsageRecord` entries under `usage`. Completed attempts provide their own sealed
`bundle/`. Retain failed attempts in their original slots with `failure`.
Use `uv run python -m scripts.agent_eval.archive_trial prepare ARCHIVE s4 1 1`
to seal an independent world before the live session. After capture,
`uv run python -m scripts.agent_eval.archive_trial finish SLOT --journal JOURNAL --elapsed-seconds SECONDS --capture BUNDLE --digest SHA`
grades the recorded findings against the pre-run seal and attaches metered usage.
Record a failed run with `--failure REASON` in place of the capture and digest.
Include `counterexample.json` with the original and changed observations and
their genuine next responses. The scorecard requires three passes for stage S4
and at least five of six scenario/seed groups, with median spend at most
USD 0.25, max USD 0.50, and median investigation time at most 60 seconds.
`TEXT_REVIEW=/path/to/text-review.json` optionally adds blinded prose scores
to the report. Generate the scores with
`uv run python -m scripts.agent_eval.text_review SAMPLES --out REVIEW`, using a
JSON array of opaque `sample` IDs and redacted `text` strings. Text scores are
reported separately from the stage eligibility checks.
