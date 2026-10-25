# Design skills vendored for the console

These files are upstream skill texts. ResiliMES did not rewrite them.

| Path | Source | License |
| --- | --- | --- |
| `.cursor/skills/design-taste-frontend/` | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) `skills/taste-skill/SKILL.md` and `references/app-screens.md` (main, fetched 2026-10-23) | MIT, Copyright (c) 2026 Leonxlnx. See `LICENSE` in that folder. |
| `.cursor/skills/frontend-design/` | [anthropics/skills](https://github.com/anthropics/skills) `skills/frontend-design/SKILL.md` and `LICENSE.txt` (main, fetched 2026-10-23) | Apache License 2.0. See `LICENSE.txt` in that folder. |
| `.cursor/skills/impeccable/` | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) v4.7.1, `cursor-plugin/skills/impeccable/` (`SKILL.md`, `reference/`, `scripts/`), plus the repo `LICENSE` and `NOTICE.md` (main at 9368675, fetched 2026-10-25) | Apache License 2.0, Copyright 2025 Paul Bakaus. See `LICENSE` and `NOTICE.md` in that folder; `reference/ios.md` and `reference/android.md` derive from ehmo/platform-design-skills (MIT). |
| `DESIGN.md` (repo root) | [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md) `design-md/ibm/DESIGN.md` (main at 3b60532, fetched 2026-10-25) | MIT, Copyright (c) 2026 VoltAgent. An analysis of IBM Carbon, not an official IBM document. Credit section at the end of the file. |
| `resilimes/demo/static/fonts/` | IBM Plex Sans and IBM Plex Mono, Latin-1 subsets in woff2 | SIL Open Font License 1.1, Copyright 2017 IBM Corp. See `OFL.txt` in that folder. |

The taste-skill folder here is the written skill and the app-screen reference, not the draw-script library. This console is an app screen, so the build followed `references/app-screens.md` rather than a marketing-page direction.

Impeccable's `scripts/impeccable` launcher runs a platform binary that is not committed here; it looks next to the script, then in `~/.impeccable`, then downloads the pinned release on first run. The 2026-10 redesign followed Impeccable's audit, critique and polish references in operate mode, with `DESIGN.md` as the visual system.
