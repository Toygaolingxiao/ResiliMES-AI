# Q-time r2: dynamic risk weight, scheduling tick, reservation, full-queue batching, deadline rework

Branch `qtime-r2`, from `main` 641d988 (PR #21). Every number below was measured on this box (8 cores)
with `resilimes/smt/qtime_study.py` and `resilimes/smt/stress.py`. No weights, due dates or seeds were
changed, and the dynamic weight has no tuned constant. Q-time windows exist only on the 264 dataset
CQT/STEP_CQT route steps (`route.cqt_limit > 0`); no window was added anywhere else.

Three versions are compared throughout: **main**, **fixed** (PR #21 at 4719e1f: graded Q-time urgency
ranked ahead of due slack) and **dynamic** (wait/slack risk, computed live). A fourth version,
**dynamic(step dues)** (branch `planning-r1`, PR #22), replaces the ρ-based due risk with a risk against
per-step due dates from the long-term plan; see "Step-due risk (planning layer)". Where the text says
"dynamic" without qualification it means dynamic(ratio), the ρ version.

## Summary

- **Q-time:** the dynamic version is the best of the three for ResiliMES on `published`. The true rate
  is 94.0 / 94.9 / **97.8 %** (main / fixed / dynamic), with 3131 windows met per run. Re-cleans fall
  from 40 / 62 to **9**. On the X-factor books the rate is 93.7 % (fixed 94.6 %, main 92.6 %).
- **On-time:** recovered from the fixed version. On `published` it is 57.1 / 55.0 / **57.1 %** (EDD
  57.5 %). On `xfactor_eta600` it is 99.1 / 63.9 / **84.4 %**, still 15 points under main. On held-out
  X-factor it is 100 / 77.9 / **93.6 %**. On `tight_vip` the dynamic version is the best of all
  versions and policies: **27.6 %** (EDD 12.4 %).
- **Throughput regressed hard.** On `published`, ResiliMES completed routes per run were
  135.8 / 122.0 / **80.2** (EDD 159.6). The cause is the observed-flow term of the due-date risk: it
  behaves like critical ratio and pulls work to the front of the routes (see "Regressions"). The total
  number of steps done is the same.
- **Scheduling tick:** 0.87 ms at p50 and 1.03 ms at p95 per tick, 0.5 s per 48 h run (about 10 % of
  wall time). With the `record` snapshot for the UI it is 3.4 / 4.1 ms and 2.0 s per run. The tick
  never starts a lot. The four baselines give **identical** results in the fixed and dynamic
  versions, so dispatch stayed event-triggered. Stalls counted: 0–0.8 per 576 ticks, almost all
  furnaces waiting to fill a batch.
- **Dispatch latency:** ResiliMES busy-decision p95 is 0.145 / 0.178 / **0.298 ms**; the p95 over all
  decisions is 0.0065 / 0.0073 / 0.0087 ms.
- **Stress:** see "Stress".
- **Step dues (PR #22):** with the plan's step due dates in place of ρ, ResiliMES on `published` keeps
  57.1 % on-time and completes **118.8** routes per run instead of 80.2 (main 135.8). The Q-time true
  rate is 95.1 % (dynamic(ratio) 97.8 %, fixed 94.9 %, main 94.0 %). On `xfactor_eta600` on-time is
  81.4 % (ratio 84.4 %). Dispatch busy p95 is 0.34 ms. ResiliMES starts the head of the 300 s schedule
  on 11.5 % of starts; every other start is logged as a deviation with a reason.

## Layers

The weight is computed by four separate layers. Only the dispatching layer starts lots.

| Layer | Cadence | What it does here | Code |
|---|---|---|---|
| **Planning** | per run (offline) | Release plan, due dates, route data, Q-time windows from the dataset (CQT/STEP_CQT only), PM calendar, scanner dedication. Not changed by this work. | `fab.py`, run setup |
| **Priority** | at each decision, from the latest estimates | ResiliMES dynamic risk per lot: expected wait / remaining slack, max over the due date and an open Q-time window. Class tiers (VIP/hot/normal) stay above it. With a plan (`run_policy(plan=...)`) the due risk is taken against the plan's step due date, and plan band/rank break ties. | `_Sim.risk`, `plain_rank`, `cheap` |
| **Scheduling** | **every 300 s of sim time** (`REPLAN_SEC`), all policies | (a) refresh the live wait estimate per family and the observed queue/process ratio ρ; (b) ResiliMES fix 3: re-evaluate tool holds, i.e. release holds no longer needed (`replan`) and set the hold plan (which inbound windowed lots warrant a held tool), so no hold decision is older than 5 min; (c) stall detector, **counter only**: an idle, up tool with an eligible ready lot and no pending wake; (d) `replan` snapshot (with `record`): per-family queue order and the next planned lot per tool, for the UI 已排程 overlay; (e) with a plan: per family, order the queue by (urgency band, plan rank) and lay it onto the tools by earliest free time over the next tick, giving `scheduled[tool]`. It never starts a lot. | `_Sim.tick`, `refresh_estimates`, `plan_holds`, `snapshot`, `build_schedule` |
| **Dispatching** | **event-triggered** (lot arrives, tool ends a piece, down or PM ends, wake, Q deadline) | Chooses and starts lots on a free tool with the latest schedule and live state: ranks by the priority layer; with a plan, logs a reasoned deviation whenever the start is not the head of `scheduled[tool]`; makes a hold only for a lot in the current hold plan, after every live tool check (busy until after the latest start, pin, PM overlap, no other tool free, ETA ≤ 15 min, one per family, cool-down). | `try_start`, `choose`, `maybe_reserve` |

The 300 s schedule (PR #22, only with a plan) is a sequence per tool, not a commitment: dispatch
still decides from live state, and the schedule is used to measure adherence and log why dispatch left
it. Without a plan (`plan=None`) nothing in this section changes, bit for bit.

## Dynamic weight (r2.1, ResiliMES fix 2)

The fixed version ranked Q-time urgency before due slack with no exchange rate between them, which
over-served Q-time (see the fixed column). Now each lot gets one number per constraint:

- **Due date:** `risk_due = (W_here + ρ · P_after) / slack_due`
  - `slack_due` = due − now − remaining raw process.
  - `W_here` = live expected wait at the lot's current family.
  - `P_after` = raw process still due after this step.
  - `ρ` = observed fab-wide queue time / process time, accumulated over every start so far.
- **Q-time** (only a lot inside an open window): `risk_q = (W_here + Σ W_f) / slack_q`
  - `slack_q` = deadline − now − process and transport still due before the target.
  - The sum covers the measured steps up to and including the target.
- **Final:** `risk = max(risk_due, risk_q)`.
  - Slack ≤ 0 gives infinite risk; ties then go to the least slack.
- **Family wait:** `W_f` = (queued work at the family + residual time of its busy up tools) / tools up.
  - A batch step is counted at its time over the batch size.
  - With no tool up: time until the first one returns, plus work over all tools.

**Why the downstream term matters.** A common per-family wait W alone would reduce to min-slack
ordering (W/slack orders by slack). The weight between Q-time and due date therefore comes from what
each constraint still has to pass: the few steps up to the Q-time target versus ρ times the rest of
the route.

**Where it is used.**
- **Fix 1** admits every open-window lot, highest risk first.
- **Ranking (fix 2):** class tier first. Then lots with risk ≥ 1, which are expected to miss, highest
  risk first, then setup. Lots with risk < 1 go by setup avoidance first, then highest risk.
  - The break-even risk of 1 is a natural threshold, not a tuned constant.
  - The shortlist key is (urgency band, tier, −risk, least slack).
- **Fix 3** holds a tool only for lots the tick put in the hold plan:
  - the lot arrives before its latest start and within 15 min of the next tick;
  - the live wait at its family ≥ its Q slack on arrival.
- **Not changed:**
  - fixes 4–6;
  - the class tiers;
  - the PR #18 urgency band (15 min margin).

## Step-due risk (planning layer, PR #22)

**What changed** (only when `run_policy(..., plan=PlanningOutput)` is given; `plan=None` is bit-identical
to dynamic(ratio): all 225 study runs re-run with `plan=None` match on every non-timing field):

- **Due risk:** `risk_due = W_here / (step_due − now − P_here)`.
  - `step_due` = the lot's due date for its current step, from the plan's backward pass.
  - `W_here` = live expected wait at the current family; `P_here` = this step's process time.
  - Slack ≤ 0 gives infinite risk, as before.
  - A lot-step that is not in the plan (56 lot-steps per run) falls back to the old slack and is counted
    (`plan_due_fallbacks`).
- **Q-time risk:** unchanged.
- **Priority:** class tier, then `max(risk_due, risk_q)` as before, then plan band and rank as the
  tie-break. No fab-wide ratio and no tuned constant: the ρ term is gone.
- **Plan:** computed once at t=0 (`book_plan`: `build_plan` on the book's WIP, releases off, because the
  simulator does not release `order.txt` lots). The plan's due for the hot lot is the same 43200 s the
  simulator applies; every other lot's plan due equals its simulator due (checked).
- **No daily replan.** Step dues come from the route and the lot's due date only (backward pass, no
  queueing), so a replan would give the same step dues; it could only move band and rank. Not worth the
  cost while dues do not depend on state.
- **300 s schedule:** each tick orders every family's queue by (urgency band, plan rank) and lays it onto
  the family's tools by earliest free time up to the next tick, giving `scheduled[tool]`. Build cost:
  1.8–2.0 ms p95, about 0.9 s per 48 h run.
- **Deviations:** whenever a start is not the head of `scheduled[tool]`, dispatch logs one reason, checked
  in this order: `tool_down` (list dropped by a down) / `hold` / `qtime_urgent` / `hold` (head held
  elsewhere) / `not_arrived` / `ineligible` / `tool_down` / `pm` / `batch_ready` / `setup`, otherwise
  `schedule_stale`. `schedule_stale` is split for diagnosis by where the started lot was:
  `new_since_tick`, `beyond_horizon` (queued at the tick, not booked before the next tick),
  `other_tool`, `no_head`, `later_in_list`.
- **Baselines:** EDD, FIFO, CR and SMT rule get the schedule and the deviation log, but their dispatch is
  unchanged; their results are identical with and without the plan (study and stress).

### Table P1. ResiliMES vs EDD: main / fixed / dynamic(ratio) / dynamic(step dues) (seed mean; on-time pooled)

| Book | Policy | On-time % | Completed | Q true rate % |
|---|---|---|---|---|
| published | resilimes | 57.1 / 55.0 / 57.1 / **57.1** | 135.8 / 122.0 / 80.2 / **118.8** | 94.0 / 94.9 / 97.8 / **95.1** |
| published | edd | 57.5 / 57.5 / 57.5 / **57.5** | 160.0 / 159.6 / 159.6 / **159.6** | 86.0 / 83.7 / 83.7 / **83.7** |
| xfactor_eta600 | resilimes | 99.1 / 63.9 / 84.4 / **81.4** | 138.0 / 124.6 / 113.0 / **113.8** | 92.6 / 94.6 / 93.7 / **94.8** |
| xfactor_eta600 | edd | 99.5 / 99.5 / 99.5 / **99.5** | 165.8 / 166.6 / 166.6 / **166.6** | 84.3 / 82.4 / 82.4 / **82.4** |
| tight_vip | resilimes | 25.7 / 23.8 / 27.6 / **24.8** | 26.6 / 27.0 / 27.0 / **27.0** | 95.4 / 96.1 / 96.0 / **96.1** |
| tight_vip | edd | 12.4 / 12.4 / 12.4 / **12.4** | 38.2 / 41.8 / 41.8 / **41.8** | 65.1 / 71.6 / 71.6 / **71.6** |
| pm_enforced | resilimes | 57.1 / 55.0 / 56.8 / **56.8** | 139.6 / 124.0 / 76.2 / **124.8** | 93.4 / 93.5 / 96.9 / **93.4** |
| pm_enforced | edd | 57.9 / 57.5 / 57.5 / **57.5** | 156.4 / 156.8 / 156.8 / **156.8** | 84.9 / 82.3 / 82.3 / **82.3** |
| litho | resilimes | 57.1 / 55.4 / 56.8 / **56.8** | 138.4 / 121.2 / 80.8 / **118.6** | 94.0 / 95.0 / 97.7 / **95.3** |
| litho | edd | 57.5 / 57.5 / 57.5 / **57.5** | 159.6 / 159.2 / 159.2 / **159.2** | 85.9 / 83.6 / 83.6 / **83.6** |
| hot | resilimes | 56.1 / 54.4 / 55.8 / **55.8** | 138.4 / 122.2 / 80.4 / **118.6** | 93.9 / 95.1 / 97.8 / **95.1** |
| hot | edd | 57.5 / 57.5 / 57.5 / **57.5** | 160.0 / 159.6 / 159.6 / **159.6** | 86.0 / 83.7 / 83.7 / **83.7** |
| heldout_published | resilimes | 57.1 / 55.4 / 57.1 / **57.1** | 144.4 / 130.8 / 82.2 / **129.2** | 94.0 / 95.0 / 97.6 / **95.2** |
| heldout_published | edd | 57.1 / 57.5 / 57.5 / **57.5** | 165.2 / 164.6 / 164.6 / **164.6** | 85.6 / 83.6 / 83.6 / **83.6** |
| heldout_xfactor | resilimes | 100.0 / 77.9 / 93.6 / **92.4** | 140.8 / 126.8 / 117.0 / **112.4** | 92.5 / 95.1 / 93.8 / **95.2** |
| heldout_xfactor | edd | 100.0 / 100.0 / 100.0 / **100.0** | 167.6 / 166.2 / 166.2 / **166.2** | 83.8 / 81.9 / 81.9 / **81.9** |
| litho_family_2h | resilimes | 57.1 / 55.0 / 56.8 / **56.8** | 139.2 / 122.6 / 81.2 / **117.6** | 93.7 / 94.6 / 97.8 / **94.9** |
| litho_family_2h | edd | 57.1 / 57.5 / 57.5 / **57.5** | 159.4 / 159.2 / 159.2 / **159.2** | 85.7 / 83.2 / 83.2 / **83.2** |

### Table P2. Schedule adherence and deviations by reason (dynamic(step dues), seed mean per run)

| Book | Policy | Starts | Follow head | qtime_urgent | batch_ready | setup | not_arrived | ineligible | tool_down | pm | hold | schedule_stale | stale: new since tick / beyond horizon / other tool / no head / later in list |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| published | resilimes | 39459 | 4518 (11.5 %) | 16 | 139 | 922 | 227 | 0 | 94 | 0 | 10 | 33533 | 19937 / 9722 / 3419 / 454 / 0 |
| published | edd | 35887 | 3220 (9.0 %) | 0 | 157 | 379 | 169 | 0 | 84 | 0 | 60 | 31817 | 19486 / 9319 / 2675 / 337 / 0 |
| xfactor_eta600 | resilimes | 39069 | 4688 (12.0 %) | 16 | 113 | 932 | 219 | 0 | 95 | 0 | 14 | 32993 | 18799 / 10061 / 3710 / 423 / 0 |
| xfactor_eta600 | edd | 35527 | 2748 (7.7 %) | 0 | 140 | 385 | 164 | 0 | 88 | 0 | 61 | 31942 | 18510 / 10379 / 2757 / 296 / 0 |
| tight_vip | resilimes | 19867 | 3135 (15.8 %) | 7 | 101 | 519 | 121 | 0 | 44 | 0 | 13 | 15927 | 9090 / 4351 / 2192 / 294 / 0 |
| tight_vip | edd | 19512 | 1983 (10.2 %) | 0 | 106 | 197 | 90 | 0 | 48 | 0 | 55 | 17033 | 7431 / 6647 / 2523 / 432 / 0 |
| pm_enforced | resilimes | 38693 | 4396 (11.4 %) | 21 | 143 | 900 | 223 | 0 | 214 | 8 | 11 | 32777 | 19330 / 9678 / 3353 / 416 / 0 |
| pm_enforced | edd | 35291 | 3250 (9.2 %) | 0 | 154 | 364 | 168 | 0 | 215 | 4 | 57 | 31079 | 19041 / 9052 / 2671 / 315 / 0 |
| litho | resilimes | 39383 | 4492 (11.4 %) | 18 | 140 | 941 | 235 | 0 | 90 | 0 | 11 | 33457 | 19831 / 9742 / 3436 / 448 / 0 |
| litho | edd | 35882 | 3247 (9.0 %) | 0 | 155 | 388 | 172 | 0 | 81 | 0 | 63 | 31776 | 19468 / 9315 / 2660 / 333 / 0 |
| hot | resilimes | 39356 | 4501 (11.4 %) | 19 | 145 | 894 | 230 | 0 | 88 | 0 | 10 | 33469 | 19919 / 9682 / 3428 / 440 / 0 |
| hot | edd | 35887 | 3231 (9.0 %) | 0 | 155 | 382 | 170 | 0 | 84 | 0 | 61 | 31802 | 19487 / 9313 / 2675 / 328 / 0 |
| heldout_published | resilimes | 39511 | 4554 (11.5 %) | 16 | 140 | 938 | 230 | 0 | 94 | 0 | 12 | 33528 | 19782 / 9894 / 3395 / 456 / 0 |
| heldout_published | edd | 36027 | 3335 (9.3 %) | 0 | 153 | 366 | 188 | 0 | 85 | 0 | 56 | 31844 | 19410 / 9423 / 2686 / 325 / 0 |
| heldout_xfactor | resilimes | 39135 | 4713 (12.0 %) | 14 | 112 | 954 | 244 | 0 | 94 | 0 | 13 | 32993 | 18792 / 10085 / 3690 / 425 / 0 |
| heldout_xfactor | edd | 35698 | 2773 (7.8 %) | 0 | 146 | 405 | 179 | 0 | 89 | 0 | 64 | 32041 | 18500 / 10485 / 2758 / 297 / 0 |
| litho_family_2h | resilimes | 39302 | 4467 (11.4 %) | 17 | 146 | 935 | 244 | 0 | 118 | 0 | 11 | 33363 | 19642 / 9849 / 3420 / 453 / 0 |
| litho_family_2h | edd | 35879 | 3223 (9.0 %) | 0 | 158 | 387 | 169 | 0 | 110 | 0 | 69 | 31763 | 19375 / 9406 / 2672 / 310 / 0 |

### Table P3. Latency (ResiliMES, seed mean): dynamic(ratio) → dynamic(step dues)

| Book | Dispatch p95 ms | Dispatch busy-p95 ms | Tick p95 ms | Schedule build p95 ms | Schedule build total s | Sim s | Plan-due fallbacks (lot-steps) |
|---|---|---|---|---|---|---|---|
| published | 0.0089 → 0.0131 | 0.324 → 0.340 | 4.08 → 7.48 | 1.82 | 0.91 | 6.91 → 10.18 | 56 |
| xfactor_eta600 | 0.0092 → 0.0140 | 0.297 → 0.349 | 4.38 → 8.35 | 2.03 | 0.98 | 6.78 → 10.59 | 56 |
| tight_vip | 0.0092 → 0.0130 | 0.250 → 0.321 | 4.41 → 7.79 | 1.93 | 0.48 | 3.26 → 5.15 | 56 |
| pm_enforced | 0.0088 → 0.0130 | 0.298 → 0.341 | 4.06 → 8.45 | 2.05 | 0.98 | 6.70 → 10.58 | 56 |
| litho | 0.0082 → 0.0128 | 0.314 → 0.349 | 4.04 → 7.55 | 1.83 | 0.90 | 6.51 → 10.10 | 56 |
| hot | 0.0080 → 0.0127 | 0.298 → 0.344 | 3.63 → 7.46 | 1.84 | 0.90 | 6.36 → 10.05 | 56 |
| heldout_published | 0.0083 → 0.0126 | 0.298 → 0.353 | 3.62 → 7.12 | 1.74 | 0.88 | 6.43 → 9.88 | 56 |
| heldout_xfactor | 0.0090 → 0.0130 | 0.293 → 0.324 | 4.32 → 7.47 | 1.83 | 0.92 | 6.65 → 9.84 | 56 |
| litho_family_2h | 0.0086 → 0.0123 | 0.306 → 0.333 | 4.05 → 7.14 | 1.75 | 0.87 | 6.67 → 9.70 | 56 |

Most deviations are `schedule_stale`, and most of those are lots that arrived after the tick or that the
tick did not book (the schedule covers 300 s only). The schedule head is followed on 11.5 % of ResiliMES
starts and 9 % of EDD starts. Among the reasoned deviations, setup dominates for ResiliMES (it still ranks
setup avoidance first below risk 1).

The tick p95 includes the schedule build (and the `record` snapshot). Sim times were measured with 5
workers on a loaded 8-core box; compare them within a table only.

### Table P4. Ablation of fixes 1–3, dynamic(ratio) / dynamic(step dues) (ResiliMES, seeds 1–5)

| Fixes | published on-time % (ratio / step dues) | published completed | published Q rate % | xfactor_eta600 on-time % | xfactor completed | xfactor Q rate % |
|---|---|---|---|---|---|---|
| 1 | 55.4 / 55.4 | 121.6 / 121.6 | 94.9 / 94.9 | 60.7 / 60.7 | 123.6 / 123.6 | 94.5 / 94.5 |
| 2 | 56.8 / 56.8 | 79.6 / 119.0 | 97.5 / 95.0 | 84.6 / 81.8 | 113.4 / 113.0 | 93.5 / 94.7 |
| 3 | 57.1 / 57.1 | 138.2 / 138.2 | 93.7 / 93.7 | 99.8 / 99.8 | 137.0 / 137.0 | 92.4 / 92.4 |
| 1+2 | 56.8 / 56.8 | 79.6 / 119.0 | 97.5 / 95.0 | 84.6 / 81.8 | 113.4 / 113.0 | 93.5 / 94.7 |
| 2+3 | 57.1 / 57.1 | 80.2 / 118.8 | 97.8 / 95.1 | 84.4 / 81.4 | 113.0 / 113.8 | 93.7 / 94.8 |
| 1+3 | 55.4 / 55.4 | 121.6 / 121.6 | 95.0 / 95.0 | 60.7 / 60.7 | 123.8 / 123.8 | 94.6 / 94.6 |
| 1+2+3 (study) | 57.1 / 57.1 | 80.2 / 118.8 | 97.8 / 95.1 | 84.4 / 81.4 | 113.0 / 113.8 | 93.7 / 94.8 |

Variants without fix 2 do not use the due risk, and their scores have no exact ties, so the plan rank
never decides and they are unchanged by the plan.

### Stress with the plan

`RESILIMES_STRESS_PLAN=1`, the same 50 runs as "Stress". The plan does not foresee the outage.

- Hard stalls 0, stranded 0, frozen WIP 0, invariant failures 0, longest late wait 29.7 min, minimum
  fab steps/h in the outage 349. The four baselines are identical to the run without plan.
- ResiliMES: on-time 53.6–58.9 % (mean 56.8, ratio 57.0), completed 96–133 (mean 118.2, ratio 80.6),
  Q-time violations 133–179 per run (mean 160, ratio 72), holds 6–15 per run.
- A first stress run reported 1 stall sample on `cr`. It was an audit artefact, not a stall: the audit
  wraps `simulate.heapq` to sample on event-heap pops, and the schedule's own tool heap went through the
  wrapper, so samples were taken mid-tick. The schedule now binds `heapq` functions directly (test:
  `test_schedule_heap_is_not_the_event_heap`); the rerun above has 0.

## Root cause (why r1 Q-time still leaked)

1. **Shortlist cut:** ResiliMES ranks only 8 or 24 candidates per decision, and the cut is ordered by
   class, late band and due-date slack. A lot deep inside a CQT window but with plenty of due-date slack
   was often cut before the Q-time term (PED) was ever seen.
2. **Urgency curve:** the old PED curve `exp(6(1 - remaining/limit)) - 1` uses the time left to the
   deadline, not to the latest start. A lot that still had 40 min of processing before its target looked
   as safe as one about to start.
3. **No tool kept free:** a scanner or etcher could start a long ordinary lot seconds before an inbound
   windowed lot arrived. Nothing held a tool back.
4. **Batching from the shortlist only:** furnace batches were built from the shortlist only, so a batch
   could leave with empty slots while same-recipe lots waited (ResiliMES is the only capped policy).
5. **No deadline event:** a lot that missed its deadline in the queue waited until it started, and was
   counted only then. Missed lots had no time-based outcome.
6. **Reporting:** the 433 snapshot lots already inside a window at t=0 were not tracked. The UI rate
   showed met / (met + violated) and left recleaned and expired windows out: 93.4 % shown against a true
   2692/3108 = 86.6 %.

## The fixes

Fixes 1–3 are ResiliMES policy logic (`r2_policy=True`, ResiliMES only). Fixes 4–6 and the pin fix are
shared simulator mechanics: they change every baseline, so all five policies were rerun on both sides.
The `mech` arm (branch with `r2_policy=False`) separates the two.

| # | Commit | What changed | Scope |
|---|---|---|---|
| 6 | 823b69a | Window outcome buckets (met / late / held / recleaned / expired, plus unscored live / skipped). The 433 inherited windows are counted apart (opened at t=0). `qtime_kpi.qtime_buckets` adds four buckets and the true rate to the API and benchmark keys. | shared |
| 5 | 45eddab | Timed deadline event at a window's latest start. An un-started lot goes to re-clean (Wet_Etch origin, first miss) or to a 30-min Q-time hold, then requeues. Hold time is counted separately (`qtime_hold_lot_min`). | shared |
| 4 | 6e44f85 | Furnace batch candidates come from the whole same-recipe family queue. The 30-min and 10-min hot/VIP caps and the recipe rule are unchanged. | shared (only ResiliMES has a capped list) |
| 1 | 66c33af, 9058111 | Every open-window lot is admitted to the capped ResiliMES shortlist. r2.1: highest dynamic risk first (was least time left first). | ResiliMES |
| 2 | 64a6e39, 9058111 | PR #21 (fixed order): graded urgency `1 - slack/limit` ranked ahead of setup and due slack. **r2.1: replaced by the dynamic risk** = expected wait / remaining slack, max of the due-date and Q-time constraints (see "Dynamic weight"). | ResiliMES |
| 3 | 320ad4a, 9058111 | Bounded reservation (r2.1: only for lots in the scheduling tick's hold plan, i.e. Q slack on arrival ≤ expected wait; the tick also releases holds no longer needed): at most 1 tool per family for at most 15 min, never on a down tool or one with PM during the hold, no back-to-back chains. Released when used, used elsewhere, expired or cancelled. Every reservation is logged and counted (count and minutes). | ResiliMES |
| + | d6a300b | Scanner pin binds only the later steps of its own layer (see below). | shared |
| + | 78a1255 | Litho stress book and audit; added to `invariant_sweep`. | test |
| + | 9058111 | Scheduling tick every 300 s sim time, all policies (see "Layers"). Never starts a lot. | shared (scheduling layer) |
| + | 05439f1, 7cf3f10 | Tests for the dynamic risk, tick and tick-planned holds; `qtime_study` `ablate` arm and tick/risk metrics. | test, study |
| + | 42d78b7 | `qtime_study.py`: one event replay scores every arm the same way. | study |

### Extra fix found by the stress test (shared, changes every policy)

`dedicate_tool` from an earlier litho layer also bound the **root step of the next layer**, even when
that step is in another family. Such a lot was eligible only while its old scanner was down, so it stayed
stranded forever. Main has this bug in every policy: at the 24 h stress start, seed 1, main ResiliMES
ended with 30 stranded lots. `pin_for()` now returns the pin only for a later step of the same layer
whose family is the pinned tool's family. The dedication invariant was narrowed to match.
`tests/test_smt_dedication.py` covers both directions; the first test fails on main.

## Method

- **Arms (three versions compared in the tables):**
  - `main`: main 641d988, running the same study script from a /tmp copy.
  - `fixed`: PR #21 at 4719e1f, fixed order (graded PED ahead of setup and due slack).
  - `dynamic`: this revision (9058111..), dynamic risk and the scheduling tick.
  - `ablate`: dynamic revision with single fixes and pairs (`r2_fixes`), ResiliMES, `published` and `xfactor_eta600`, seeds 1–5.
- **Policies:** resilimes, edd, fifo, cr, smt_rule. The four baselines do not use the policy fixes; the tick runs
  for all five.
- **Books** (mirroring `benchmark.py`):
  - `published`
  - `xfactor_eta600` (focus tool down 600 min, X-factor due dates)
  - `tight_vip` (24 h)
  - `pm_enforced`
  - `litho` (focus tool down for the litho MTTR)
  - `hot`
  - `heldout_published` and `heldout_xfactor` (seeds 9–13)
  - `litho_family_2h` (stress outage, below)
- **Seeds:** 1–5 except the held-out books. 225 runs per version, plus 60 ablation runs.
- **Scoring:** Q-time buckets and batch fill come from the recorded events with one replay for every arm.
  On the branch the replay matched the simulator's own counters exactly (checked on three runs).
- **Q-time rate:** met / (met + started late + recleaned + open-expired). Live windows (deadline after
  the horizon) and skipped targets are not scored.

## Results: main / fixed / dynamic

Cells read main / fixed / dynamic unless the header says otherwise. On-time is pooled over seeds; other numbers are seed means per run. Tick and stall numbers come from `record` runs (snapshot on).

### Table 1. ResiliMES vs EDD, main → PR #21 fixed order → dynamic (seed mean; on-time pooled)

| Book | ResiliMES on-time % | EDD on-time % | ResiliMES completed | EDD completed | ResiliMES X-factor |
|---|---|---|---|---|---|
| published | 57.1 / 55.0 / **57.1** | 57.5 / 57.5 / 57.5 | 135.8 / 122.0 / **80.2** | 160.0 / 159.6 / 159.6 | 2.58 / 2.56 / 3.16 |
| xfactor_eta600 | 99.1 / 63.9 / **84.4** | 99.5 / 99.5 / 99.5 | 138.0 / 124.6 / **113.0** | 165.8 / 166.6 / 166.6 | 1.74 / 2.15 / 2.26 |
| tight_vip | 25.7 / 23.8 / **27.6** | 12.4 / 12.4 / 12.4 | 26.6 / 27.0 / **27.0** | 38.2 / 41.8 / 41.8 | 1.75 / 1.72 / 1.72 |
| pm_enforced | 57.1 / 55.0 / **56.8** | 57.9 / 57.5 / 57.5 | 139.6 / 124.0 / **76.2** | 156.4 / 156.8 / 156.8 | 2.65 / 2.53 / 3.04 |
| litho | 57.1 / 55.4 / **56.8** | 57.5 / 57.5 / 57.5 | 138.4 / 121.2 / **80.8** | 159.6 / 159.2 / 159.2 | 2.59 / 2.57 / 3.14 |
| hot | 56.1 / 54.4 / **55.8** | 57.5 / 57.5 / 57.5 | 138.4 / 122.2 / **80.4** | 160.0 / 159.6 / 159.6 | 2.51 / 2.57 / 3.12 |
| heldout_published | 57.1 / 55.4 / **57.1** | 57.1 / 57.5 / 57.5 | 144.4 / 130.8 / **82.2** | 165.2 / 164.6 / 164.6 | 2.37 / 2.39 / 3.13 |
| heldout_xfactor | 100.0 / 77.9 / **93.6** | 100.0 / 100.0 / 100.0 | 140.8 / 126.8 / **117.0** | 167.6 / 166.2 / 166.2 | 1.71 / 2.03 / 2.19 |
| litho_family_2h | 57.1 / 55.0 / **56.8** | 57.1 / 57.5 / 57.5 | 139.2 / 122.6 / **81.2** | 159.4 / 159.2 / 159.2 | 2.57 / 2.56 / 3.14 |

### Table 2. Q-time buckets (dispatcher windows, seed mean per run). True rate = met / (met + started late + recleaned + open-expired)

| Book | Policy | Version | True rate % | Met | Started late (late+held) | Recleaned | Open-expired | Inherited missed / 433 |
|---|---|---|---|---|---|---|---|---|
| published | resilimes | main | 94.0 | 2922 | 69 (69+0) | 40 | 79 | 203 |
| published | resilimes | fixed | 94.9 | 3031 | 99 (0+99) | 62 | 1 | 140 |
| published | resilimes | dynamic | 97.8 | 3131 | 63 (0+63) | 9 | 0 | 141 |
| published | edd | main | 86.0 | 2598 | 207 (207+0) | 53 | 161 | 184 |
| published | edd | fixed | 83.7 | 2608 | 411 (0+411) | 98 | 0 | 185 |
| published | edd | dynamic | 83.7 | 2608 | 411 (0+411) | 98 | 0 | 185 |
| xfactor_eta600 | resilimes | main | 92.6 | 2898 | 86 (86+0) | 44 | 101 | 195 |
| xfactor_eta600 | resilimes | fixed | 94.6 | 2991 | 110 (0+110) | 60 | 1 | 136 |
| xfactor_eta600 | resilimes | dynamic | 93.7 | 2946 | 129 (0+129) | 69 | 1 | 140 |
| xfactor_eta600 | edd | main | 84.3 | 2528 | 240 (240+0) | 55 | 175 | 190 |
| xfactor_eta600 | edd | fixed | 82.4 | 2540 | 445 (0+445) | 97 | 1 | 186 |
| xfactor_eta600 | edd | dynamic | 82.4 | 2540 | 445 (0+445) | 97 | 1 | 186 |
| tight_vip | resilimes | main | 95.4 | 1396 | 35 (35+0) | 5 | 28 | 211 |
| tight_vip | resilimes | fixed | 96.1 | 1476 | 51 (0+51) | 7 | 1 | 165 |
| tight_vip | resilimes | dynamic | 96.0 | 1455 | 52 (0+52) | 8 | 1 | 143 |
| tight_vip | edd | main | 65.1 | 943 | 401 (401+0) | 16 | 88 | 156 |
| tight_vip | edd | fixed | 71.6 | 1081 | 389 (0+389) | 40 | 0 | 153 |
| tight_vip | edd | dynamic | 71.6 | 1081 | 389 (0+389) | 40 | 0 | 153 |
| pm_enforced | resilimes | main | 93.4 | 2776 | 81 (81+0) | 36 | 78 | 209 |
| pm_enforced | resilimes | fixed | 93.5 | 2904 | 134 (0+134) | 66 | 1 | 140 |
| pm_enforced | resilimes | dynamic | 96.9 | 2988 | 87 (0+87) | 9 | 0 | 142 |
| pm_enforced | edd | main | 84.9 | 2447 | 213 (213+0) | 61 | 160 | 193 |
| pm_enforced | edd | fixed | 82.3 | 2473 | 422 (0+422) | 109 | 1 | 194 |
| pm_enforced | edd | dynamic | 82.3 | 2473 | 422 (0+422) | 109 | 1 | 194 |
| litho | resilimes | main | 94.0 | 2918 | 70 (70+0) | 37 | 80 | 202 |
| litho | resilimes | fixed | 95.0 | 3034 | 98 (0+98) | 60 | 1 | 139 |
| litho | resilimes | dynamic | 97.7 | 3132 | 65 (0+65) | 9 | 0 | 141 |
| litho | edd | main | 85.9 | 2587 | 208 (208+0) | 55 | 162 | 184 |
| litho | edd | fixed | 83.6 | 2606 | 413 (0+413) | 99 | 0 | 184 |
| litho | edd | dynamic | 83.6 | 2606 | 413 (0+413) | 99 | 0 | 184 |
| hot | resilimes | main | 93.9 | 2913 | 70 (70+0) | 39 | 81 | 202 |
| hot | resilimes | fixed | 95.1 | 3031 | 96 (0+96) | 59 | 1 | 141 |
| hot | resilimes | dynamic | 97.8 | 3132 | 61 (0+61) | 8 | 0 | 142 |
| hot | edd | main | 86.0 | 2598 | 207 (207+0) | 53 | 161 | 184 |
| hot | edd | fixed | 83.7 | 2608 | 411 (0+411) | 98 | 0 | 185 |
| hot | edd | dynamic | 83.7 | 2608 | 411 (0+411) | 98 | 0 | 185 |
| heldout_published | resilimes | main | 94.0 | 2921 | 76 (76+0) | 43 | 69 | 202 |
| heldout_published | resilimes | fixed | 95.0 | 3033 | 100 (0+100) | 59 | 1 | 139 |
| heldout_published | resilimes | dynamic | 97.6 | 3111 | 69 (0+69) | 8 | 0 | 141 |
| heldout_published | edd | main | 85.6 | 2596 | 218 (218+0) | 61 | 155 | 187 |
| heldout_published | edd | fixed | 83.6 | 2622 | 415 (0+415) | 100 | 0 | 186 |
| heldout_published | edd | dynamic | 83.6 | 2622 | 415 (0+415) | 100 | 0 | 186 |
| heldout_xfactor | resilimes | main | 92.5 | 2897 | 97 (97+0) | 46 | 91 | 195 |
| heldout_xfactor | resilimes | fixed | 95.1 | 3003 | 98 (0+98) | 56 | 0 | 136 |
| heldout_xfactor | resilimes | dynamic | 93.8 | 2937 | 127 (0+127) | 67 | 1 | 139 |
| heldout_xfactor | edd | main | 83.8 | 2518 | 260 (260+0) | 53 | 174 | 189 |
| heldout_xfactor | edd | fixed | 81.9 | 2535 | 459 (0+459) | 98 | 2 | 186 |
| heldout_xfactor | edd | dynamic | 81.9 | 2535 | 459 (0+459) | 98 | 2 | 186 |
| litho_family_2h | resilimes | main | 93.7 | 2898 | 76 (76+0) | 37 | 81 | 202 |
| litho_family_2h | resilimes | fixed | 94.6 | 3013 | 107 (0+107) | 64 | 0 | 140 |
| litho_family_2h | resilimes | dynamic | 97.8 | 3136 | 63 (0+63) | 9 | 0 | 141 |
| litho_family_2h | edd | main | 85.7 | 2597 | 209 (209+0) | 56 | 168 | 184 |
| litho_family_2h | edd | fixed | 83.2 | 2602 | 421 (0+421) | 105 | 0 | 184 |
| litho_family_2h | edd | dynamic | 83.2 | 2602 | 421 (0+421) | 105 | 0 | 184 |

### Table 3. All five policies, main / fixed / dynamic

| Book | Policy | On-time % | Completed | Q true rate % | Batch fill % |
|---|---|---|---|---|---|
| published | resilimes | 57.1 / 55.0 / 57.1 | 135.8 / 122.0 / 80.2 | 94.0 / 94.9 / 97.8 | 68.9 / 71.1 / 72.6 |
| published | edd | 57.5 / 57.5 / 57.5 | 160.0 / 159.6 / 159.6 | 86.0 / 83.7 / 83.7 | 66.6 / 66.1 / 66.1 |
| published | fifo | 36.1 / 36.1 / 36.1 | 97.4 / 94.8 / 94.8 | 72.0 / 74.3 / 74.3 | 66.4 / 66.6 / 66.6 |
| published | cr | 57.1 / 55.7 / 55.7 | 64.4 / 63.0 / 63.0 | 87.3 / 84.6 / 84.6 | 69.7 / 69.7 / 69.7 |
| published | smt_rule | 57.1 / 55.7 / 55.7 | 61.2 / 60.4 / 60.4 | 87.6 / 85.5 / 85.5 | 73.4 / 73.2 / 73.2 |
| xfactor_eta600 | resilimes | 99.1 / 63.9 / 84.4 | 138.0 / 124.6 / 113.0 | 92.6 / 94.6 / 93.7 | 68.7 / 70.0 / 74.3 |
| xfactor_eta600 | edd | 99.5 / 99.5 / 99.5 | 165.8 / 166.6 / 166.6 | 84.3 / 82.4 / 82.4 | 67.5 / 67.7 / 67.7 |
| xfactor_eta600 | fifo | 45.3 / 54.0 / 54.0 | 98.2 / 96.4 / 96.4 | 72.0 / 74.1 / 74.1 | 66.5 / 66.7 / 66.7 |
| xfactor_eta600 | cr | 76.1 / 76.1 / 76.1 | 89.0 / 89.0 / 89.0 | 69.9 / 67.7 / 67.7 | 70.9 / 69.9 / 69.9 |
| xfactor_eta600 | smt_rule | 74.9 / 74.5 / 74.5 | 92.0 / 92.2 / 92.2 | 69.1 / 66.1 / 66.1 | 74.8 / 75.2 / 75.2 |
| heldout_published | resilimes | 57.1 / 55.4 / 57.1 | 144.4 / 130.8 / 82.2 | 94.0 / 95.0 / 97.6 | 68.2 / 70.5 / 71.3 |
| heldout_published | edd | 57.1 / 57.5 / 57.5 | 165.2 / 164.6 / 164.6 | 85.6 / 83.6 / 83.6 | 65.8 / 65.6 / 65.6 |
| heldout_published | fifo | 37.1 / 37.9 / 37.9 | 104.4 / 99.0 / 99.0 | 70.9 / 73.5 / 73.5 | 65.9 / 66.0 / 66.0 |
| heldout_published | cr | 56.8 / 55.0 / 55.0 | 62.2 / 62.6 / 62.6 | 88.0 / 84.9 / 84.9 | 69.1 / 68.4 / 68.4 |
| heldout_published | smt_rule | 57.1 / 55.7 / 55.7 | 62.2 / 61.6 / 61.6 | 87.4 / 85.6 / 85.6 | 73.1 / 72.1 / 72.1 |
| heldout_xfactor | resilimes | 100.0 / 77.9 / 93.6 | 140.8 / 126.8 / 117.0 | 92.5 / 95.1 / 93.8 | 67.9 / 69.6 / 74.0 |
| heldout_xfactor | edd | 100.0 / 100.0 / 100.0 | 167.6 / 166.2 / 166.2 | 83.8 / 81.9 / 81.9 | 66.9 / 66.7 / 66.7 |
| heldout_xfactor | fifo | 56.6 / 61.6 / 61.6 | 105.2 / 101.2 / 101.2 | 70.7 / 73.5 / 73.5 | 65.9 / 65.9 / 65.9 |
| heldout_xfactor | cr | 77.7 / 78.6 / 78.6 | 89.0 / 89.0 / 89.0 | 70.8 / 68.4 / 68.4 | 70.8 / 69.3 / 69.3 |
| heldout_xfactor | smt_rule | 81.4 / 81.1 / 81.1 | 91.4 / 92.0 / 92.0 | 70.4 / 67.5 / 67.5 | 75.2 / 75.1 / 75.1 |

### Table 4. Batch fill (lots / furnace lot capacity, mean over books and seeds)

| Policy | main | fixed | dynamic |
|---|---|---|---|
| resilimes | 69.8 | 71.9 | 73.4 |
| edd | 68.0 | 67.9 | 67.9 |
| fifo | 67.8 | 68.1 | 68.1 |
| cr | 70.7 | 70.2 | 70.2 |
| smt_rule | 74.7 | 74.5 | 74.5 |

### Table 5. ResiliMES holds, reservations, dispatch latency, scheduling tick (dynamic)

| Book | Reservations / run (released by replan) | Minutes held / run | Hold lot-min | Dispatch p95 / busy-p95 ms main → fixed → dyn | Tick p50 / p95 ms | Tick total s / sim s | Stalls / ticks (batch) | ρ |
|---|---|---|---|---|---|---|---|---|
| published | 10.8 (0.0) | 38 | 4451 | 0.0065/0.148 → 0.0073/0.181 → 0.0089/0.324 | 3.37 / 4.08 | 2.00 / 6.91 | 0.4 / 576 (0.0) | 0.77 |
| xfactor_eta600 | 8.0 (0.0) | 24 | 6402 | 0.0067/0.141 → 0.0076/0.164 → 0.0092/0.297 | 3.52 / 4.38 | 2.09 / 6.78 | 0.0 / 576 (0.0) | 0.95 |
| tight_vip | 12.8 (0.0) | 44 | 4104 | 0.0063/0.134 → 0.0073/0.169 → 0.0092/0.250 | 3.44 / 4.41 | 1.02 / 3.26 | 0.2 / 288 (0.2) | 0.60 |
| pm_enforced | 6.4 (0.2) | 28 | 5175 | 0.0062/0.135 → 0.0071/0.169 → 0.0088/0.298 | 3.39 / 4.06 | 1.99 / 6.70 | 0.8 / 576 (0.8) | 0.82 |
| litho | 12.0 (0.0) | 44 | 4524 | 0.0063/0.146 → 0.0073/0.183 → 0.0082/0.314 | 3.17 / 4.04 | 1.89 / 6.51 | 0.4 / 576 (0.0) | 0.76 |
| hot | 9.8 (0.0) | 44 | 4446 | 0.0066/0.158 → 0.0074/0.193 → 0.0080/0.298 | 3.16 / 3.63 | 1.85 / 6.36 | 0.8 / 576 (0.6) | 0.77 |
| heldout_published | 10.0 (0.0) | 36 | 4638 | 0.0066/0.148 → 0.0073/0.189 → 0.0083/0.298 | 3.15 / 3.62 | 1.85 / 6.43 | 0.8 / 576 (0.6) | 0.77 |
| heldout_xfactor | 8.8 (0.0) | 25 | 6288 | 0.0069/0.146 → 0.0075/0.171 → 0.0090/0.293 | 3.46 / 4.32 | 2.03 / 6.65 | 0.0 / 576 (0.0) | 0.95 |
| litho_family_2h | 10.0 (0.0) | 39 | 4464 | 0.0064/0.145 → 0.0073/0.180 → 0.0086/0.306 | 3.28 / 4.05 | 1.96 / 6.67 | 0.0 / 576 (0.0) | 0.76 |

### Table 6. Scheduling tick on other policies (dynamic run, seed mean)

| Book | Policy | Tick p95 ms | Tick total s / sim s | Stalls / ticks |
|---|---|---|---|---|
| published | resilimes | 4.08 | 2.00 / 6.91 | 0.4 / 576 |
| published | edd | 1.86 | 0.91 / 3.30 | 0.0 / 576 |
| published | fifo | 1.78 | 0.90 / 3.18 | 0.0 / 576 |
| published | cr | 2.08 | 1.03 / 3.69 | 0.0 / 576 |
| published | smt_rule | 1.94 | 0.94 / 4.75 | 0.4 / 576 |
| xfactor_eta600 | resilimes | 4.38 | 2.09 / 6.78 | 0.0 / 576 |
| xfactor_eta600 | edd | 1.93 | 0.92 / 3.29 | 0.4 / 576 |
| xfactor_eta600 | fifo | 1.76 | 0.89 / 3.17 | 0.0 / 576 |
| xfactor_eta600 | cr | 2.40 | 1.06 / 3.81 | 0.0 / 576 |
| xfactor_eta600 | smt_rule | 1.97 | 0.94 / 4.46 | 0.0 / 576 |

### Table 7. Ablation of the policy fixes, fixed order vs dynamic (ResiliMES, seeds 1–5)

Each cell: fixed / dynamic. Main has no policy fixes (row "none" is the branch with `r2_policy=False`).

| Variant | published on-time % (fixed / dyn) | published completed (fixed / dyn) | xfactor_eta600 on-time % | xfactor completed | Q true rate % pub |
|---|---|---|---|---|---|
| none (mech) | 57.1 / – | 138.4 / – | 99.8 / – | 137.2 / – | 93.6 / – |
| fix 1 | 55.4 / 55.4 | 121.6 / 121.6 | 60.7 / 60.7 | 123.6 / 123.6 | 94.9 / 94.9 |
| fix 2 | 57.1 / 56.8 | 136.8 / 79.6 | 98.6 / 84.6 | 136.6 / 113.4 | 93.6 / 97.5 |
| fix 3 | 57.1 / 57.1 | 137.8 / 138.2 | 99.8 / 99.8 | 137.2 / 137.0 | 93.7 / 93.7 |
| fix 1+2 | 55.4 / 56.8 | 120.8 / 79.6 | 64.4 / 84.6 | 125.4 / 113.4 | 94.9 / 97.5 |
| fix 2+3 | 57.1 / 57.1 | 136.6 / 80.2 | 98.9 / 84.4 | 137.8 / 113.0 | 93.7 / 97.8 |
| fix 1+3 | 55.4 / 55.4 | 121.8 / 121.6 | 60.7 / 60.7 | 123.8 / 123.8 | 95.0 / 95.0 |
| fix 1+2+3 (shipped) | 55.0 / 57.1 | 122.0 / 80.2 | 63.9 / 84.4 | 124.6 / 113.0 | 94.9 / 97.8 |

## Stress: Litho_FE_92 family (26 scanners) down 2 h in the busy window

Outage at 0 h (deepest queue on main) and at 24 h, every policy, seeds 1–5 (50 runs per version). The audit
samples every 5 min:

- **Hard stall:** an idle, up tool with a startable lot and no pending event.
- **Stranded:** a lot no tool of its family may ever start.
- **Frozen WIP:** no step done fab-wide over one sample after the first hour.
- **Late start:** an idle tool waiting for a pending wake.

The full invariant checker runs as well.

| Version | Runs | Hard-stall samples | Runs with stranded lots (max) | Frozen WIP | Invariant failures | Longest late wait | Min fab steps/h in outage |
|---|---|---|---|---|---|---|---|
| main | 50 | 139 (resilimes 16, fifo 60, cr 43, smt_rule 20, edd 0) | 50 / 50 (max 52 lots) | 0 | 0 | 716 min | – |
| fixed | 50 | 0 | 0 / 50 | 0 | 0 | 29.7 min | 349 |
| dynamic | 50 | 0 | 0 / 50 | 0 | 0 | 29.7 min | 349 |

ResiliMES under stress, dynamic version:
- 55.4–58.9 % on-time;
- 78–85 completed routes (the throughput regression, below);
- 58–90 Q-time violations per run (fixed: 133–191);
- 5–19 holds and 3–88 held minutes per run.

The scheduling tick's own stall counter agrees with the audit: nothing beyond furnaces waiting to fill
a batch. **Verdict: no deadlock, starvation or stranded lot in either branch version.** `make smt-invariants`
(`invariant_sweep`, 5 books × 5 policies, with the stall, frozen-WIP and stranded checks) reports 0
failures on the dynamic version.

## Regressions and root causes

1. **ResiliMES completed routes −41 % vs main on the `published`-type books (dynamic fix 2).**
   - **Mechanism:** the `ρ · P_after` term of the due risk grows with the route still ahead, so a lot
     early in its route gets high risk. The ranking then behaves like critical ratio (the `cr`
     baseline completes about 63 routes here).
   - **Evidence** (`published`, seed 1, fix 2 alone vs no policy fix):
     - Steps done are equal (39,371 vs 39,337).
     - Steps in the first fifth of the routes rise 6,475 → 8,950 (+38 %).
     - Steps in the last fifth fall 9,732 → 8,054 (−17 %).
     - With ρ forced to 0 as a diagnosis only (not shipped), completed routes return to 134. The
       Q-time rate then falls back to the old level too: 190 violations instead of 93.
   - **Effect:** WIP moves forward but fewer lots finish inside the 48 h horizon. On-time is
     unaffected on `published`, because the due-in-horizon lots there are mostly already late
     (infinite risk) or far from due.
   - **Why not fixed:** any cut-off or discount on the downstream term would be a tuned weight. The
     choice needs a decision (see "Open questions").
2. **X-factor on-time −15 points vs main (84.4 vs 99.1 %; held-out 93.6 vs 100 %).**
   - The same mechanism: X-factor due dates are tight relative to the remaining route only for
     back-end lots, which now lose priority to front-end lots with a large `ρ · P_after`.
   - The dynamic version still recovers 20 points over the fixed version (63.9 %). There the fix-1
     shortlist admission over-served Q-time.
3. **Fix 1 is now neutral.**
   - With the dynamic fix 2, fix 1 changes nothing: 1+2 equals 2 alone on both books (Table 7).
   - The windowed lots that matter already rank high, so their admission order rarely decides
     anything.
   - Fix 1 alone still costs throughput, as before (121.6 completed).
4. **Dispatch busy p95 0.178 → 0.298 ms** (ResiliMES mean over the books).
   - The cause is the per-lot risk: it sums the family waits up to the Q-time target, memoised per
     moment.
   - It is still well under 1 ms. The baselines moved by under 0.01 ms (tick events in the heap).
5. **Holds replace late starts (unchanged from PR #21, fix 5, shared).**
   - Baseline Q-time rates stay 2–3 points under main, e.g. EDD 86.0 → 83.7 %.
   - The reason: lots that main let start late are now held or recleaned at their deadline. Compare
     policies within a version.
6. **Batch fill:** ResiliMES 69.8 / 71.9 / 73.4 %. The baselines are unchanged (only ResiliMES has a
   capped shortlist).
7. **Reservations:** 6.4–12.8 per run and 24–44 held minutes per run (fixed: 8.4–12.8 and 29–62).
   Released by `replan`: 0–0.2 per run. Holds are now granted only from the tick's plan.

8. **Step dues: Q-time true rate −2.7 points vs dynamic(ratio)** (`published` 97.8 → 95.1 %; Q-time
   violations 71 → 155 per run, re-cleans 9 → 56). Still above fixed (94.9 %) and main (94.0 %).
   - **Not a ranking change.** `published` seed 1: starts where a lot in an open window was passed
     over fell 3779 → 264; passed over by a lot with due risk ≥ 1, 244 → 74.
   - **Mechanism: WIP redistribution.** ρ held WIP at the front of the routes (family 99 queue
     129 → 82), so the Q-time target families downstream were less loaded. With step dues the WIP
     moves on: mean queue at Q-target families 497 → 540 (+8.7 %) with total WIP flat (1086 vs
     1077). The ratio version's Q-time gain was a side effect of starving the back of the line.
   - **Why not fixed:** recovering it would mean holding WIP back on purpose, i.e. a weight.
9. **Step dues: `xfactor_eta600` on-time −3.0 points vs ratio** (84.4 → 81.4 %; held-out 93.6 → 92.4 %,
   completed 117 → 112.4), mostly seed 2 (63 → 46 on-time lots, tardiness 2048 → 5089 min).
   - **Mechanism:** the step dues come from a backward pass with no queueing (it is ρ = 0), so a lot
     looks on plan until its slack to the step due is gone; lead lots with due risk ≥ 1 fell
     1049 → 391. Still 17.7 points under main (99.1 %).
10. **Step dues: `tight_vip` on-time −2.8 points** (27.6 → 24.8 %, still twice EDD's 12.4 %): 3 of 105
    lots over 5 seeds (1 in seed 1, 2 in seed 4), the same mechanism; weighted tardiness +8 %.
11. **Step dues: latency.** Dispatch busy p95 0.30 → 0.34 ms, tick p95 4 → 7.5 ms (schedule build
    included), sim time 6.9 → 10.2 s per run (loaded box). Baselines get the tick cost too when a plan
    is given.

## Open questions (need a decision; nothing tuned)

- **Downstream term:** answered in PR #22 by the plan's step due dates (no ρ). Open: should the plan's
  backward pass include expected queueing (a per-family planned wait)? That would bring back part of the
  downstream look-ahead (regression 9) and part of the WIP shift (regression 8); it needs a
  planned-wait model, not a tuned factor.
- **Schedule as commitment:** the 300 s schedule is followed on ~11 % of starts. Should dispatch prefer
  the head (and how strongly), or stay a measurement? Not decided; nothing changed in dispatch.

## Caveats

- **Still a constant:** the PR #18 urgency band (15 min margin) is a fixed number. The 15 min hold cap
  and the 300 s tick are design limits, not weights.
- **Fab-wide ρ:** ρ is one fab-wide ratio, not per route or family, and it starts at 0. Before the first
  tick, and until starts accumulate, the due risk counts only the wait at the current step.
- **Stale estimates:** wait estimates and the hold plan are up to 5 min old. A lot that becomes inbound
  after the last tick gets no hold until the next tick; dispatch never sets a hold on its own.
- **Tick cost on every policy:** the tick adds a heap event every 300 s to all policies. The snapshot
  costs extra only with `record` (UI and study runs). Baseline outcomes are identical to the fixed
  version.
- **Stall counter:** the counter includes furnaces that are waiting by design to fill a batch
  (`tick_stalls_batch`).
- **Inherited windows:** the 433 inherited windows are taken to open at t=0 with their full limit.
- **Scope:** one snapshot, five training seeds and five held-out seeds.
- **Plan (PR #22):** WIP only (no `order.txt` releases in the simulator), computed once at t=0 with no
  knowledge of downs; the stress outage is not in the plan. `schedule_stale` counts every start the 300 s
  schedule did not foresee, so it is large by construction (see its split in Table P2).

## Note for ui-r1 (PR #19, `resilimes/smt/kpi.py`)

`kpi.qtime_achievement` counts only `met` and `violated`, and drops windows ended by a re-clean or still
open past their deadline. That is why the UI shows 93.4 % where the true rate is 2692/3108 = 86.6 %.

On ui-r1:

1. Take the backend block `qtime_kpi.qtime_buckets(result)`, which is already in the scenarios API
   kpis on this branch. Show its four buckets, `met`, `started_late` (with `held` as a sub-count),
   `recleaned` and `open_expired`, and use `rate_pct` = met / (sum of the four).
2. Show `inherited` (the 433 snapshot windows) as a separate line, never in the dispatcher rate.
3. Show `hold_lot_min` beside the hold count.
4. In `kpi.py`, map a window closed by a re-clean to `recleaned` and an open window whose deadline is
   at or before the horizon to `open_expired`. Then compute the rate with `bucket_counts` instead of
   met / (met + violated).
