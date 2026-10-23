# Gantt review

Three roles reviewed the Recover Gantt on the live console at 1920×1080, then the same three reviewed the implementation. Measurements below are from the page, not from a visual guess: `scrollHeight`, label rectangles, tick rectangles, and the shared window on the report.

Baseline frames (the chart before this change): `screenshot_gantt_base_litho.png`, `screenshot_gantt_base_rush.png`, `screenshot_gantt_base_shortage.png`, `screenshot_gantt_base_rework.png`, `screenshot_gantt_base_qtime.png`, `screenshot_gantt_base_bylot.png`.

## What the baseline actually did

`scaleOf` took the max of every bar end, every priority-1 due, and every down or maintenance `available_at_min`, then rounded up to a full hour. Both charts shared that number, but the number was not the work. Flexbox `space-between` then pinned the last tick to the right edge even when that tick was not the scale end.

Lot ids that did not fit a bar were floated into the gap above or below the bar. On the lithography frame those captions stacked on the neighboring lots.

Measured books, minutes from 06:30 UTC:

| Scenario | Before last bar | After last bar | What was stretching the axis |
| --- | --- | --- | --- |
| Lithography down | 965 | 420 | The late bar is real. LOT-1001 is due at 690. LITHO-02 is down until 600. |
| Rush | 420 | 510 | LOT-1001 due at 690. LOT-2001 is due at 180. |
| Shortage | 420 | 240 | LOT-1001 due at 690. |
| Rework | 420 | 570 | LOT-1001 due at 690. |
| Queue time | 420 | 340 | LOT-1001 due at 690. |

The lithography after book really does end at 420. An empty right half on that chart is the makespan recovery. The other four scenarios were empty because the axis ran out to a due the bars never reach.

## Role A — fab planner

Independent critique of the baseline:

- The lithography before book must keep the bar that ends at 965. Clipping it would hide the lot that waited out the down scanner.
- LITHO-02's hatch through 600 minutes is the reason LOT-1001 moved. It has to stay on the row. DEP-01's maintenance hatch stays too, including on a row that has no bars. Dropping an empty tool hides a resource.
- The Now line is the scenario clock and has to be the left edge. A window that starts after 0 makes the clock look late.
- LOT-2001's due at 180 is the rush story. LOT-1001's due at 690 is still a fact when the book ends at 510, 480, or 600. Hiding it is a lie. Stretching the axis to 690 to show it is why the rush, shortage, rework, and queue-time charts look empty.
- Rework is a stripe on the lot's bar, not a new color. The bottleneck is the marked tool label. A reticle is a Verify fact. A queue-time window is an Analyze fact. Drawing either on the tool Gantt would fight the hatch.
- A non-linear scale would make a 90-minute lithography step look like a 40-minute CMP step. Rejected.

Proposal: one linear window from t=0 to the later bar, plus about 5% and snapped to a tick. Clip a down block that runs past that window and mark the cut. Put an off-window due on the edge instead of moving the edge.

## Role B — product designer

Independent critique of the baseline:

- Bars were 20px in a 36px row. At 1920×1080, and again once the frame is recorded, the lot id is the thing that disappears.
- Floating captions are why 1001 and 1004 collide. The gap between rows is 4px. A 14px caption cannot live there.
- `space-between` on the axis is a false scale whenever the last label is not the end of the data.
- Nine to seventeen hourly labels across a 16-hour book will collide. 15, 30, and 60 minutes are right for a short book and wrong for lithography.
- The two charts already share a column. They must share the window, the tick labels, and the row order, or the eye cannot compare them.
- The legend already has area, moved, down, maintenance, now, and due. Rework appears only when a rework bar exists. Another swatch on every scenario wraps the legend past the frame.
- By-lot rows name the lot. Repeating the id on every step is optional. Tool rows do not name the lot, so the id has to be on the bar.

Proposal: 30px bars, 14px type, labels inside the bar or not at all, ticks positioned by time, one window object from the server.

## Role C — hackathon judge

Weights used: Impact 30, Technical 20, Innovation 15, Demo 15, Product and UX 10, Sponsor 10.

Independent critique of the baseline:

