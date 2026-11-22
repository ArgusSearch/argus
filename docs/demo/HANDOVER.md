# Handover: demo flow and polish (Alan's lane)

> Historical handover. The branches, draft changes and screenshots in this folder describe the rehearsal at the revision below. See the [current showcase guide](../pitch/showcase.md) for the playback flow.

Last update: Saturday 2026-11-21, evening. Base: `origin/main` at `f35b00a`. Nothing pushed yet: every branch below
is local and waits for review. A fresh agent can continue from this file alone.

## Branches

Push order: `team/alan/polish` first (all owned files), then the rest in any order (each is one small commit on
top of polish). Every branch is green on its own (table at the end).

| Branch | Purpose | Files outside Alan's folders |
| --- | --- | --- |
| `team/alan/polish` | `web/src/ui/` (states, `explainError`, responsive.css), `web/src/challenge/` (blind challenge), `docs/demo/` | none |
| `team/alan/hook-responsive` | `hook:` import responsive.css in `main.tsx` | `web/src/main.tsx` (1 line) |
| `team/alan/hook-challenge` | `hook:` wrap `<App />` in `<ChallengeGate>` | `web/src/main.tsx` (4 lines) |
| `team/alan/apply-app-states` | offline banner, graph skeleton, graph refetch on open | `web/src/App.tsx` |
| `team/alan/apply-feed-empty` | empty states per feed tab | `web/src/components/Feed.tsx` |
| `team/alan/apply-receipts-states` | receipt skeleton, error with retry, plain 409 re-run message | `web/src/components/Receipts.tsx` |
| `team/alan/apply-digest-states` | "While you slept" skeleton and error with retry | `web/src/components/Overlays.tsx` |
| `team/alan/apply-incident-states` | incident sheet skeleton and error with retry | `web/src/components/IncidentSheet.tsx` |
| `team/alan/fix-follow-reconnect` | reopen a closed event stream | `web/src/lib/api.ts` |
| `team/alan/copy-ticker`, `copy-feed`, `copy-trail`, `copy-incident` | string-only copy fixes | one component each |

The two hooks both edit `web/src/main.tsx` but merge cleanly together (checked). The apply and copy branches on
`Feed.tsx` and `IncidentSheet.tsx` touch different lines and merge cleanly together (checked: all 12 merged into a
local preview branch `local/alan-preview`, typecheck, 54 tests and build green; never push that branch).
Issues to file first (section 7, rule 3): `docs/demo/issues/*.md`. PR bodies: `docs/demo/pr-bodies/*.md`.

## A1 click path: `docs/demo/click-path.md`

