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

Consequence, stated plainly: the Jobs card can be larger than the number
of bars drawn. That is the intended semantic — cards = display window,
canvas = drawn subset — and the status line is what makes the two numbers
reconcilable on screen.

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