- The three-second read is the headline, the refusal, the three numbers, and the two charts. The lithography headline is "LOT-1001 leaves LITHO-02". If that bar has no id, the chart does not support the sentence.
- The lithography after chart's empty right side is the win (on-time delivery 83.3 to 100, tardiness 840 to 0, makespan 965 to 420). Do not zoom that chart away from the before chart.
- Rush, shortage, rework, and queue time currently spend the right half of the chart on a due the bars never reach. In a recording that reads as "nothing happened".
- A new reticle row or a queue-time band would add a fourth idea to a frame that already has to land in one screen.
- The outline on a moved bar, the faded bar it left, and the hatch are enough vocabulary. Do not add a second encoding for the same fact.

Proposal: zoom the four short scenarios to their work, leave the lithography pair on the long window, and spend the pixels on bar height and a readable id for the lot the headline names.

## Cross-critique

Role A on B: in-bar-or-silent is honest, and it fails the lithography step. A 90-minute step is about 37px on the 1080-minute window, and "1001" at 14px is 34px of glyphs plus padding. Silent there hides the lot the planner came to see. The caption has to stay inside the row.

Role A on C: agreeing to keep the long lithography window. Rejecting a separate zoom on the after chart. The two charts are a comparison only when a minute is the same width.

Role B on A: the edge chip for a far due is right, and it cannot sit on top of a bar. The first drawing of "2001 due" on the line covered LOT-1001 and LOT-1004 on the rush chart. Words go on the axis.

Role B on C: taller bars are the demo fix. A new color would not survive the recording. Keep the existing palette.

Role C on A: queue-time bands and a reticle row lose the three-second read and were going to collide with the hatch. They stay on Analyze and Verify. The dashed due and the axis caption are the compromise that keeps the priority lot visible.

Role C on B: a caption rail inside the row is acceptable. A caption between rows is the bug being removed.

## Final spec

Decisions:

- `shared_window` in `resilimes/domain/gantt.py` is the only scale. The orchestrator puts it on `gantt.window`. Both charts read that object. The origin is 0.
- The end is the later bar, plus `max(end // 20, 10)` minutes, snapped up to the next tick.
- The step is the finest of 15, 30, 60, 120, 180, 240 such that `span <= step * 8` (at most nine labels). Lithography uses 180 and ends at 1080 (06:30 through 00:30). Rush and rework use 120 and end at 600 (through 16:30). Shortage and queue time use 60 and end at 480 (through 14:30).
- Ticks are absolutely positioned. The first is "Now" and is not translated. The last is translated by its own width. The middle ones are centered on the instant they name.
- Down and maintenance are drawn only inside the window. A block that continues past the end gets an 8px dark cap. In these five scenarios the cap is unused: the lithography down of 600 sits inside 1080, and DEP-01 maintenance of 240 sits inside every window. The cap is still the rule, so a shorter book cannot be stretched by a long down event.
- A priority-1 due inside the window is a dashed line with no words on the line. The words sit on a second axis row. A due past the window is the same caption, flush to the right edge of that row ("1001 due" on rush, shortage, rework, and queue time). LOT-2001's due stays a line at 09:30 on the rush chart.
- Tracks are 48px. Bars are 30px and start 16px down, which leaves a 16px caption rail in the row. An id draws inside the bar when it fits at 14px. Otherwise it draws in the rail if it does not touch another rail caption. Moved and new bars take the rail first. If neither fits, the bar stays quiet and the tooltip keeps the id.
- Padding on the id is 1px. "1001" measures 34px, so the 37px lithography step on the long window can carry its id. The old 3px padding measured 40px and left that step quiet.
- By-lot does not use the rail. The row label is the lot. The same window, the same ticks, and the same due caption apply. Wait links between steps stay.
- Area color, the moved outline, the faded leaving bar, the rework stripe, the bottleneck mark on the tool name, and the legend rules are unchanged. Rework is in the legend only when a rework bar exists.

Rejected:

- A non-linear scale.
- A separate window per chart.
- Dropping a tool row that has only maintenance.
- Clipping the lithography bar that ends at 965.
- Forcing 60-minute ticks on the lithography book.
- Floating captions into the gap between rows.
- Shrinking type under 14px.
- A queue-time band on the tool Gantt.
- A reticle resource row.
- Stretching the axis out to a priority-1 due or a down event.

## Round 1

The first build had the shared window, absolute ticks, 30px bars, and in-bar-or-silent labels. Frames: `screenshot_gantt_r1_litho.png` and the rush, shortage, rework, queue-time, and by-lot pair.

Measured on every scenario, tool view and by-lot: `scrollHeight` 1080, recover panel overflow 0, legend bottom 1058, both charts the same scale, no tick rectangle collisions, no label rectangle collisions.

