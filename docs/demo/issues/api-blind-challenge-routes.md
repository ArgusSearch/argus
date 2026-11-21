# [api] blind challenge routes: commit, state stream, reveal

Labels: api, bench, demo · Owner: bench lane (W) · Blocks: the live blind challenge in Mission Control (A3)

## Why

The blind challenge screens (`web/src/challenge/`, `?challenge` in the URL) work today against a recorded run
(`web/src/challenge/fixtures/blind-11.*`, from `uv run argus-bench blind --seed 11` on main). To let a judge pick
the seed live, the page needs the bench to seal, run and reveal through the API. `POST /challenge/commit` and
`POST /challenge/reveal` answer 501 on main (`src/argus/contracts/events.py`, `ROUTES`).

## Shapes the page needs

All payloads reuse the reserved C5 `ChallengeStatePayload` (`state`, `commitment`, `reveal`) and the fields
`src/bench/blind.py` already writes to `runs/bench/blind-<seed>/challenge.jsonl`.

1. `POST /challenge/commit` with `{"seed": 11}` (or `{}` for a random seed):
   seals the hidden scenario and answers `{"state": "committed", "commitment": "sha256:<64 hex>", "reveal": null}`.
   The commitment is `"sha256:" + hex(SHA-256(nonce + "\n" + payload))` exactly as `src/bench/sealed.py`.
   The seed may be echoed; the scenario must not be.
2. The run streams `challenge_state` events on `GET /events` (`committed`, then `running`), so the banner
   during the run comes from the stream, and Mission Control shows the hidden world live (not the S1 replay).
3. `POST /challenge/reveal` (or a final `challenge_state` with `state: "revealed"`) answers
   `{"state": "revealed", "commitment": ..., "reveal": {"scenario", "seed", "nonce", "payload", "verified", "grade"}}`
   where `payload` is the canonical JSON string byte for byte and `grade` is the `RunGrade` JSON. Please also
   send `grade.passed` (the page mirrors `RunGrade.passed` today; see `passed()` in `web/src/challenge/model.ts`).
4. Optional: `GET /challenge` returning the latest state, so a phone that opens `/?challenge=verify` can load
   the reveal from the laptop instead of the bundled sample.

## Swap point in the web app

`web/src/challenge/sample.ts` (`recordedChallenge()`) is the only loader. When the routes answer 200 it becomes
a fetch with the same return type; the screens do not change.
