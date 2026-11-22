# fix(web): "While you slept" shows a skeleton while loading and a plain error with retry

Refs: `docs/demo/issues/web-loading-error-states.md`. File: `web/src/components/Overlays.tsx` (`DigestModal`) only.

## How it was tested

```bash
npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build
```

Green on this branch (see `docs/demo/HANDOVER.md` for the exact counts). Python checks unchanged (no Python touched).


