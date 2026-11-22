# fix(web): data-issue notes use the "didn't wake you" wording

String only, `web/src/components/Feed.tsx` ("Data issue · held back" -> "Data issue · didn't wake you"). Refs: `docs/demo/issues/web-copy.md`.

## How it was tested

```bash
npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build
```

Green on this branch (see `docs/demo/HANDOVER.md` for the exact counts). Python checks unchanged (no Python touched).


