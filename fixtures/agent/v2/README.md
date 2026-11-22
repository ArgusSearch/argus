# Agent recordings v2

`accepted.json` is the external pin map for the seed-one S1 and S4 stage
presentations. Firstmate installs the two scenario directories and their
digests after retaining qualified live trials. Until both are present, the
release gate fails and the demo uses the existing v1 presentation.

## Capture and seal

Record with the v2 profile and the target feature set. Retain S4's approval
and independent denial exports in separate directories. Use the same
pre-run memory file for both branches when memory is seeded. Use the
default models and budgets when collecting the release recording.

Use `uv run python -m scripts.agent_eval.archive_trial prepare ARCHIVE s1 1 1`
to generate a trial world and seal its grading truth. Repeat for S1 and S4
at trial indices 1–3. Capture using the command's printed world path.

```sh
ARGUS_AGENT_PROFILE=v2 ARGUS_AGENT_FEATURES=critic,sql,hypotheses \
  uv run argus agent record --world WORLD --out RAW_EXPORT --decide none
```

For S4, record with `--decide approve` and make a separate recording with
`--decide deny`. Each memory-enabled recording starts with its own copy of
the same seed. Use the detective-to-verdict elapsed time for qualification.

Stage and seal the raw live export outside the repository.

```sh
uv run python -m scripts.agent_eval.capture_presentation RAW_EXPORT STAGING \
  --scenario s1 --source-commit SHA --profile v2 \
  --feature critic --feature sql --feature hypotheses
```

For S4, pass `--scenario s4 --denial RAW_DENIAL`. List every enabled feature.
When using seeded memory, include `--feature memory --memory-seed ORIGINAL_JSONL`.
The sealer pins the original memory snapshot and replays with a fresh working
copy. Pass an empty JSONL file to pin an initially empty memory store. Omit
`--memory-seed` when the runtime has no configured memory path. An investigation-only
export follows the same method with `capture_cassette` and no denial. Verify
a presentation or investigation digest with `bundle --digest SHA`; add
`--cassette` for an investigation. Every recorded turn is matched by key
and request digest in order, including the critic's exchange.

Archive each sealed trial with
`uv run python -m scripts.agent_eval.archive_trial finish SLOT --journal RAW_EXPORT --elapsed-seconds SECONDS --capture STAGING --digest SHA`.
Keep failures in their original slots with `--failure REASON`.

After reviewing the artifacts for release, install `s1/` and `s4/` here and
record each emitted seal digest in `accepted.json`. Keep live trial journals
and paid usage archives outside the repository. The presentation runs with
the recorded event stream and supports both S4 operator decisions.

## Release gate

`make agent-eval` checks the 17 established v1 invariants.
`make agent-eval-intel` checks all intelligence evals and requires the two
live pins. If STL was cut, use `CUT_STL=1`. E27 verifies matching evidence
from two fresh replays of each presentation, including the S4 approval and
denial paths. Retain three paid trials per scenario and score the archive
with `make agent-eval-live TRIALS=ARCHIVE PROFILE=v2`. If acceptance pins land
in a separate commit, add `SOURCE_COMMIT=SHA` with the commit that ran the
trials. The demo may use v2 only after both scorecards pass. For the scenario
being shown, set `ARGUS_DEMO_BUNDLE` to its presentation directory and
`ARGUS_DEMO_BUNDLE_SHA` to its accepted digest when starting the demo server.