Windows matched the spec: lithography 1080, rush 600, shortage 480, rework 600, queue time 480. The lithography after chart's last bar reached 39% of the track. The before chart's last bar reached 89%. That is the recovery.

Role A: the late bar, the hatch, Now, and the off-window due were right. Signed the window.

Role B: no collisions, and the lithography step the headline names was silent. Twenty of twenty-six lithography bars were silent. "1001" at the old padding did not fit a 37px bar.

Role C: rush, shortage, rework, and queue time finally fill the frame, and the moved lithography bar still had no id. Not signed.

## Round 2

Fix from Role B and Role C: 1px padding, and a caption rail inside the tool row. By-lot stays on the row label.

Re-measured: lithography rail captions 12, rail collisions 0, label collisions 0, tick collisions 0. The 37px LOT-1001 lithography bars are labeled. Moved bars on rush, shortage, and rework are labeled. Queue time has no moved bars; the hold is the shorter after book (last bar at 71% versus 87%). Rework draws one striped bar. Scroll, panel, and legend were unchanged. By-lot rush, the tallest book at seven rows, still cleared the card by more than 200px.

The due caption was still drawn on the dashed line. On the rush chart the rectangle for "2001 due" covered LOT-1001 and LOT-1004.

Role A: the line can cross a bar. The words cannot. Move the words.

Role B: a second axis row, 16px, accent color, under the clock. An off-window due uses the right edge of that row. Line-height 16px so the caption row does not touch the clock row.

Role C: the dashed line is the three-second mark. The words are there when the recording holds.

Confirming measurement after that move, tool view, all five scenarios, plus queue-time by-lot:

- Due captions no longer intersect clock ticks, bars, or rail captions.
- In-bar labels do not intersect each other. Rail captions do not intersect each other.
- `scrollHeight` 1080, panel overflow 0, legend bottom 1058. The axis ends at least 264px above the bottom of the chart card.

Rush by-lot remains inside the card (the previous round cleared it by 226px, and the extra axis row is 16px).

## Sign-off

Role A signs. The window is the work, Now is the left edge, the late lithography bar is on the chart, down and maintenance stay on their tools, LOT-2001's due is a line at 09:30, and LOT-1001's far due is named on the axis instead of stretching the scale.

Role B signs. One type size, one window, ticks on the instants they name, ids inside the row, due words under the clock, and the frame does not scroll.

Role C signs. The lithography pair shows the lot leaving the down scanner and the book ending before the old makespan. The other four scenarios use the width for the lots that moved, the hold, or the rework stripe. The refusal and the three numbers are still the sentence. The chart now agrees with it.

## Round 3 — fill the card, keep every id off the edges

The signed frames still left the bottom of each chart card empty, and several ids sat on a bar edge or on the Now line. Lithography's 1001 on LITHO-02 and on ETCH-01, the 1002 at the left of a row, and the CMP captions were the examples.

Role A: the window stays as signed. Taller rows make the down hatch and the moved bars easier to read during recovery. A by-lot book with seven rows has to stay inside the same 1920×1080 frame.

Role B: the row height is the card height divided by the row count, clamped between 48px and 112px. At this frame the clamp does not bind, so six tool rows are 90px and the axis is flush with the bottom of the card, 6px under the last row. The bar grows with the row and keeps an 18px caption band above it. An id is drawn inside the bar only when 4px remains on both sides and the glyphs clear the Now line. Otherwise it sits 7px to the right of the bar. Otherwise it sits in the caption rail, which ends 4px above the bar and starts 6px clear of Now. Two ids never share a rectangle.

Role C: the empty card made the recovery look small on a recording. The taller bars are the picture. No new color, no new row.

Measured at 1920×1080 after the change. `scrollHeight` 1080, recover panel overflow 0, legend bottom 1058. Tool rows are 90px on lithography, rush, shortage, and queue time, and 93px on rework. Slack under the axis is 0. Rush by lot is 6 rows at 90px beside 7 rows at 76px, and that frame still does not scroll. Glyph rectangles do not intersect a bar edge, the Now line, or another id, on every scenario in both views.

Role A signs. The scale, the late bar, the hatch, and the dues are unchanged, and the rows now use the card.

Role B signs. The axis is in the same place on both charts, the ids are inside a bar, just to its right, or in the rail, and nothing touches an edge.

Role C signs. The move is the tall object in the card, and the frame is still one screen.
