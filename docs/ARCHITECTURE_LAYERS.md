# Architecture layers: planning, priority, scheduling, dispatching

This page sets out how ResiliMES decides which lot runs where and when. It has
three time layers and one shared artefact, the **baseline priority**. Each
layer runs at its own cadence, reads what the slower layer produced, and adds
what only it can see:

1. **Long-term planning** (daily). Gives every lot step dues and a baseline
   priority from the order book and fab capacity.
2. **High-frequency scheduling** (about every 5 min of sim time). Combines the
   baseline with the short-term fab state and produces per-tool queues for the
   next few hours.
3. **Dispatching** (real time, event-triggered). Follows the schedule when a
   tool frees or a lot arrives. Every deviation is logged with a reason.

Everything below is derived from the SMT2020 data (process times, transport
rule, tool counts, down and PM calendars, order book). No layer uses a
hand-tuned weight.

```mermaid
flowchart TB
    subgraph data["SMT2020 dataset (read-only)"]
        R[routes: master-data standard times,<br/>sampling, CQT steps]
        T[tools / families,<br/>down + PM calendars]
        O[WIP snapshot +<br/>order.txt releases]
    end

    subgraph L1["1 · Long-term planning  (daily)"]
        BP[backward pass:<br/>step due + latest start per lot step]
        FP[forward pass:<br/>finite litho capacity, PM, forced downs]
        PR[baseline priority:<br/>tier, band, score, rank]
        OV[litho overload flag<br/>per family per day]
        BP --> FP --> PR
        FP --> OV
    end

    subgraph L2["2 · High-frequency scheduling  (every ~5 min)"]
        ST[short-term state: queues, tool up/down/PM,<br/>open Q-time windows, batches, setups, transport]
        SQ[per-tool queues for the next few hours<br/>+ tool holds for Q-time lots]
    end

    subgraph L3["3 · Dispatching  (event-triggered)"]
        EV[tool free / lot arrives /<br/>Q-time deadline / down / PM]
        DS[start the scheduled lot,<br/>or deviate and log the reason]
    end

    R --> BP
    T --> FP
    O --> BP
    PR -->|PlanningOutput| SQ
    OV -->|capacity alerts| SQ
    ST --> SQ
    SQ -->|schedule| DS
    EV --> DS
    DS -->|deviation log + new state| ST
    DS -.->|daily: actual progress| BP
```

## 1. Long-term planning

| | |
|---|---|
| **Cadence** | Once per sim day (and on demand per scenario). Full fab: about 2.5 s including about 3,200 dataset releases, or 0.6 s for WIP only. |
| **Inputs** | Each lot's route, current step, ready time, due and class (sim state or the published snapshot). SMT2020 master-data standard times (`standard_time`: PTIME by PTPER plus setup into the step's recipe) and the sampled-metrology rule (`measured`). Fixed transport (1 min within an STNGRP, 3 min across). Litho tool counts. PM calendars (`pm`, `attach`). Down calendar (MTTF/MTTR). Forced downs. `order.txt` releases. |
| **Outputs** | `PlanningOutput`, described below. |
| **Code today** | `resilimes/smt/planning.py` (`plan_input`, `build_plan`, `plan_scenario`). It replaces the naive `kernel/aps.py` `backward_dues` and `simulate.macro_aps_ms`. |

**Method**

1. **Visit path.** The visit path is the current step plus every later step
   that this lot number is measured at. Skipped sampled metrology is skipped
   here as well, exactly as in the sim.
