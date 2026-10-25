# Hard Q-time mode (default off)

Leading fabs do not accept Q-time violations, so the schedule should treat the
dataset CQT window as a hard constraint: a lot starts the CQT origin step only
if its target step can start within the limit. Real disruptions still break
some windows after the origin started. Such a lot is never parked or excluded.
It is expedited.

Switch: `make_sim(..., hard_qtime=True)` or `RESILIMES_HARD_QTIME=1`. Default
off. With it off, a run is event-for-event main: the golden-digest tests
(`tests/test_sched_freeze.py`, `tests/test_fab_layout.py`) pass unchanged with
the two new result fields (`qtime_causes`, `hard_qtime`) left out, and
`tests/test_hard_qtime.py` checks that default, `hard_qtime=False` and
`RESILIMES_HARD_QTIME=0` give the same digest. A 12 h plan-mode and EDD run
against main f359e63 matched in every field except wall-clock timings. Only dataset values are
used: CQT limits, process times, batch sizes, transport and the PM calendar. No
weights, due dates or seeds were tuned. Code: `resilimes/smt/hard_qtime.py`,
hooks in `resilimes/smt/simulate.py`.

## Mechanism

1. **Miss causes (always on, read-only).** At each window deadline the sim
   records why the window was missed: `upstream` (lot still at an intermediate
   step of a multi-step span), `queueing` (at the target, every up tool busy),
   `batch_fill` (at a batch target with an idle tool, waiting to fill),
   `tool_down_pm` (target family lost at least one tool-equivalent of up time
   while the lot waited), `breakdown_rework` (a breakdown aborted the lot's
   step), `transport`. Windows already open in the t=0 WIP are counted as
   `inherited`. `RunResult.qtime_causes` holds the counts.
2. **Origin gate (whole-segment Q-time kanban).** A lot may start a CQT
   origin only if every family of the CQT segment can still be cleared in
   time: each measured intermediate step and the target. For each such step
   the lot's latest start is the target's latest start (origin start +
   process time + limit) minus what the lot still needs from that step to
   the target (dataset cycle times and transport). Per family, the work
   already committed there plus the candidate's must fit the family's up
   tools before each item's latest start (fluid earliest deadline first:
   free time from `busy_until`, PM overlap subtracted, batch steps as
   cycle / batch-min lots, missed lots counted first). Committed work is the
   remaining segment steps of every lot inside an open window or running at
   a CQT origin; a step's entry is released when the lot starts it. Only the
   current down state is used, never future breakdowns. The check is re-run
   on every origin start attempt, so a family going down blocks new origins
   at once. Gated tools are woken when the blocking family finishes a step or
   a tool comes back up (30 min fallback). A segment whose minimum
   remaining time already exceeds the limit is blocked outright.
3. **Never gate a lot that is inside or past a window**, being expedited, or
   in re-clean/rework (`exempt_origin_starts`).
4. **Expedite.** A lot that missed its window (including inherited windows)
   is flagged until its target step starts, also through Q-time hold,
   re-clean and the re-opened window. Inside its SMT2020 class tier (strict
   tiers unchanged) it ranks right behind lots whose open window is lost
   unless they start now and ahead of everyone else, the same place main
   gives a hot lot (a Q-time-urgent lot outranks a non-late hot lot). At a
   batch tool an expedited lot waits at most the hot-lot batch wait. ResiliMES'
   downstream-ready gate is skipped for it. A lot at an intermediate step of an
   open window gets the same rank as at the target: "inside a window" means
   any step up to and including the target, with slack measured to the
   target's latest start (`tests/test_hard_qtime.py` checks both the segment
   entries and this rank). Nothing in main excluded violated
   lots before (fix-3 holds and the planning layer only reorder); this keeps
   that and moves them up.

Putting missed lots above every lot still inside its window was tried first.
That makes savable lots miss in turn (24 h, plan mode: 78% true Q-time vs 95%
off), so missed lots sit one level below the "start now or lose it" lots.

