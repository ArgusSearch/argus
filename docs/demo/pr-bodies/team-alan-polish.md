# feat(web): blind challenge, shared loading and error states, responsive layout, demo click path

Base: `main`. Only Alan's folders: `web/src/challenge/`, `web/src/ui/`, `docs/demo/`. Builds and runs without the
hooks; the hooks and the per-component branches are separate PRs (see `docs/demo/HANDOVER.md`).

## What

- **Blind challenge** (`web/src/challenge/`): pick and seal with a QR code to the phone page, the commitment banner
  during the run, the reveal (truth next to Argus, grade, PASS, the hash recomputed in the browser, a one-character
  tamper test) and a phone page at 390 px. Recorded sample from `uv run argus-bench blind --seed 11` on main until
  the bench routes exist (`docs/demo/issues/api-blind-challenge-routes.md`).
- **SHA-256 fallback** written from FIPS 180-4 for phones on plain http (no `crypto.subtle`), and a **QR encoder**
  written from ISO/IEC 18004 (byte mode, level M, versions 1-10). No new dependency.
- **States** (`web/src/ui/`): `Spinner`, `Loading`, `Skeleton`, `EmptyState`, `ErrorState`, `OfflineBanner` and
  `explainError()` (plain English per status, never raw JSON).
- **Responsive** `web/src/ui/responsive.css`: 1920x1080 projector tier, 1280x720, one column at 768 and 390.
- **Docs**: `docs/demo/click-path.md` (timed), `HANDOVER.md`, issue drafts, PR bodies, screenshots.

Sources for the algorithms: NIST FIPS 180-4 (Secure Hash Standard), ISO/IEC 18004:2015 (QR code), the bench's
commitment rule in `src/bench/sealed.py`.

## How it was tested

```bash
npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build   # 54 passed, build OK
uv run ruff check . && uv run mypy && uv run python -m argus.contracts.export --check     # unchanged, green
```

- Vitest: NIST SHA-256 vectors (empty, "abc", 448-bit, 896-bit, one million "a"), block edges and UTF-8 against
  WebCrypto; the real reveal matches with WebCrypto and the built-in code; one changed character in the payload
  or the nonce fails; QR Reed-Solomon, format and version codes, finder and timing patterns; routes; `explainError`.
- The QR output decoded by zxing-cpp for versions 1, 3, 4, 6-10 (all match).
- Playwright at 1920x1080, 1440x900, 1280x720, 768 and 390: the whole challenge flow, no horizontal scroll, no
  console errors. Screenshots: `docs/demo/screenshots/challenge-*.png`, `after-*.png`, `before-*.png`.

## Still open

- Real phone over Wi-Fi and hotspot (only the phone viewport was checked).
- Live sealing: needs `POST /challenge/commit` and `/challenge/reveal` (issue draft above).
- `pytest` on Windows fails 3 pre-existing tests on main too (see HANDOVER, issue #24).