2. **Backward pass over master-data standard times.** This pass starts from
   the lot due and works backwards over the remaining path. It gives each step
   a *step due* (target, latest finish) and a *latest start* = step due − the
   step's standard time; the step before is due at that latest start − the
   fixed transport. There is no queueing slack and no weight.
   - **Step targets come from master-data standard times; there is no
     actuals weighting yet** (there are no MES actuals). The standard time of
     a step is `planning.standard_time(fab, route, step)`:
     - SMT2020 route PTIME by PTPER: `per_piece` × PIECES (25), `per_lot` as
       published, `per_batch` once per batch (a lot in a batch takes the whole
       batch cycle; it is not divided by the lots in it);
     - plus, on a step with a SETUP, the setup into its recipe: `setup.txt`
       where it has a row (it wins), else the route STIME. This is a full
       change on every SETUP step, an upper bound: a tool that already holds
       the recipe skips it. Which lots share a setup is left to scheduling.
     - Transport (1 min within an STNGRP, 3 min across) is added between
       steps by the passes. Sampled steps are not on the path.
   - **Hook.** `standard_time` is the one place step times come from (also
     `build_plan(step_time=…)`). A future MES-actuals weighting, for example
     an EWMA of observed step times blended with the standard, replaces it.
     That weighting is not implemented.
   - Lead times are not taken from `order.txt` DUE − START and there is no
     flow factor: an earlier version did that (f00f273) and was reverted.
3. **Forward capacity check.** The check is an event-driven forward pass over
   every lot from its ready time:
   - Non-litho steps take their standard time, so capacity there is unlimited.
   - Each `Litho_*` family (the 7 scanner families plus the 2 `Litho_Met`
     registration families) has a finite number of tools.
   - Queue order at each litho family is class tier, then latest start.
   - Processing time is standard time ÷ availability. Availability is
     MTTF/(MTTF+MTTR) from the down calendar (0.9346 for scanners, 0.9965
     for registration).
   - A start that would overlap a PM window waits for the PM to end. This is
     the same no-overlap rule the sim uses.
   - A forced down removes that tool until it returns.
   - Lots that arrive at the same instant are started in priority order.

   Dataset releases up to the latest WIP due are planned as competing litho
   load.
4. **Baseline priority.** Three quantities feed the priority (raw time here
   means the standard time of step 2):
   - `raw_slack` = due − (ready + remaining raw time)
   - `plan_slack` = due − capacity-feasible finish
   - `score` = `plan_slack` / remaining raw time

   The score is dimensionless: it is the slack as a fraction of the work
   still to do.

   | band | rule |
   |---|---|
   | `critical` | `raw_slack < 0`: late even with zero queueing |
   | `behind` | `score < 0`: late once the litho capacity is accounted for |
   | `on_plan` | `0 ≤ score < 1` |
   | `ahead` | `score ≥ 1`: more slack than the remaining work itself |

   The rank sorts on (class tier, band, score, due). VIP comes before hot,
   which comes before normal, as the published HotLotFIRST rule does. Within
   a tier, the most urgent band and the lowest score come first.
5. **Q-time.** Q-time applies only to steps that have a dataset CQT. The plan
   counts each lot's CQT windows on the path, including windows the lot is
   already inside, which are inherited. It also flags the windows the plan
   itself breaks.
6. **Litho overload.** Each litho family gets one row per day with three
   figures:
   - *capacity*: tool up-hours, outside PM and forced downs, × availability
   - *demand*: standard litho hours whose latest start falls that day (backlog
     counts on day 0)
   - *planned*: hours the forward pass starts that day

   `overload` means demand > capacity on that day. `cum_overload` means
   cumulative demand > cumulative capacity up to that day.

