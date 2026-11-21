# fix(web): say when the API connection drops and show a graph skeleton while it loads

Refs: `docs/demo/issues/web-loading-error-states.md` (file it first, section 7 rule 3). File: `web/src/App.tsx` only.

- `OfflineBanner` replaces the red "API is offline" banner: connecting (only after 2 s), "The API is not running", "Lost the connection to the API" with a retry clock, Reload when the stream closed.
- `Skeleton variant="graph"` while `GET /graph` has not answered.
- Fetch the graph once the stream opens if the page loaded while the API was down (a fresh stream gets no `stream` header, so `onReset` never refetched it).

## How it was tested

```bash
npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build
```

Green on this branch (see `docs/demo/HANDOVER.md` for the exact counts). Python checks unchanged (no Python touched).

Checked with Playwright: page served by the API, API stopped for 10 s then restarted: banner, then full recovery, no duplicated cards. Dev server with the API down, then up: recovers (with `team/alan/fix-follow-reconnect`).
