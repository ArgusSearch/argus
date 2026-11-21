# fix(web): receipt drawer shows a skeleton while loading and says why a re-run failed

Refs: `docs/demo/issues/web-loading-error-states.md`. File: `web/src/components/Receipts.tsx` only.
Loading: skeleton. Load error: `ErrorState` with the route and Try again. Re-run in replay (409): "Receipt re-runs need live mode. This page replays a recorded run, so there is no database to query. Start Argus live with make demo to re-run receipts."

## How it was tested

```bash
npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build
```

Green on this branch (see `docs/demo/HANDOVER.md` for the exact counts). Python checks unchanged (no Python touched).

Checked in replay with Playwright (footer text above) and live on `uv run argus api --world runs/s1-7/world.duckdb` (r169 re-run: same hash).