Done as a first draft with measured and computed timings on main: S1 replay at 4× (anomaly 46.7 s, explained
50.2 s, resolved 54.3 s, measured), S2 replay at 4× ("Didn't wake you" note at about 30 s, computed), live S1
seed 7 at 0.5 s per hour (incident at 64 s, measured), new metric in the terminal (1.7 s, measured).
MISSING lines: beat 3 in the browser (`POST /metrics` 501), live blind challenge (bench routes 501), demo mode and
Scorecard (Youssef's PR #25), and the two hooks.
Not verified: a stopwatch run with a narrator, and whether the beats fit 3:00 after the cuts.

## A2 loading, empty and error states: `web/src/ui/`

`Spinner`, `Loading` (shows only after 250 ms), `Skeleton` (lines, card, sheet, graph), `EmptyState`, `ErrorState`
(plain title and detail, the failed route, Try again only when retrying can help), `OfflineBanner` (silent while
connected; "Connecting to Argus" only after 2 s; "The API is not running" / "Lost the connection to the API" with a
retry clock; Reload). `explainError()` maps statuses to plain English and never shows raw JSON (vitest).
Applied in five components through the apply branches. Checked with Playwright:

- Dev server, API stopped: banner "The API is not running · Retrying on its own · 5 s", graph skeleton, feed empty
  state, no blank screen. API started: recovered in under 8 s without a reload (needs `fix-follow-reconnect` and
  `apply-app-states`; without them the page stayed offline, see `issues/web-follow-reconnect.md`).
- Page served by the API, API stopped 10 s and restarted: "Lost the connection to the API", then full recovery,
  31 graph nodes, no duplicated cards.
- Replay, "Re-run SQL": "Receipt re-runs need live mode. ... Start Argus live with make demo to re-run receipts."

Console: while the API is down the browser logs failed requests (502 through the dev proxy, refused without it)
from the 1 s health poll. That is the browser, not the app; nothing else is logged.

## A3 blind challenge: `web/src/challenge/`

URLs (with `hook-challenge`): `/?challenge` (pick and seal, QR to the phone page), `/?challenge=run` (Mission
Control plus a "Hidden scenario, committed sha256:…" banner bottom right), `/?challenge=reveal` (scenario, the
truth next to what Argus said, grade table, PASS, the hash recomputed in the browser, "Change one character of the
payload"), `/?challenge=verify&c=<hash>` (phone page: commitment from the QR, load the reveal, recompute).

- SHA-256 written from FIPS 180-4 (`sha256.ts`), used when `crypto.subtle` is missing (a phone on
  http://192.168.x.x is not a secure context); WebCrypto otherwise. Vitest: the NIST vectors (empty, "abc",
  448-bit, 896-bit, one million "a"), block edges 55 to 120 bytes and UTF-8 against WebCrypto, the real reveal
  matches with both engines, one changed character in the payload or the nonce fails.
- QR encoder written from ISO/IEC 18004 (`qr.ts`, byte mode, level M, versions 1-10, no dependency). Vitest: the
  HELLO WORLD Reed-Solomon example, format and version BCH codes, finder and timing patterns. Also decoded by an
  independent decoder (zxing-cpp via `uv run --with zxing-cpp`) for versions 1, 3, 4, 6, 7, 8, 9 and 10: all match.
- Sample: `fixtures/blind-11.*`, recorded on main with `uv run argus-bench blind --seed 11` (s1, PASS,
  commitment `sha256:0207174d…e7ed80`; `uv run argus-bench verify runs/bench/blind-11` says match).
  `sample.ts` is the only loader; swap it for the API when `issues/api-blind-challenge-routes.md` lands.
- Honest limits on screen: a "recorded run · seed 11" chip, and "Live sealing is not built yet" when the judge
  types another number. The run step shows the normal replay, not the hidden world.

Not verified: a real phone. Checked only in Chrome's phone viewport (390x844, touch) on the laptop. On a real
phone over the venue Wi-Fi and over a hotspot: run `uv run argus api --host 0.0.0.0 --port 8000`, type the
laptop's LAN address under the QR code, scan, then load the reveal. On http the page uses the built-in SHA-256
and says so ("built-in SHA-256 (no WebCrypto on this page)").

## A4 responsiveness: `web/src/ui/responsive.css`

Screenshots in `docs/demo/screenshots/` (`before-*` from main, `after-*` with all branches): horizontal scroll at
768 went from 497 px to 0 and at 390 from 875 px to 0; 1920, 1440 and 1280 stay at 0. At 1920x1080 the header,
ticker, feed and trail are zoomed 1.12 for the projector (the graph is never zoomed: React Flow measures its own
pointer). If Youssef's demo mode scales type itself, it sets `data-demo` on `<html>` and this tier switches off.
Known: at 768 the graph's outer nodes touch the canvas edge (fit is done by `GraphView`); at 1280x720 the graph is
small because the trail keeps its 244 px. Not verified: readability from 3 m on a real projector.

## A5 performance

Measured with Playwright on the laptop, S1 replay restarted, 1920x1080, two runs each at 8× and one at 4×:

| | before (main) | after (main plus all branches) |
| --- | --- | --- |
| first contentful paint | 128-164 ms | 156-164 ms |
| frames over 50 ms during the S1 walk (anomaly to resolved) | 0-2 (56 ms) | 0 |
| frames over 50 ms at startup (graph mount, first 0.5 s) | 3 (up to 181 ms) | 3 (up to 174 ms) |
| app chunk | 55.84 kB | 65.90 kB (+ challenge screens lazily, 26 kB) |
| largest chunk | xyflow 246.58 kB | same |

Main already splits React and React Flow into their own chunks, so the 500 kB target is met; my vendor-chunk hook
was dropped. Not done: the Chrome Performance panel and React Profiler by hand, graph panning smoothness (not
measured), lazy loading of the sheets (not needed for the chunk target).

## A6 copy: `docs/demo/issues/web-copy.md`

Four string-only branches (ticker and feed say "didn't wake you", "Playbook for a drop", "Copy as Markdown"), plus
a list of API and narrator strings for their owners: the digest's "0 anomalys", the provider named twice in the
incident title, segment order, raw `SUPPORTED_CAUSE` in the trail, `EUR` and metric ids in trail prose.

## Green checks (Windows 11, Git Bash, no make)

Web, every branch: `npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build`:
typecheck OK, 54 tests passed (35 of them mine, 19 on main), build OK.

Python (no Python touched; identical on every branch): `uv run ruff check .` passed; `uv run mypy` no issues in
96 files; `uv run python -m argus.contracts.export --check` OK; `uv run ruff format --check .` reports 1 file
(`docs/plan/build-plan.md`, on main, not mine). `uv run pytest` on a clean `origin/main` worktree fails the same
3 tests as on my branches (pre-existing, Windows): `tests/api/test_api_app.py::test_replay_reruns_recorded_receipts_on_the_same_world`
(issue #24, still fails on main), `tests/api/test_api_scenarios.py::test_live_runtime_streams_the_recorded_story[s2]`
(live s2 streams 160 events, the recording has 163) and `tests/bench/test_bench_runner.py::test_callable_and_command_agents`
(`FileNotFoundError` from `subprocess` on Windows). With `web/node_modules` installed, `tests/api/test_api_web.py`
adds 2 Windows-only failures (`npm` is `npm.cmd`; the test calls `subprocess.run(["npm", ...])`).