**Releases in the simulator** (flag, default off). `with_releases(fab, until=…)`
appends the `order.txt` lots released before `until` after the WIP, at step 0,
with the dataset product, class, priority and due (release + the order row's DUE − START, the dataset due; not a step target); raw material
is always available. The simulator enqueues each one at its release time
(`Fab.lot_release`), cycle time and X-factor run from release, and the
invariant checker flags any start before release. The study switches it on
with `RESILIMES_STUDY_RELEASES=1` (horizon `RESILIMES_STUDY_HORIZON_H`).

**Out of scope for this layer.** The scheduling layer handles these:
setup sequencing, batching, dedication, rework, and capacity outside litho.

### `PlanningOutput` (what the scheduling layer consumes)

```python
plan = plan_scenario(
    load_fab(), "published"
)  # or build_plan(fab, plan_input(fab, now=..., lot_step=..., ...))
plan.lot("Init_Lot_1_8").band  # 'on_plan'
plan.priority_key("Init_Lot_1_8")  # (rank,) – sort key, lower first
plan.step_due("Init_Lot_1_8", route_step)  # step due (s) for a visited step
plan.band_counts()  # WIP lots per band
plan.overloads()  # LithoDay rows with overload=True
plan.summary()
plan.to_dict(limit=20)  # JSON-ready
```

`LotPlan` carries the following per lot:

| Group | Fields |
|---|---|
| Identity | `lot_id`, `route_id`, `order_class`, `tier`, `released` |
| Times | `ready_sec`, `due_sec` |
| Remaining work | `remaining_raw_sec` |
| Finishes | `raw_finish_sec`, `plan_finish_sec` |
| Slack | `raw_slack_sec`, `plan_slack_sec`, `litho_wait_sec` |
| Priority | `score`, `band`, `rank` |
| Q-time | `qtime_windows`, `qtime_at_risk` |

It also carries these per-step tuples, aligned on `steps`: `step_due`,
`latest_start`, `plan_start`, `plan_end`.

## 2. Baseline priority (the shared artefact)

The priority is not a separate process. It is the planning output that the
two faster layers read:

- **Scheduling** uses `rank` as the default queue order. It also uses `band`
  to decide which lots may claim scarce tools such as Q-time holds and
  batch-forming waits.
- **Dispatching** uses `rank` as the tie-break once the hard constraints are
  met: Q-time urgency, a ready batch, setup, eligibility. In PR #22 the
  ResiliMES due risk is `wait here / (step_due − now − this step's process)`,
  with `step_due` of the current step from the plan.

A lot moves to another band only when the plan reruns, so the band is
stable. In PR #22 the plan runs once at t=0 (see "Integration plan"). The scheduling layer works out short-term urgency from live state.

## 3. High-frequency scheduling

| | |
|---|---|
| **Cadence** | Every `REPLAN_SEC` = 300 s of sim time (the qtime-r2 tick) |
| **Inputs** | `PlanningOutput`. Live queues per family. Tool state: up, down, PM, setup recipe. Open Q-time windows and their deadlines. Batch candidates. Inbound lots with arrival times. Live wait estimates per family. |
| **Outputs** | An ordered queue per tool for the next few hours, holds for Q-time lots, batch-forming decisions, and stall counts. |
| **Code today** | `simulate._Sim.tick` (qtime-r2, PR #21) refreshes the live wait estimates (`refresh_estimates`), sets the Q-time hold plan (`plan_holds`), counts stalls, and snapshots queue order. With a plan (PR #22) it also runs `build_schedule`: each family's queue ordered by `(urgency_band, plan rank)` and laid onto the tools by earliest free time up to the next tick, into `sched[tool]` (1.8–2.0 ms p95). |
| **Target** | Project each tool's queue over the next 2–4 h (batching, setup sequences, PM) and write a `Schedule` with tool → [lot, planned start, reason]. Today's schedule covers one tick only. |

## 4. Dispatching

| | |
|---|---|
| **Cadence** | Event-triggered: a tool frees, a lot arrives, a Q-time deadline falls, a down or PM starts or ends |
| **Inputs** | The latest schedule and the live state at the event |
| **Outputs** | A lot start (tool, lot, time). When the started lot is not the scheduled head, a deviation record with a reason. |
| **Code today** | `simulate._Sim` dispatch with `rank`/`cheap`/`plain_rank` (policies `resilimes`, `edd`, `cr`, `fifo`, `smt_rule`). Q-time-urgent override, shortlist, reservation (qtime-r2). With a plan (PR #22): `_Sim.deviation` compares every start with `sched[tool]`'s head and logs `("deviation", t, tool, scheduled, started, reason)` with one of the nine reasons; the run reports counts (`deviations`, `sched_follow`, `sched_stale_detail`). Dispatch does not prefer the head yet: it is measured, not followed. Lot and tool states and hold reasons are in `resilimes/smt/fsm.py` (PR #20). |
| **Target** | Dispatch takes the schedule head unless a hard rule overrides it. Each override logs `(time, tool, scheduled_lot, started_lot, reason)`, where the reason is one of `qtime_urgent`, `batch_ready`, `setup`, `not_arrived`, `ineligible`, `tool_down`, `pm`, `hold` or `schedule_stale`. |

## Current versus target code map

| Layer | Today | Target |
|---|---|---|
| Planning | `smt/planning.py` (new). `kernel/aps.py` and `simulate.macro_aps_ms` are naive and superseded. | `planning.py` called once per sim day from the sim, using live lot state |
| Priority | `kernel/score.py` `class_tier` and `tiered_key`. With a plan: step-due risk and plan band/rank tie-break (PR #22). | Done in the simplified form |
| Scheduling | `_Sim.tick` (300 s): wait estimates, Q-time hold plan, stall counter; with a plan, `build_schedule` (one tick ahead) | Per-tool queue for the next few hours |
| Dispatching | `_Sim` rank keys, Q-time override, reservation; with a plan, a reasoned deviation log | Follow the schedule head unless a hard rule overrides it |

**Releases.** The sim can release `order.txt` lots (`planning.with_releases`,
the same `dataset_releases` parser; flag, default off). With the flag off only
the 2,156 WIP lots flow, while `plan_scenario` still plans the releases up to
the latest WIP due, so its litho load is higher than the sim's. The study's
`book_plan` plans exactly the lots the sim runs.

## Integration plan (after PR #21 lands)

**Simplified version: done in PR #22 (branch `planning-r1`).** Differences from
the plan below, and why:

- The plan is built once at t=0 from the lots the sim runs: the WIP, plus the
  `order.txt` releases inside the horizon when the releases flag is on.
- No daily replan. Step dues depend only on the route, its master-data standard
  times and the due date (backward pass, no queueing), so a replan gives the
  same step dues and could move only
  band and rank. It is not worth the cost while dues do not depend on state.
- Step 4's reasons come from a fixed check order on the live state at the start
  (see `_Sim.deviation`), not from the branch that chose; anything else is
  `schedule_stale`, split for diagnosis.
- The stress run (`RESILIMES_STRESS_PLAN=1`) uses the same t=0 plan, which does
  not know about the outage.
- Results and regressions: `docs/QTIME_R2.md`, "Step-due risk".
- 7 d study (closed and with releases), balance KPIs and the root cause of the
  plan arm's regression against main: `docs/PLANNING_R1_STUDY.md`.

The original plan:

1. Rebase onto `main` once #21 is merged. `planning.py` touches no existing
   file, so no conflict is expected.
2. In `run_policy`, add `plan: PlanningOutput | None = None`. This is an
   opt-in parameter; the default changes nothing. Call `plan_scenario` once
   before the run (2.5 s).
3. Scheduling: in `tick`, when `plan` is set, order each family's live queue
   by `(urgency_band, plan.rank)` and store the head *k* per tool as
   `scheduled[tool]`. *k* is the tool's lots in the next `REPLAN_SEC`.
4. Dispatching: when a tool starts a lot that is not `scheduled[tool][0]`,
   append `("deviation", t, tool, scheduled, started, reason)` to `events`.
   The reason comes from the branch that made the choice: Q-time override,
   batch, setup, reservation, or a scheduled lot that has not arrived.
5. Report the following per scenario: deviation counts by reason, plan-band
   versus actual-lateness confusion, and on-time rate for `resilimes`+plan
   versus `resilimes`.
6. Add tests for three things: the sim with `plan=None` is bit-identical to
   today; every deviation has a reason; and a plan-ordered queue starts the
   rank-1 lot first on a toy fab.

**Full version (after Monday)**

- Replan daily inside the sim. Feed `plan_input(fab, now=t, lot_step=…,
  lot_ready=…, finished=…, down_until=…)` from live state and swap the plan at
  the day boundary.
- Release `order.txt` lots in the sim (`dataset_releases`).
- Scheduling projects a 2–4 h per-tool queue that covers batching, setup
  sequences and PM. The UI shows schedule versus actual.
- Feed capacity alerts back: an overload day pulls PM-flexible windows
  (`pm_avoid`) or changes litho tool dedication.