## Study

`python -m resilimes.smt.hard_qtime_study OUT.json` (report: `--report`).
Published book, seeds 1-3, 7 days, closed fab, main's default settings
(planning layer default from #36, r2 fixes 2+3). True Q-time is the event
replay of `qtime_study`. Totals are over 3 seeds unless "/run".

### Why windows are missed today (main default, hard mode off)

| Cause (3 seeds) | Planning (default) | EDD |
|---|---:|---:|
| inherited (t=0 WIP) | 446 | 565 |
| upstream (still before target) | 1467 | 977 |
| queueing at target | 184 | 1885 |
| batch fill at target | 0 | 0 |
| target tool down / PM | 46 | 268 |
| breakdown / rework after start | 2 | 0 |
| transport | 29 | 15 |
| true Q-time % | 94.62 | 89.23 |

In the default mode most misses are not at the target at all: the lot is still
working through the intermediate steps of a multi-step span. EDD's misses are
mostly queueing at the target.

### Hard mode (whole-segment gate)

| KPI | Planning | Planning + hard | EDD | EDD + hard |
|---|---:|---:|---:|---:|
| on-time % | 91.96 | 89.74 | 91.96 | 88.89 |
| completed / run | 503.7 | 459.3 | 520.0 | 513.0 |
| true Q-time % | 94.62 | 97.15 | 89.23 | 97.39 |
| true Q-time % after first 24 h | 95.00 | 99.03 | 91.53 | 99.14 |
| weighted tardiness (min/run) | 20,950 | 32,432 | 21,046 | 36,218 |
| missed, avoidable (upstream + batch + queue) | 1651 | 551 | 2862 | 585 |
|   of which upstream | 1467 | 225 | 977 | 267 |
| missed, disruption (down/PM, rework, transport) | 77 | 96 | 283 | 97 |
| missed, inherited | 446 | 426 | 565 | 415 |
| expedited exception lots | - | 905 | - | 914 |
| recovered (target started) by 7 d | - | 862 | - | 914 |
| time to recover, mean / p90 (min) | - | 652 / 2670 | - | 620 / 2558 |

The off columns are identical to the first study (off == main). For
reference, the first, target-only kanban gave planning + hard 92.86% true
Q-time with 454.3 completed/run, and EDD + hard 93.59% with 444.0.

Per seed, completions for planning + hard are 510 / 419 / 449 vs 508 / 513 /
490 off. Seed 2 (long downs) is still the worst case. EDD + hard stays within
2% of EDD's output on every seed (521 / 517 / 501 vs 529 / 519 / 512).

Time to recover runs from the miss to the start of the target step. It
includes the Q-time hold and, for multi-step spans, the remaining intermediate
steps, so it is long even for a top-priority lot.

## Honest reading

* Checking the whole segment fixes what the target-only kanban could not
  see. Upstream misses fall from 1467 to 225 (planning) and avoidable misses
  fall about 3x to 5x. After the first 24 h (mostly t=0 WIP that had already
  missed) true Q-time is about 99% in both modes.
* It does not beat the default overall. Planning + hard costs 44 completed
  lots per run (-9%), 2.2 pp on-time and +55% weighted tardiness. EDD + hard
  keeps throughput (-1%) but still loses 3.1 pp on-time and adds +72%
  tardiness. Of the four, EDD + hard has the best Q-time and the
  best Q-time/throughput trade-off.
* The remaining misses are mostly inherited windows and disruptions after
  the start, which a start gate cannot prevent. Those lots are expedited, and
  all but 43 (planning) recover within the 7 days.

Recommendation: keep hard mode off and the planning default as the demo
default, because hard mode trades delivery and output for Q-time. Hard mode
is now a credible "zero-tolerance" switch (about 97% overall and 99% after
the first day). Use it where Q-time compliance outranks output. With hard mode
on, EDD dispatch is the better pairing than the planning layer.
