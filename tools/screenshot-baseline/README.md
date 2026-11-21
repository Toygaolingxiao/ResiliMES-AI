# Screenshot baseline (Wave 0 / #121)

Isolated Playwright harness. **Does not** add a build step, bundler, or
dependency to the served app (`resilimes/demo/static`).

## Matrix

See `matrix.json`:

- Pages: `/`, `/report`, `/import`, `/timeline`
- Languages: `en` / `zh` / `ja` (`localStorage resilimes.lang`)
- Themes: `light` / `dark` (`resilimes.theme` + `html[data-theme]`)
- Widths: `1440` and `1023`
- Plus one pseudo-localized console shot (copy stretched ~35%)

Expected count: **49** (asserted by `tests/test_guard_checklist.py`).

## Capture

```bash
# terminal 1 — existing demo server, no extra build
python -m resilimes  # or whatever starts the mock console

# terminal 2
cd tools/screenshot-baseline
npm install
npm run capture -- --base=http://127.0.0.1:8000
```

PNGs land in `baselines/` (gitignored). Commit the matrix and this tool;
commit PNGs only when a wave intentionally refreshes the visual goldens.

## CI

Pytest asserts the matrix is complete. Full capture is optional / local
until Wave 1+ regression comparison wires the goldens. App CI stays
Python-only.
