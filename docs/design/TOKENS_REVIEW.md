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
| `chart.gantt-processing` | chart | #FFD700 | #F5D000 | timeline bar: processing (gold) |
| `chart.gantt-scheduled` | chart | #5B8DEF | #7BA8F5 | timeline bar: scheduled (blue) |
| `chart.gantt-reserved` | chart | #FF69B4 | #FF85C2 | timeline bar: reserved (pink) |
| `chart.gantt-waiting` | chart | #82C213 | #9AD42E | timeline bar: waiting (green) |
| `chart.gantt-transport` | chart | #8080C0 | #9A9AD4 | timeline bar: transport (periwinkle) |
| `chart.gantt-setup` | chart | #FFA400 | #FFB833 | timeline bar: setup (orange) |
| `chart.gantt-down` | chart | #6b6258 | #A09890 | timeline bar: down (brown-gray) |
| `chart.gantt-pm` | chart | #808080 | #B0B0B0 | timeline bar: PM (gray) |
| `chart.gantt-idle` | chart | #e7e2d8 | #4a4640 | timeline bar: idle (beige) |
| `chart.gantt-ink-dark` | chart | #1e293b | #0f172a | label ink on light bars |
| `chart.gantt-ink-light` | chart | #ffffff | #f8fafc | label ink on dark/mid bars |
| `chart.fab-run` | chart | #4589ff | #78a9ff | fab tool: running |
| `chart.fab-setup` | chart | #eb6200 | #ff832b | fab tool: setup |
| `chart.fab-idle` | chart | #e0e0e0 | #525252 | fab tool: idle |
| `chart.fab-pm` | chart | #6f6f6f | #a8a8a8 | fab tool: PM |
| `chart.fab-down` | chart | #da1e28 | #fa4d56 | fab tool: down |
| `chart.fab-wait` | chart | #f1c21b | #f1c21b | fab tool: wait / batch_wait |
| `chart.class-vip` | chart | #8a3ffc | #be95ff | lot class VIP |
| `chart.class-hot` | chart | #d02670 | #ff7eb6 | lot class hot |
| `chart.class-normal` | chart | #8d8d8d | #a8a8a8 | lot class normal |
| `chart.risk-late` | chart | #da1e28 | #fa4d56 | risk late |
| `chart.risk-risk` | chart | #b28600 | #f1c21b | risk at-risk |
| `chart.done` | chart | #24a148 | #42be65 | done / pass graphic |
| `chart.area-lithography-fill` | chart | #d0e2ff | #312e81 | bay Lithography fill |
| `chart.area-lithography-ink` | chart | #002d9c | #e0e7ff | bay Lithography ink |
| `chart.area-etch-fill` | chart | #9ef0f0 | #155e75 | bay Etch fill |
| `chart.area-etch-ink` | chart | #004144 | #cffafe | bay Etch ink |
| `chart.area-cmp-fill` | chart | #e8daff | #5b21b6 | bay CMP fill |
| `chart.area-cmp-ink` | chart | #491d8b | #f3e8ff | bay CMP ink |
| `chart.area-deposition-fill` | chart | #a7f0ba | #115e59 | bay Deposition fill |
| `chart.area-deposition-ink` | chart | #044317 | #ccfbf1 | bay Deposition ink |
| `chart.area-metrology-fill` | chart | #fddc69 | #92400e | bay Metrology fill |
| `chart.area-metrology-ink` | chart | #483700 | #ffedd5 | bay Metrology ink |
| `chart.area-clean-fill` | chart | #e0e0e0 | #1e3a5f | bay Clean fill |
| `chart.area-clean-ink` | chart | #393939 | #e0f2fe | bay Clean ink |

## `--text-warning` contrast (scripted)

| Foreground | Background | Ratio | AA text (≥4.5) |
| --- | --- | --- | --- |
| `--text-warning` `#684e00` | --card / white `#ffffff` | 7.84:1 | pass |
| `--text-warning` `#684e00` | --ground `#f4f4f4` | 7.13:1 | pass |
| `--text-warning` `#684e00` | --bg-warning-subtle `#fcf4d6` | 7.11:1 | pass |
| `--text-warning` `#684e00` | --layer-hover `#e8e8e8` | 6.40:1 | pass |
