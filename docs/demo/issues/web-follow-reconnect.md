# [web] the event stream never reopens after it closes; the page stays offline until a reload

Labels: web, bug · File: `web/src/lib/api.ts` (`follow()`) · Fix branch: `team/alan/fix-follow-reconnect`

## Steps

1. `ARGUS_API=http://127.0.0.1:8199 npm --prefix web run dev -- --port 5273` with nothing on port 8199.
2. Open http://localhost:5273. The Vite proxy answers `/events` with 502, so `EventSource` closes for good
   (`readyState === CLOSED`) and `follow()` reports `offline`.
3. Start the API: `uv run argus api --port 8199`.

Expected: the page connects within a few seconds. Actual: it stays "API offline" until a manual reload
(checked with Playwright: still offline 8 s after the API answered `/health`).

Same when the API answers any non-200 on `/events` for a moment. A dropped connection to a page served by the
API itself is not affected: there `EventSource` stays `CONNECTING` and retries on its own (checked: the page
recovers 8 s after a restart, no duplicated cards).

## Fix (one place, 7 lines)

In `es.onerror`, when the source is `CLOSED`, report `offline` and call `open()` again after 2 s; clear the
timer in the cleanup. With the fix the same steps recover without a reload (checked with Playwright).

## Related, in the same scenario

A page that loaded while the API was down never fetched `GET /graph` (a fresh stream gets no `stream` header,
so `onReset` does not refetch it): the graph stayed a skeleton. Fixed in `team/alan/apply-app-states` with an
effect that fetches the graph once the connection is open and no graph is loaded.
