# QA baseline

## Current base: `main` @ `f35b00a` (Saturday ~18:00 CET)

| Command | Result |
| --- | --- |
| `make setup` | ok |
| `make check` | **red at lint**: `ruff format --check` flags `docs/plan/build-plan.md:2238` (#27). CI on main fails the same way. |
| `make typecheck contracts-check web test` | mypy `no issues found in 96 source files`, contracts fresh, web 19 vitest tests and the build ok, pytest `273 passed` in 6:22 |
| `make s1` | `ALL PASS` (six PASS lines; 21 receipts re-run, 0 mismatched) |
| `uv run argus-bench` | Argus pass@1 100% vs threshold 20% (see matrix.md) |

## First baseline: `fm/argus-api` @ `437fff5`

Run by Ansor's agent on Saturday 2026-11-21, 16:10–16:40 CET, macOS 26 (Darwin 25.5, Apple silicon, 8 GB RAM).
Tool versions: uv 0.11.7 (Python 3.13.1 from the lock), Node v26.13.0, npm 11.20.0, Playwright 1.65.1 (Chromium for Testing 159).

## Base: `origin/fm/argus-api` @ `437fff5`

| Command | Result | Time |
| --- | --- | --- |
| `make setup` | ok, locked environment installed | 6.5 s |
| `make check` (before `web/node_modules` existed) | ruff ok, `80 files already formatted`, mypy `no issues found in 58 source files`, contracts fresh, pytest `79 passed, 2 skipped` (the 2 skipped are the web checks) | 38 s |
| `make s1` (seed 7) | six `PASS` lines (supported_cause, release_ruled_out, detected_within_3h, quiet_hours_silent, one_incident, receipts_reproducible) and `ALL PASS` | 5.5 s |
| `npm --prefix web install` | ok; warns that `fsevents@2.3.3` has install scripts not covered by `allowScripts` (harmless on macOS) | 2 s |
| `npm --prefix web run typecheck` | ok | <1 s |
| `npm --prefix web test` | `8 passed (8)`, 1 file | <1 s |
| `npm --prefix web run build` | ok; two known warnings: main chunk larger than 500 kB, and `MODULE_LEVEL_DIRECTIVE "use no memo"` in `react-compiler-runtime` | <1 s |
| `make api` | serves `http://127.0.0.1:8000`; `GET /health` → `status ok`, `mode replay`, replay `loop: true`, 171 events; replay starts playing by itself at 1× | — |
| `GET /routes` + stub calls | the six stub routes (`POST /metrics`, `POST /chaos/inject`, `POST /challenge/commit`, `POST /challenge/reveal`, `GET /bench/results`, `POST /incidents/{id}/feedback`) all answer 501 | — |

Notes:

- A full replay at 1× takes about 4 minutes (120 hours × 2 s plus 13 investigation steps); 8× takes about 30 s. After the last event the replay waits 8 s and restarts on its own (`loop: true`).
- The recorded S1 run (`fixtures/`) contains no `note_logged` events, so the "Didn't wake you" tab stays empty in replay. That is consistent with S1 but it means the replay cannot show demo moment 2.

## Integration branch (S2–S4)

See [matrix.md](matrix.md); the integration commands and their results are listed there with the SHAs they ran on.

## Smoke suite

`npm --prefix e2e test`; see [e2e/README.md](../../e2e/README.md).
