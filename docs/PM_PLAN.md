# PM plan: staggered per-tool PM calendar

`resilimes/smt/pm_plan.py` is part of the planning layer. It turns the SMT2020
family PM calendars into one PM calendar **per tool**, and it is read by:

- the scheduling layer, as each tool's PM windows;
- dispatch, through the rule "never start a lot that would run into a PM".

Planning (`planning.py`) can use the calendar through an optional hook. The
simulator does **not** use it yet; see [Integration](#integration-with-simulatepy-separate-step).

## Why

SMT2020 publishes PM calendars per tool family:

- `pmcal.txt` holds the calendars, linked to families through `attach.txt`.
- The time-based calendars are WK, MN and QT.
- Each calendar gives a first start (FOA), an interval (MTBPM) and a duration (MTTR).

`simulate.pm_windows` copies the family calendar onto every tool, so a whole
family goes down at once. For example:

- all 23 `Litho_BE_110` scanners stop for 6.65 h every week;
- all 13 `Diffusion_FE_94` furnaces stop for 26.2 h every month.

During those windows the family has zero capacity. No fab plans PMs that way.

## Mapping to the published calendar

Take a family with `n` tools (tool index order `0..n-1`) and one of its
calendars `c`:

- first start `F` (after the same optional `shift_sec` as `simulate.pm_windows`);
- interval `I`;
- duration `D`.

The plan is built from those four values and nothing else. It has no tuned
constants.

1. **Same occurrences.** The dataset calendar has occurrences `F + k·I`.
   - Occurrence `k` is kept when it starts before the horizon and ends after 0,
     which is exactly the rule in `simulate.pm_windows`.
   - Every tool keeps exactly those occurrence indices `k`, and every PM keeps
     its published duration.
   - So the PM count per tool, per family and for the fab equals the dataset's
     over the plan horizon, and so do the PM hours.
2. **Even stagger, by tool index.**
   - Tool `i`'s nominal start for occurrence `k` is `F + k·I − (n−1−i)·I/n`.
   - The last tool keeps the published time. The others are spread `I/n` apart
     before it.
   - A nominal start is never earlier than `F + k·I − I`, meaning the published
     time minus one interval. Each tool's nominal interval is still `I`.
   - A nominal start before 0 would be moved to 0. With the SMT2020 data this
     never happens, because every FOA is later than `(n−1)/n·I`.
3. **Lanes (minimum overlap).**
   - The family PM load is `L = n · Σ_c D_c / I_c`, the average number of tools
     in PM.
   - At most `lanes = max(1, ceil(L))` tools of the family may be in PM at once.
   - When `L ≤ 1`, `lanes` is 1 and the family is fully staggered.
   - When `L > 1`, full staggering is impossible: at least `ceil(L)` tools must
     overlap at some point. The family is flagged with `overlap_required`.
   - `overfull_calendars` lists the calendars that cannot be staggered even on
     their own, because `n·D > I`. For `Litho_FE_92` that is WK:
     26 × 6.65 h = 172.9 h > 168 h.
4. **Single-tool family.** It keeps the published calendar unchanged.
5. **Placement.**
   - A family's occurrences are placed in this order: nominal start, then the
     calendar's order in the dataset, then tool index.
   - Each occurrence starts at the earliest time, at or after its nominal start,
     when two conditions hold for its whole duration:
     - its tool is not already in PM;
     - fewer than `lanes` tools of the family are in PM.
   - WK, MN and QT drift against each other, so some occurrences start later
     than nominal. `max_delay_h` and `mean_delay_h` report how much later.
   - Delays never change the count or the duration of any PM.

The output is deterministic: the same fab, horizon and shift always give the
same plan.

**Horizon.** The count is preserved over the horizon the plan is built for.
Because the stagger only moves PMs earlier, a shorter sub-window sees some PMs
sooner than the dataset does. For example, the first 2 days have 53 staggered
PMs and 0 in the dataset. Build the plan once for the planning window and give
the same windows to every consumer.

## API

```text
build_pm_plan(fab, horizon, *, shift_sec=0.0) -> PmPlan
  PmPlan.per_tool()            same shape as simulate.pm_windows (list per tool index)
  PmPlan.tool_windows(tool)    one tool's windows
  PmPlan.tool_spans(tools)     merged windows per tool (capacity checks)
  PmPlan.windows               PmWindow(tool, family, calendar, occurrence,
                               published_sec, nominal_sec, start_sec, end_sec)
  PmPlan.families[fam]         FamilyPm before/after figures
  PmPlan.flagged()             families that need overlap
published_windows(fab, horizon, *, shift_sec=0.0)   dataset calendar per tool (== pm_windows)
markdown_table(plan)                                the table below
python -m resilimes.smt.pm_plan                     prints it for the 56-day window
```

## Planning hook (additive)

The hook adds these pieces to `planning.py`:

- `PlanInput.tool_pm` and `plan_input(..., tool_pm=None)`: per-tool PM windows.
- `with_pm_plan(fab, inp)`: fills `tool_pm` from `build_pm_plan` over the
  planning window `[0, release_until)`. Occurrences that the dataset starts
  after the window keep the published calendar, so the count stays equal over
  any longer horizon too.
- `scenario_input(..., staggered_pm=False)` and `plan_scenario(..., staggered_pm=False)`.
- In the forward litho pass, each idle scanner checks **its own** next PM. A
  scanner that cannot fit the head lot waits for its PM to end, and the next
  scanner is tried.
- In the daily capacity check, each scanner's up time is computed from its own
  windows.

The default is `tool_pm=None`. In that case every tool gets the family
calendar, and the output is **bit-identical** to the previous planner on the
`published`, `pm_avoid` and `litho_down` scenarios (ranks, bands, plan finish
times and the litho table). A test also checks that passing the family
calendar explicitly per tool reproduces the default.

## Before / after per family (published calendar, 56-day window)

- "before" is `simulate.pm_windows`: every tool carries the family calendar.
- "after" is `build_pm_plan(fab, 56 days)`.
- "min available" is the fewest tools of the family that are up at any moment,
  counting PM only.
- Flags: `overlap` means L > 1; `(WK n·D>I)` means the weekly calendar alone is
  overfull.

| family | tools | calendars I/D h | load | lanes | flag | max in PM before→after | min available before→after | PMs | max/mean delay h |
|---|---|---|---|---|---|---|---|---|---|
| DefMEt_FE_118 | 2 | MN 720/13.76, QT 2184/27.52 | 0.06 | 1 |  | 2→1 | 0 (0%)→1 (50%) | 2→2 | 0.00/0.00 |
| DefMet_BE_33 | 2 | MN 720/13.76, QT 2184/27.52 | 0.06 | 1 |  | 2→1 | 0 (0%)→1 (50%) | 2→2 | 0.00/0.00 |
| DefMet_BE_42 | 1 | MN 720/13.76, QT 2184/27.52 | 0.03 | 1 |  | 1→1 | 0 (0%)→0 (0%) | 2→2 | 0.00/0.00 |
| DefMet_FE_10 | 2 | MN 720/13.76, QT 2184/27.52 | 0.06 | 1 |  | 2→1 | 0 (0%)→1 (50%) | 2→2 | 0.00/0.00 |
| DefMet_FE_106 | 1 | MN 720/13.76, QT 2184/27.52 | 0.03 | 1 |  | 1→1 | 0 (0%)→0 (0%) | 2→2 | 0.00/0.00 |
| DefMet_FE_34 | 2 | MN 720/13.76, QT 2184/27.52 | 0.06 | 1 |  | 2→1 | 0 (0%)→1 (50%) | 2→2 | 0.00/0.00 |
| DefMet_FE_43 | 5 | MN 720/13.76, QT 2184/27.52 | 0.16 | 1 |  | 5→1 | 0 (0%)→4 (80%) | 5→5 | 0.00/0.00 |
| Diffusion_BE_123 | 9 | MN 720/26.21, QT 2184/52.42 | 0.54 | 1 |  | 9→1 | 0 (0%)→8 (89%) | 9→9 | 0.00/0.00 |
| Diffusion_FE_100 | 3 | MN 720/26.21, QT 2184/52.42 | 0.18 | 1 |  | 3→1 | 0 (0%)→2 (67%) | 3→3 | 0.00/0.00 |
| Diffusion_FE_101 | 10 | MN 720/26.21, QT 2184/52.42 | 0.60 | 1 |  | 10→1 | 0 (0%)→9 (90%) | 10→10 | 0.00/0.00 |
| Diffusion_FE_120 | 8 | MN 720/26.21, QT 2184/52.42 | 0.48 | 1 |  | 8→1 | 0 (0%)→7 (88%) | 8→8 | 0.00/0.00 |
| Diffusion_FE_122 | 6 | MN 720/26.21, QT 2184/52.42 | 0.36 | 1 |  | 6→1 | 0 (0%)→5 (83%) | 6→6 | 0.00/0.00 |
| Diffusion_FE_125 | 5 | MN 720/26.21, QT 2184/52.42 | 0.30 | 1 |  | 5→1 | 0 (0%)→4 (80%) | 5→5 | 0.00/0.00 |
| Diffusion_FE_126 | 4 | MN 720/26.21, QT 2184/52.42 | 0.24 | 1 |  | 4→1 | 0 (0%)→3 (75%) | 4→4 | 0.00/0.00 |
| Diffusion_FE_127 | 8 | MN 720/26.21, QT 2184/52.42 | 0.48 | 1 |  | 8→1 | 0 (0%)→7 (88%) | 8→8 | 0.00/0.00 |
| Diffusion_FE_44 | 7 | MN 720/26.21, QT 2184/52.42 | 0.42 | 1 |  | 7→1 | 0 (0%)→6 (86%) | 7→7 | 0.00/0.00 |
| Diffusion_FE_94 | 13 | MN 720/26.21, QT 2184/52.42 | 0.79 | 1 |  | 13→1 | 0 (0%)→12 (92%) | 13→13 | 0.00/0.00 |
| LithoTrack_BE_117 | 5 | WK 168/6.65, MN 720/13.29, QT 2184/26.59 | 0.35 | 1 |  | 5→1 | 0 (0%)→4 (80%) | 40→40 | 6.65/0.26 |
| LithoTrack_FE_115 | 41 | WK 168/6.65, MN 720/13.29, QT 2184/26.59 | 2.88 | 3 | overlap (WK n·D>I) | 41→3 | 0 (0%)→38 (93%) | 328→328 | 7.44/0.08 |
| LithoTrack_FE_95 | 40 | WK 168/6.65, MN 720/13.29, QT 2184/26.59 | 2.81 | 3 | overlap (WK n·D>I) | 40→3 | 0 (0%)→37 (92%) | 360→360 | 6.09/0.05 |
| LithoTrack_FE_96 | 2 | WK 168/6.65, MN 720/13.29, QT 2184/26.59 | 0.14 | 1 |  | 2→1 | 0 (0%)→1 (50%) | 18→18 | 1.85/0.10 |
| Litho_BE_110 | 23 | WK 168/6.65, MN 720/13.29, QT 2184/26.59 | 1.61 | 2 | overlap | 23→2 | 0 (0%)→21 (91%) | 184→184 | 6.65/0.11 |
| Litho_BE_93 | 4 | WK 168/6.65, MN 720/13.29, QT 2184/26.59 | 0.28 | 1 |  | 4→1 | 0 (0%)→3 (75%) | 32→32 | 12.09/0.38 |
| Litho_BE_99 | 3 | WK 168/6.65, MN 720/13.29, QT 2184/26.59 | 0.21 | 1 |  | 3→1 | 0 (0%)→2 (67%) | 27→27 | 11.69/0.43 |
| Litho_FE_111 | 20 | WK 168/6.65, MN 720/13.29, QT 2184/26.59 | 1.40 | 2 | overlap | 20→2 | 0 (0%)→18 (90%) | 180→180 | 12.09/0.12 |
| Litho_FE_35 | 2 | WK 168/6.65, MN 720/13.29, QT 2184/26.59 | 0.14 | 1 |  | 2→1 | 0 (0%)→1 (50%) | 18→18 | 10.89/0.60 |
| Litho_FE_92 | 26 | WK 168/6.65, MN 720/13.29, QT 2184/26.59 | 1.83 | 2 | overlap (WK n·D>I) | 26→2 | 0 (0%)→24 (92%) | 208→208 | 12.55/0.21 |
| Litho_FE_98 | 4 | WK 168/6.65, MN 720/13.29, QT 2184/26.59 | 0.28 | 1 |  | 4→1 | 0 (0%)→3 (75%) | 32→32 | 8.49/0.27 |
| LithoMet_BE_18 | 11 | MN 720/13.76, QT 2184/27.52 | 0.35 | 1 |  | 11→1 | 0 (0%)→10 (91%) | 11→11 | 0.00/0.00 |
| LithoMet_FE_19 | 14 | MN 720/13.76, QT 2184/27.52 | 0.44 | 1 |  | 14→1 | 0 (0%)→13 (93%) | 14→14 | 0.00/0.00 |
| Litho_REG_BE_63 | 8 | MN 720/13.76, QT 2184/27.52 | 0.25 | 1 |  | 8→1 | 0 (0%)→7 (88%) | 8→8 | 0.00/0.00 |
| Litho_REG_FE_64 | 12 | MN 720/13.76, QT 2184/27.52 | 0.38 | 1 |  | 12→1 | 0 (0%)→11 (92%) | 12→12 | 0.00/0.00 |
| TF_Met_FE_45 | 2 | MN 720/13.76, QT 2184/27.52 | 0.06 | 1 |  | 2→1 | 0 (0%)→1 (50%) | 2→2 | 0.00/0.00 |
| TF_Met_FE_61 | 2 | MN 720/13.76, QT 2184/27.52 | 0.06 | 1 |  | 2→1 | 0 (0%)→1 (50%) | 2→2 | 0.00/0.00 |

Summary:

- Fab PM count: 1566 before, 1566 after.
- Flagged families (minimum overlap kept): `Litho_FE_92`, `Litho_BE_110`,
  `Litho_FE_111` (2 at a time), and `LithoTrack_FE_115`, `LithoTrack_FE_95`
  (3 at a time).
- Every furnace (`Diffusion_*`) and every other family now loses at most one
  tool at a time.

## Cross-check: litho day overloads

This compares `plan_scenario(fab)` with `plan_scenario(fab, staggered_pm=True)`.

- Demand is the litho hours that must start that day (by latest start).
- Capacity is the scanner up-hours × availability, after PM.
- Total capacity over the 56 days is unchanged: BE_110 27604 h before and
  27603 h after; FE_92 31204 h before and 31204 h after.
- The PM hours are spread instead of falling all at once.

**Litho_BE_110** (23 scanners)

| day | demand h | capacity h before | capacity h after | overload |
|---|---|---|---|---|
| 7 | 431.1 | 372.9 | 489.7 | yes → no |
| 14 | 447.4 | 372.9 | 482.9 | yes → no |
| 21 | 453.3 | 372.9 | 485.8 | yes → no |
| 28 | 438.0 | 372.9 | 483.5 | yes → no |
| 30 | 449.6 | 230.2 | 482.9 | yes → no |
| 35 | 446.0 | 372.9 | 495.3 | yes → no |
| 42 | 444.3 | 372.9 | 495.3 | yes → no |
| 49 | 441.1 | 372.9 | 509.7 | yes → no |

Lowest daily capacity: 230.2 h before, 482.9 h after. The highest is 515.9 h
in both cases.

**Litho_FE_92** (26 scanners)

| day | demand h | capacity h before | capacity h after | overload |
|---|---|---|---|---|
| 21 | 426.5 | 421.6 | 551.1 | yes → no |
| 28 | 503.2 | 421.6 | 546.1 | yes → no |
| 31 | 500.1 | 318.6 | 549.9 | yes → no |
| 35 | 502.4 | 421.6 | 560.2 | yes → no |
| 42 | 507.2 | 421.6 | 560.2 | yes → no |
| 49 | 513.3 | 421.6 | 572.3 | yes → no |

Lowest daily capacity: 318.6 h before, 546.1 h after.

**All litho families:**

| | overload days before | overload days after |
|---|---|---|
| `published` | 32 (BE_110 8, FE_92 6, FE_111 7, FE_98 5, others 6) | 1 (FE_35 day 27, 2 scanners) |
| `pm_avoid` | 39 | 0 |

These overloads were PM-day artefacts. With the PM hours spread, daily demand
(≈ 430–513 h) is below the nearly flat capacity. The same PM hours are lost
over the window either way.

Side effect:

- The planned mean litho wait of WIP lots rises from 173.8 h to 180.6 h.
- The cause is that the stagger pulls PMs that the dataset places on days
  27–33 (MN) earlier, into the congested first weeks.
- Bands barely move (`published`: 20 critical and 1 behind in both).

This is a planning figure, not a simulation result.

## Flexible PM execution (`pm_decision`)

The staggered plan gives every PM a *planned* start. A PM does not have to
run at that exact time. When a family has a lot of WIP waiting, its PMs move
later; when a tool is idle with nothing to run, it can take its PM early. All
of it is pure logic in `pm_plan.py`; `simulate.py` is not changed.

### Window: the fab's ±1 day rule

SMT2020 has no PM tolerance field. The window is **the fab owner's rule**, not
a dataset field: a PM may move **up to ±24 h** from its planned start
(`PM_WINDOW_SEC = 24 h`, one parameter, not tuned on results).

```text
earliest = max(planned - 24 h, end of the tool's previous planned PM, 0)
latest   = min(planned + 24 h, start of the tool's next planned PM - this PM's duration)
```

"Previous / next planned PM" means the same tool, any calendar (WK, MN and QT
windows interleave). So two PMs of one tool can never overlap or merge. In the
56-day plan, 73 of 1566 PMs have a latest start capped by the tool's next PM,
and 92 have an earliest start capped by the previous PM's end. Some are
back-to-back and have no slack on that side.

### Decision at every scheduling tick

`pm_decision(tool, now, state) -> PmDecision` looks at the tool's next PM that
is not yet committed. The checks run in this order:

| result | when |
|---|---|
| `defer` (not logged) | no PM left, the previous PM is still on, or `now < earliest` |
| `start_now` | inside the window, all of: tool up and idle; fewer than `lanes` tools of the family in PM (the stagger plan's limit); the family's eligible queue fits on the other tools during the PM duration. Reason: `no_queue` or `queue_absorbed`, plus `early` / `on_time` / `late` |
| `defer` | `tool_down`, `tool_busy` (never start on a running tool), `concurrency_cap(k/lanes)`, or `queue_heavy(Qh>Ah)`: the queue is larger than what the remaining up tools can process during the PM, so taking this tool down now would grow the queue |
| `force` | waiting one more tick (300 s) would pass `latest`. The PM starts now, or as soon as the current lot or batch, a down, or the previous PM is over. Reason: `latest_start,<what held it>`. If the family is already at its lane cap, the force still goes ahead and is counted as `forced_over_cap` |

- **Queue measure.** `queue_work_sec(fab, [(route, step), ...])` gives
  standard work seconds from the master-data step times (`route.cycle`). A
  batch step counts as one lot's share of a full batch (`cycle / batch_max`).
- **Absorb measure.** For each other tool of the family, absorb counts the
  part of `[now, now + D)` after that tool is free of its lot, any down and
  its committed PM.
- **Commitment.** `start_now` and `force` *commit* the PM. A deferred PM
  keeps its place, and every planned PM is committed exactly once.
- **Dispatch guard.** `state.may_start_lot(tool, now, proc_sec)` is false
  while a committed PM is pending or running. It is also false if the lot
  would end after the latest start of the tool's next PM, so a lot never
  crosses a committed PM and never pushes a PM past its window.
- **Log.** Every in-window decision goes to `state.log` with its reason, queue,
  absorb, family PMs in progress and lanes.

### KPIs (`state.kpis()`)

- **PM shift** (actual − planned start): count, mean and max for deferral and
  for advance.
- **Forced:** count of forced PMs, and `forced_over_cap`.
- **PM-hours in high-queue periods:** at the planned times
  (`pm_h_high_queue_planned`) and at the actual times
  (`pm_h_high_queue_actual`). A high-queue period is a tick where the family
  queue exceeds what all but one of its tools can do during its shortest PM.
  `set_queue` samples this once per family per tick.
- **Count check:** `pm_committed + pm_pending == pm_planned`.

For the before/after report, run the same seeds twice:

- **before:** the rigid plan (PM at its planned start). Its PM-hours in
  high-queue periods equal `pm_h_high_queue_planned`.
- **after:** `pm_decision`.

The unit harness in the tests is not a simulation: it uses random lots, and
its queue is light or heavy by day. On FE_92, BE_110 and Diffusion_FE_120 over
21 days (98 PMs) it gives:

- **30 % heavy days:**
  - 64 PMs advanced: mean 17.7 h, max 24 h;
  - 34 deferred: mean 13.7 h, max 24 h;
  - 13 forced, 5 of them over the cap;
  - PM-hours in high-queue periods: 312 → 68.
- **95 % heavy days:** every PM is held to its latest start and forced; the
  high-queue PM-hours do not change.

## Integration with simulate.py (separate step)

`simulate.py` is not changed here. The planning-r1 study runs on the published
calendar and must stay comparable. Switch only after that study is finished,
as its own PR:

1. **One plan, many consumers.** Build `plan = build_pm_plan(fab, H_plan, shift_sec=shift)`
   once per run, with `H_plan` = the planning window (`release_until`). Pass
   `plan.per_tool()` as `pm=` to `run_policy` instead of `pm_windows(...)`.
   `run_policy` already takes per-tool windows. Give the planner the same
   windows (`with_pm_plan`), so planner and simulator agree.
2. **Call sites to switch, behind one flag** (`pm_mode="dataset" | "staggered"`,
   default `dataset` until the baselines are re-run):
   - `qtime_study.py` (≈ lines 77–116)
   - `scenarios.py:396`
   - `invariant_sweep.py:37–72`
   - `stress.py:233, 252`
   - `benchmark.py:230, 272, 327, 360, 818`
   - tests that pin `pm_windows`: `test_smt_fab.py`, `test_smt_invariants.py`
3. **Dispatch.** The "never start a lot into a PM" check must read the tool's
   own next window, not the family's (same change as in the planner).
4. **The `pm` scenario.** `pm_shift_to_open` shifts the published calendar so
   that a family-wide PM opens at a chosen time. With the staggered plan, the
   same shift opens one tool's PM (two for flagged families), not the whole
   family. That changes the scenario's meaning. Keep a dataset-calendar
   variant for the old scenario, or define the new one explicitly.
5. **Short horizons.** The study horizon is 2 days. On the dataset calendar
   no PM falls in that window at shift 0. On a plan built for the 56-day
   window, 53 staggered PMs do. Use the planning-window plan, clipped by the
   simulator, rather than rebuilding the plan with `H = 2 days`, and state this
   in the results.
6. **Flexible PM at the scheduling tick** (owned by the scheduling-tick work
   on planning-r1; not wired here):
   - **Setup:** build `state = PmState.build(fab, plan)` once per run.
     `simulate.py` then stops pre-blocking PM windows. A PM exists only once
     it is committed.
   - **Each 300 s tick, in this order:**
     1. `state.set_tool(t, busy_until=..., down_until=...)` for the PM
        families' tools;
     2. `state.set_queue(fam, queue_work_sec(fab, eligible_queue), now)`;
     3. `pm_decision(t, now, state)` for each tool. For `start_now`/`force`,
        put the tool into PM over `[start_sec, start_sec + D)`.
   - **Dispatch:** before starting a lot or batch on tool `t`, require
     `state.may_start_lot(t, now, proc_sec)`.
   - **Planner:** it can keep using the planned windows (`with_pm_plan`),
     which are within ±24 h of the actual ones.
   - **Report:** `state.kpis()` next to the rigid-plan run (step 7).
7. **Report separately.** The switch changes every policy's baseline: litho
   capacity no longer drops to zero for a few hours each week, and the
   furnaces never lose a whole family. So:
   - first re-run all policies on both calendars with the same seeds;
   - show the "dataset → staggered" change per policy as its own table;
   - only then compare policies on the staggered calendar.
   Do not mix the before/after of this switch into any policy comparison.

## Tests

`tests/test_pm_plan.py` covers:

- the stagger formula on a toy family, with exact windows;
- single-tool families unchanged;
- the overfull flag and the minimum overlap;
- the bound "nominal start > published − I";
- "before" equal to `simulate.pm_windows`;
- count, occurrences and durations preserved;
- no tool overlapping itself, and the family staying within its lanes;
- furnaces and small litho families at one tool at a time, and FE_92 WK
  flagged;
- determinism and `per_tool` shape;
- the planning hook: the explicit family calendar gives the default result, a
  toy staggered PM lets the other scanner run, and staggered capacity on
  BE_110 and FE_92 has the same total, a higher minimum and fewer overload
  days.

The flexible-PM tests in the same file cover:

- the ±24 h window, its cap by the tool's next and previous PM (WK and MN
  back-to-back on one tool), and every dataset-plan window holding its planned
  start;
- opportunistic early start when idle with no queue, and nothing logged
  before the window;
- defer under a heavy queue, and start once the other tools absorb it;
- force at the latest start, never on a running tool (forced after the lot)
  and the dispatch guard while committed;
- the guard refusing a lot that crosses the latest start;
- the lane cap (second tool deferred `concurrency_cap(1/1)` until the first
  PM ends);
- `queue_work_sec` with a batch share;
- a 21-day tick replay at 30 % and 95 % heavy days checking that every PM is
  committed once, in order, with its own duration, inside its window and with
  no overlap; the KPIs match the log.
