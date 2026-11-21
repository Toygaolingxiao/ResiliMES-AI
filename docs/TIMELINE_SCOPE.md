# Timeline scope: what the Gantt page shows vs the window

Contract: `timeline/v1` (`resilimes/timeline/model.py`, `window_payload`).
The page (`resilimes/demo/static/product/timeline/timeline.js`) is the only
caller. This note defines the scope fields added 2026-11-18 and the basis of
every number the page draws.

## The problem this fixes

The lot cap (`lots`, default 100) used to shrink the drawn bars silently:
at the default window the page showed about 6% of the lots while the stat
cards — computed from the same shrunken set — read as if they described the
whole window (e.g. `late_lots` 5 shown vs 31 in the window). Nothing on the
page said a subset was shown.

## Two windows: `window` vs `view`

The page fetches a wider range than it shows: every fetch widens the
display span by one span on each side, so panning does not re-fetch
immediately. The payload therefore carries two windows:

| Field | Definition |
| --- | --- |
| `window` | The fetched range. `bars`, `machine_rows`, `product_rows`, `blocks` and `gaps` cover this range (after the caps below). |
| `view` | The display range the page shows (`view_t0`/`view_t1` query params; absent, the view is the fetch window). Stats and `scope` are computed over this range. |

On first load the two coincide (the page adopts `body.window` as its
display span). After navigating (day buttons, zoom, pan), the view is the
middle third of the fetch — and the cards follow the view, not the fetch.

## `scope`

Every payload carries:

| Field | Definition |
| --- | --- |
| `scope.lots_total` | Distinct `bar.lot` values with at least one bar in the display window, before the lot cap. |
| `scope.lots_shown` | Distinct `bar.lot` values in the bars actually drawn inside the display window. |
| `scope.lots_capped` | True when the lot cap engaged on the fetch window. It can be true while the view shows all its lots — the notice fires on `lots_shown < lots_total`, not on this flag. |
| `scope.bars_total` | Bars in the display window, before the lot cap and the bar limit. |
| `scope.bars_shown` | Bars drawn inside the display window. |
| `scope.machines_total` / `scope.machines_shown` | Distinct machines in the display window / drawn inside it. |

`truncated` (pre-existing) stays as the bar-limit flag: true when the bars
surviving the lot cap exceed `limit` (default 8000). Note it is computed
after the lot cap, so a window with 9751 bars reduced to 1302 by the cap
reports `truncated=false`.

Consistency: `stats.total_lots == scope.lots_total` and
`stats.total_jobs == scope.bars_total` always hold, because both are
computed over the same display-window bar set — except `skip_count`
(see below).

## Stats basis

