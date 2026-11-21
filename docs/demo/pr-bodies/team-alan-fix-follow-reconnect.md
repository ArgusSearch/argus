# fix(web): reopen the event stream after it closes, so the page recovers when the API comes back

Refs: `docs/demo/issues/web-follow-reconnect.md`. File: `web/src/lib/api.ts` (`follow()`) only, 7 lines:
when `EventSource` is `CLOSED` (a non-200 on `/events`, e.g. the Vite proxy while the API is down), report `offline` and reopen after 2 s.

## How it was tested

```bash
npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build
```

Green on this branch (see `docs/demo/HANDOVER.md` for the exact counts). Python checks unchanged (no Python touched).

Before: dev page stayed "API offline" 8 s after the API came back. After: banner gone, 31 graph nodes rendered, replay running (Playwright).
