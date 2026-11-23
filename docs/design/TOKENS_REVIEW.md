# ResiliMES design tokens

Generated from `docs/design/tokens.json`. Do not edit the table by hand —
run `python scripts/regen_tokens_review.py`. Format: `resilimes.design.tokens/v1`.
CSS/JS: scripts/regen_tokens_css.py / regen_tokens_js.py → demo/static/design/.

| Token | Layer | Light | Dark | Role |
| --- | --- | --- | --- | --- |
| `green-30` | primitive | #defbe6 | — | success wash candidate |
| `green-50` | primitive | #24a148 | — | success graphic / icon |
| `green-60` | primitive | #198038 | — | success text on light |
| `blue-60` | primitive | #0f62fe | — | interactive accent |
| `blue-70` | primitive | #0043ce | — | recorded ink |
| `red-60` | primitive | #da1e28 | — | alarm |
| `red-70` | primitive | #a2191f | — | alarm ink |
| `amber-30` | primitive | #fcf4d6 | — | warning wash |
| `amber-40` | primitive | #f1c21b | — | warning fill / graphic |
| `amber-50` | primitive | #8e6a00 | — | legacy amber text (boundary AA) |
| `amber-60` | primitive | #684e00 | — | warning text (AA-safe) |
| `gray-10` | primitive | #f4f4f4 | — | ground / unknown wash |
| `gray-100` | primitive | #161616 | — | ink |
| `--ground` | semantic | #f4f4f4 | #161616 | page background |
| `--card` | semantic | #ffffff | #1e1e1e | card surface |
| `--sheet` | semantic | #f4f4f4 | #262626 | form surface |
| `--layer-hover` | semantic | #e8e8e8 | #333333 | hover surface |
| `--ink` | semantic | #161616 | #f4f4f4 | body text |
| `--muted` | semantic | #525252 | #c6c6c6 | secondary text |
| `--line` | semantic | #e0e0e0 | #393939 | divider |
| `--accent` | semantic | #0f62fe | #78a9ff | primary action |
| `--text-success` | semantic | #198038 | #42be65 | success text |
| `--bg-success-subtle` | semantic | #defbe6 | #071908 | success wash |
| `--graphic-success` | semantic | #24a148 | #42be65 | success graphic (not text) |
| `--text-danger` | semantic | #a2191f | #ff8389 | danger text |
| `--bg-danger-subtle` | semantic | #fff1f1 | #3a1517 | danger wash |
| `--text-warning` | semantic | #684e00 | #f1c21b | warning text (owner #3) |
| `--bg-warning-subtle` | semantic | #fcf4d6 | #302400 | warning wash |
| `--graphic-warning` | semantic | #f1c21b | #f1c21b | warning graphic / fill |
| `--text-info` | semantic | #0043ce | #a6c8ff | recorded / info text |
| `--bg-info-subtle` | semantic | #edf5ff | #001d6c | recorded wash |
| `chart.light.gantt-run` | chart | #0f62fe | — | running bar |
| `chart.light.gantt-setup` | chart | #0072c3 | — | setup bar |
| `chart.light.gantt-down` | chart | #da1e28 | — | down bar |
| `chart.light.gantt-pm` | chart | #6f6f6f | — | PM bar |
| `chart.light.gantt-idle` | chart | #c6c6c6 | — | idle bar |
| `chart.dark.gantt-run` | chart | — | #78a9ff | running bar |
| `chart.dark.gantt-setup` | chart | — | #33b1ff | setup bar |
| `chart.dark.gantt-down` | chart | — | #fa4d56 | down bar |
| `chart.dark.gantt-pm` | chart | — | #a8a8a8 | PM bar |
| `chart.dark.gantt-idle` | chart | — | #525252 | idle bar |

## `--text-warning` contrast (scripted)

| Foreground | Background | Ratio | AA text (≥4.5) |
| --- | --- | --- | --- |
| `--text-warning` `#684e00` | --card / white `#ffffff` | 7.84:1 | pass |
| `--text-warning` `#684e00` | --ground `#f4f4f4` | 7.13:1 | pass |
| `--text-warning` `#684e00` | --bg-warning-subtle `#fcf4d6` | 7.11:1 | pass |
| `--text-warning` `#684e00` | --layer-hover `#e8e8e8` | 6.40:1 | pass |
