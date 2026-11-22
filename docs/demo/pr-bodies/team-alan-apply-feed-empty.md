# fix(web): explain an empty feed tab instead of "Nothing here yet"

Refs: `docs/demo/issues/web-loading-error-states.md`. File: `web/src/components/Feed.tsx` only.
Per-tab `EmptyState`: "No incidents. Argus is watching 27 metrics." (count from `graph.nodes`), "No \"didn't wake you\" notes yet.", "No graph changes yet.", "Nothing yet. Argus is watching."

## How it was tested

```bash
npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build
```

Green on this branch (see `docs/demo/HANDOVER.md` for the exact counts). Python checks unchanged (no Python touched).