`stats` are computed over the bars in the display window **before** the
lot cap and the bar limit. The cards therefore describe the display
window, not the drawn subset. When lots are hidden, the status line says
so (`timeline.scopeLots`: "Showing {shown} of {total} lots in this
window. Counts cover this window; Skips counts the whole book."), and the
bar-limit sentence (`timeline.truncated`) is appended when `truncated` is
true. The lots sentence appears whenever `lots_shown < lots_total`,
whatever cut the lots — lot cap or bar limit.

Consequence, stated plainly: the Segments card can be larger than the number
of bars drawn. That is the intended semantic — cards = display window,
canvas = drawn subset — and the status line is what makes the two numbers
reconcilable on screen.

## Stats semantics

One bar is one lot's one step on one machine. Every `stats` field counts
bars, lots, machines, steps or wafers over the display-window bar set —
except `skip_count` (whole book, see below):

| Field | Card label | Counts |
| --- | --- | --- |
| `stats.total_jobs` | Segments / 工程段数 / 工序段数 | Bars in the display window. The field name is historical (timeline/v1); the card no longer reads "Jobs", because a bar is an operation segment, not a job in the lot sense. Renaming the field is a contract change proposed for a follow-up, not done here. |
| `stats.total_equipment` | Tools / 装置数 / 装置数 | Distinct machines with at least one bar in the window. |
| `stats.total_lots` | Lots / ロット数 / 批次数 | Distinct `bar.lot` values with at least one bar in the window. `also` members sharing a bar are **not** counted here (see Lot-count nuance): 19 lots in the SMT2020 book appear only via `also`. |
| `stats.total_operations` | Steps / 工程数 / 工序数 | Distinct `bar.step` values — step kinds, not step executions. Two lots running the same step add one to this count. |
| `stats.total_moves` | Wafer-steps / ウェーハステップ数 / 晶圆步数 | Sum of `bar.qty` over the bars. `qty` is wafers (25 per lot per step in SMT2020; a batched bar carries 25 per lot in the batch), so this is wafer-steps: one lot is counted once per step it runs, and a reworked step counts again on its second execution. It is neither a move count nor a count of distinct wafers in the window. A batched bar's `qty` includes the wafers of its `also` lots, which are not counted in Lots — so the Wafer-steps and Lots cards count different lot sets on shared bars. |
| `stats.late_lots` | Late / 納期遅れ / 迟到 | Distinct late lots with at least one bar in the window. |
| `stats.qtime_breach` / `stats.qtime_risk` | Q-time / Qタイム / 排队时限 | Bars flagged breach / risk in the window. |
| `daily[].jobs` | (no label; day buttons show the count) | Bars overlapping the fetch window, bucketed by start day. A bar counts toward the day its `start_min` falls on, even when that start is outside the fetch window. The field name is the same historical "jobs"; it counts bars, like `total_jobs`. |

Known divergence, out of scope for this increment: when a timeline
label key is missing, the page shows the raw key (`timeline.js`
`c[key] || key`), and a missing language falls back to Japanese —
unlike the cases page rule (a missing key falls back to the English
label, never the raw key). No key is missing today (all three
languages carry the same 77 keys); this is recorded here so the
inconsistency is not mistaken for intent.

Two fields are NOT display-window counts:

- `skip_count` is a whole-book replay count (`book.skips`), or `0` when
  the query is narrowed by any filter. An empty window still shows the
  book's skips; a narrowed query shows 0, which reads as "no skips"
  rather than "skips hidden by the filter". The notice's Skips clause
  exists because of this card. A true window-wide Skips is computable —
  the replay carries skip timestamps — but needs plumbing through
  `smt_book.py`; follow-up, not this increment.
- `daily` counts bars by start day over the **fetch** window, not the
  display window: it is a navigation aid across the loaded range, and its
  day buttons set the display span.

## Verified numbers: correcting the PR #101 smoke sentence

PR #101's description says "1,199 bars across 1,313 tools and 2,156
lots". Read literally, that sentence is wrong: it mixes a one-hour
window's bar count with the whole 48-hour book's tool and lot totals.
The measured figures (SMT2020 book, seed 1; independently re-measured
2026-11-19 in this run — `load_smt_book()` + `window_payload`, by the
coordinator and by the product and red-team reviewers separately; the
2026-11-17 figures agree with them):

| Figure | Value | Basis |
| --- | --- | --- |
| Bars, first hour, uncapped | 1,199 | 1-hour display window, `lots=5000` (effectively uncapped for this book) |
| Tools, first hour, uncapped | 954 | Distinct machines with a bar in that window, `lots=5000` |
| Lots, first hour, uncapped | 1,005 | Distinct `bar.lot` values with a bar in that window, `lots=5000` (primary lots only; another 277 lots appear only as batch members, `bar.also`, in the same hour — union 1,282) |
| Bars drawn, first hour, page default (`lots=100`) | 228 | Drawn subset (`scope.bars_shown`); the Segments card still reads 1,199 |
| Wafer-steps, first hour, uncapped | 36,900 | `sum(bar.qty)`; the old "Moves" card value, `lots=5000` |
| Tools, whole 48 h book | 1,313 | Distinct machines in the book |
| Lots, whole 48 h book | 2,113 | Distinct `bar.lot` values with at least one bar in the book (LotInfo rows: 2,156, of which 43 have no bar in 48 h) |

Correct reading: "1,199 bars across 954 tools and 1,005 lots in the
first hour (uncapped); the full 48 h book spans 1,313 tools and
2,113 lots that ran at least one bar. At the page default (`lots=100`)
the canvas draws 228 of those 1,199 bars while the Segments card still
reads 1,199. This increment does not edit
PR #101's description; this section is the correction of record, and the card
labels fixed in this increment (Segments, Wafer-steps) are what stop the
page itself from repeating the confusion. The 36,900 wafer-steps
against 1,199 bars is also why "Moves" was misleading: one bar carries
25 wafers (more when batched), so the old card read ~30x the bar
count with no unit to explain it.
## Data source

Every payload already carried `source`, `seed` and `horizon_h`
(`window_payload`, top-level fields); the page never showed them, so
the SMT2020 benchmark and the sample fab were indistinguishable on
screen. The page now renders a source line (`.tl-source`,
`timeline.sourceLine`) from those three fields — no API change:

- `smt2020` → "SMT2020 benchmark" (`timeline.sourceSmt2020`),
  `sample` → "Sample fab" (`timeline.sourceSample`), in all three
  languages. Any other `source` value is shown verbatim — never
  dropped, never invented (the renderer fills `{seed}`/`{horizon}`
  before `{source}`, so a source containing "{seed}" stays literal).
  Matching is exact and case-sensitive; `"SMT2020"` is not mapped.
- `sample` always takes the short form (`timeline.sourceLineShort`,
  source only). The sample book has no random seed (`seed=1` is a
  hardcoded constant) and its `horizon_h` is the last bar end
  (6.98 h on the real sample book), not a run horizon — printing
  "seed 1 · 6.98 h" would read as a seeded simulation run that never
  happened.
- Otherwise the full form prints only when the seed is a positive
  integer and the horizon is a finite number above zero; any other
  value takes the short form. If `source` itself is missing, not a
  string, or blank, no line is shown.
- `{horizon}` is the whole-book horizon (48 h for SMT2020), not the
  span of the window currently on screen (12 h by default).
- The line shows the book actually loaded, never the request
  parameters: in sample mode the API ignores the `book`/`seed`/
  `horizon_h` query parameters (see M5 below), so a requested seed
  that was silently dropped is never printed as if it applied.
- The line is separate from the warn status line (`.tl-status`): it is
  factual, shown whenever a payload is loaded, re-rendered on
  language switch, and never takes the warn style. A missing catalog
  key falls back to English, never to silence.
- A failed load clears the line, so no source is asserted under the
  error. Residual: the failed load keeps the previous payload, so a
  language switch afterwards re-renders the old source line from it
  (and the old chart) — the same pre-existing stale-payload behaviour
  as the rest of the page, not something this increment introduces.

Still open: CSV / PNG export carries no source note (see above).

## What still describes the drawn subset only

- `machine_rows` / `product_rows` / `blocks`: rows and blocks for the
  machines and lots in the fetched set after the caps. Their per-group
  counts sum to the drawn subset, not to the cards; the status line's
  lots sentence is the only on-page reconciliation. In idle mode with no
  narrowing filter, `machine_rows` lists the whole fab while
  `stats.total_equipment` counts only machines with bars in the display
  window.
- `gaps`: computed from the returned bars, but a gap is only reported
  when the lot's sequence is intact in the display — if any bar of the
  lot in the window was dropped by the lot cap or the bar limit, that
  gap is skipped instead of fabricated. (The cap *can* split a lot's
  sequence when `also` co-location is involved: a bar is kept if any of
  its members ranked in, so a middle bar can drop while its neighbours
  survive. The guard above is what keeps that honest.)
- `focus_bars`: still hard-cut at 400 with no marker, and they bypass
  the window and the filters entirely — a focused lot's bars draw even
  when the filters exclude them, while stats and scope exclude them.
  The focus lot is drawn on request and shown in the "Selected" line;
  it is not counted in `scope`.
- CSV / PNG export: exported from the drawn bars, not the display
  window, with no truncation note attached. CSV additionally excludes
  `focus_bars`; PNG renders only the visible viewport, narrower than the
  drawn bars.

## Lot-count nuance

The cap ranks lots by member count, where a member is `bar.lot` plus
`bar.also` (co-located lots sharing a bar, see
`resilimes/timeline/smt_book.py`). `scope` counts `bar.lot` only, matching
the Lots card — so an `also`-only lot can rank into the kept set and
displace a primary lot without ever appearing in `lots_total`, and an
`also` lot rides along on a shared bar and appears as an extra lot row
without being counted. The banner reports drawn primary lots, which is
the honest number for the reader; the focus lot can additionally push
`lots_shown` one over the `lots` limit (focus is force-added to the kept
set). Direct model use with `lots<=0` disables the cap (the API forbids
0 with `ge=1`).

## Acceptance (given/when/then)

1. Given a window with 4 lots and `lots=1`, when the payload is built,
   then `scope.lots_total == 4`, `scope.lots_capped` is true,
   `stats.total_lots == 4`, and `stats.late_lots` counts late lots from
   the whole display window, not just the drawn lot.
2. Given a window that fits the cap and the bar limit, when the payload
   is built, then `scope.lots_capped` is false, `lots_total ==
   lots_shown`, `bars_total == bars_shown`, and no scope notice is shown.
3. Given a capped payload and the English copy, when the page composes
   the status line, then it reads "Showing {shown} of {total} lots in
   this window. Counts cover this window; Skips counts the whole book."
   with the real counts, and the bar-limit sentence is appended only
   when `truncated` is true.
4. Given a fetch window wider than the display window, when the payload
   is built with `view_t0`/`view_t1`, then stats and scope count the
   display window only, `bars` still cover the fetch window, and
   `payload.view` names the display range.
5. Given a lot whose middle bar was dropped by the cap, when gaps are
   computed, then no gap is reported across the dropped bar's interval.
6. Given a synthetic window of 3 bars across 2 step kinds with wafer
   quantities 25, 25 and 75, when the payload is built, then
   `stats.total_jobs == 3`, `stats.total_operations == 2` and
   `stats.total_moves == 125`; and in all three languages the stats
   cards read Segments / 工程段数 / 工序段数 for `total_jobs` and
   Wafer-steps / ウェーハステップ数 / 晶圆步数 for `total_moves`.
