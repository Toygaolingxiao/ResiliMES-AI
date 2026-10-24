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
2. **Origin gate (per-target Q-time kanban).** A lot may start a CQT origin
   only if the work already committed to the target family plus its own fits
   the family's up tools before each lot's latest start (fluid earliest
   deadline first: free time from `busy_until`, PM overlap subtracted, batch
   steps as cycle / batch-min lots). Committed work is every lot inside an
   open window or running at a CQT origin heading there. Only the current
   down state is used, never future breakdowns. Being committed is the
   capacity reservation: it is released when the lot starts its target step,
   and the check is re-run on every origin start attempt, so a target that
   goes down blocks new origins at once. Gated tools are woken when the target
   family finishes a step or a tool comes back up (30 min fallback).
3. **Never gate a lot that is inside or past a window**, being expedited, or
   in re-clean/rework (`exempt_origin_starts`).
4. **Expedite.** A lot that missed its window (including inherited windows)
   is flagged until its target step starts, also through Q-time hold,
   re-clean and the re-opened window. Inside its SMT2020 class tier (strict
   tiers unchanged) it ranks right behind lots whose open window is lost
   unless they start now and ahead of everyone else, the same place main
   gives a hot lot (a Q-time-urgent lot outranks a non-late hot lot). At a
   batch tool an expedited lot waits at most the hot-lot batch wait. ResiliMES'
   downstream-ready gate is skipped for it. Nothing in main excluded violated
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

### Hard mode

| KPI | Planning | Planning + hard | EDD | EDD + hard |
|---|---:|---:|---:|---:|
| on-time % | 91.96 | 89.74 | 91.96 | 85.40 |
| completed / run | 503.7 | 454.3 | 520.0 | 444.0 |
| true Q-time % | 94.62 | 92.86 | 89.23 | 93.59 |
| true Q-time % after first 24 h | 95.00 | 94.11 | 91.53 | 95.41 |
| weighted tardiness (min/run) | 20,950 | 31,139 | 21,046 | 56,351 |
| missed, avoidable (upstream + batch + queue) | 1651 | 1644 | 2862 | 1353 |
| missed, disruption (down/PM, rework, transport) | 77 | 116 | 283 | 117 |
| missed, inherited | 446 | 426 | 565 | 415 |
| expedited exception lots | - | 1623 | - | 1426 |
| recovered (target started) by 7 d | - | 1533 | - | 1426 |
| time to recover, mean / p90 (min) | - | 714 / 2470 | - | 689 / 2510 |

Per seed, hard mode is uneven. Seed 2 (long target downs) is the worst case:
EDD + hard completes 310 lots vs 519, planning + hard 393 vs 513, because the
gate stops origin starts while target families are down. On seed 3 planning +
hard is better on every Q-time and throughput number (95.07% vs 94.33%, 495
vs 490 completed).

Time to recover runs from the miss to the start of the target step. It
includes the Q-time hold and, for multi-step spans, the remaining intermediate
steps, so it is long even for a top-priority lot.

## Honest reading

* With EDD, hard mode removes about half of the avoidable misses (2862 to
  1353) and gains 4.4 pp true Q-time. It costs 76 completed lots per run and
  2.7x weighted tardiness.
* With the planning default, hard mode does not help. Q-time drops 1.8 pp,
  completions drop 49 per run and tardiness goes up 49%. The default already
  avoids queueing at the target. Its remaining avoidable misses are
  `upstream`: delays at the intermediate steps of a span. The kanban only
  models target capacity, so it cannot see them.
* Expedited lots take target capacity first, which is right for the fab but
  costs other lots. Early in the run this is mostly the 400+ windows already
  missed in the snapshot WIP.

Recommendation: keep hard mode off and the planning default as the demo
default. Show hard mode as the "zero-tolerance" switch, together with the
per-cause breakdown. A real hard mode would also need to model the
intermediate steps of the span, which is the next step.
