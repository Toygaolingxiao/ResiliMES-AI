# Planning-r1 study: main / dyn / plan, 2 d and 7 d, closed fab and with releases

Branch `planning-r1` (PR #22). Write-up of the KPI study and of why the plan arm regresses against main.
Nothing here was tuned: no weight, seed, due date or horizon was changed to make an arm win.
Step targets are the backward pass over SMT2020 master-data standard times (PTIME by PTPER + setup) with
the forward litho capacity check (`smt/planning.py`); order lead time is not spread over the route.

## Arms and runs

| Arm | Code | Dispatcher (ResiliMES) |
|---|---|---|
| main | `main` 641d988 | tiered key: band, tier, late, Q-time PED, setup, slack |
| dyn | qtime-r2 (PR #21) | risk = expected wait / remaining slack, max of due and Q-time |
| plan | `planning-r1` | same risk, but the due term uses the plan's step due; plan band/rank tie-break |

- 9 books × 5 policies × 5 seeds = 225 runs per arm and horizon. Seeds and books are the pre-registered
  study set (`qtime_study.BOOKS`, `SEEDS`, `HELDOUT_SEEDS`).
- Horizons: 2 d (48 h, the earlier Table S1/K1 runs) and 7 d (`RESILIMES_STUDY_HORIZON_H=168`).
- Closed fab: only the 2,156 WIP lots. Releases: `RESILIMES_STUDY_RELEASES=1`, `order.txt` lots enter at
  their release (373 per run on average over the books); the plan holds exactly the lots the sim runs.
- **Harness-only guard (main arm, 7 d):** main's PED `exp(k·(1 − ratio))` overflows once a lot is about
  117× past its CQT window, which never happens in 48 h. The 7 d main runs used a copy of main with
  `OverflowError → inf` in `kernel/score.py` (the value the exponential tends to). It is not a change to
  main and is not committed. dyn and plan do not call PED.
- Baselines (EDD, FIFO, CR, SMT rule) do not read the plan; they are identical in the dyn and plan runs
  (branch simulator code). Main-code baselines differ slightly because the shared r2 simulator fixes
  (full-queue batching, scheduling tick, stranded-lot fix) change every policy.
- All 9 × 225-run files completed with no failed or missing rows (`/workspace/study_kpi/*.json` on the
  study box).

## Table R1. Outcome KPIs, ResiliMES (on-time pooled over due lots; others mean per run)

| Horizon | Arm | On-time % | Completed/run | True Q-time % | W. tardiness min/run | Mean X-factor | Steps/day |
|---|---|---|---|---|---|---|---|
| 2 d closed | main | 69.7 | 126.8 | 93.6 | 14,421 | 2.27 | 19,573 |
| 2 d closed | dyn | 66.1 | 82.0 | 96.6 | 14,304 | 2.77 | 19,676 |
| 2 d closed | plan | 65.4 | 108.9 | 94.9 | 14,554 | 2.31 | 19,623 |
| 7 d closed | main | 93.5 | 456.3 | 92.8 | 15,189 | 2.18 | 17,470 |
| 7 d closed | dyn | 92.5 | 333.2 | 97.1 | 15,103 | 3.42 | 18,448 |
| 7 d closed | plan | 90.6 | 455.6 | 94.6 | 16,897 | 2.36 | 18,156 |
| 7 d + releases | main | 93.5 | 456.6 | 92.8 | 15,158 | 2.18 | 18,718 |
| 7 d + releases | dyn | 92.5 | 328.1 | 98.1 | 15,106 | 3.45 | 19,261 |
| 7 d + releases | plan | 90.6 | 455.7 | 94.8 | 16,746 | 2.36 | 19,210 |

Baselines, branch code (same in the dyn and plan runs):

| Horizon | Policy | On-time % | Completed/run | True Q-time % | W. tardiness min/run | Mean X-factor |
|---|---|---|---|---|---|---|
| 7 d closed | EDD | 93.6 | 464.7 | 88.8 | 14,985 | 2.07 |
| 7 d closed | FIFO | 75.3 | 396.7 | 83.1 | 80,946 | 2.54 |
| 7 d closed | CR | 91.2 | 305.0 | 85.9 | 15,192 | 3.97 |
| 7 d closed | SMT rule | 90.8 | 305.6 | 80.7 | 15,246 | 4.07 |
| 7 d + releases | EDD | 93.5 | 464.6 | 88.9 | 14,978 | 2.07 |
| 7 d + releases | FIFO | 75.5 | 400.5 | 83.2 | 80,272 | 2.53 |
| 7 d + releases | CR | 91.2 | 305.5 | 86.2 | 15,202 | 3.96 |
| 7 d + releases | SMT rule | 90.9 | 305.9 | 81.4 | 15,246 | 3.99 |

Paired by book and seed (45 pairs), plan − main, ResiliMES:

| Horizon | Completed/run | Runs plan better / worse | On-time lots/run | W. tardiness min/run |
|---|---|---|---|---|
| 2 d closed | −17.9 (sd 8.9) | 1 / 40 | −2.5 | +133 |
| 7 d closed | −0.7 (sd 3.4) | 19 / 18 | −8.5 | +1,708 |
| 7 d + releases | −0.9 (sd 3.9) | 20 / 16 | −8.5 | +1,588 |

- **The 2 d completion gap is a delay, not a loss.** At 7 d plan completes the same lots as main (−0.7
  per run, inside seed noise). Releases do not change completions at 7 d (a released lot needs 250–611 h
  of raw process), so they only change WIP position and starvation.
- **The on-time gap at 7 d is the X-factor books.** Every other book is within ±0.2 points except tight_vip (−0.9, its horizon is fixed at 48 h in both); xfactor_eta600
  100.0 → 91.2 % and heldout_xfactor 100.0 → 86.5 % (closed). That is where the extra weighted
  tardiness comes from.
- **Q-time:** plan keeps a real but small gain over main (true rate +1.8 points at 7 d, +1.3 at 2 d).
  dyn has the best Q-time rate and loses 27 % of completions at 7 d.
- **EDD is still at least as good as every ResiliMES arm** on on-time and completed at 7 d, with a worse
  Q-time rate (88.8 %).

## Table R2. Balance KPIs, ResiliMES (mean per run)

Route figures are computed per run over the 10 routes and then averaged (max − min of route on-time;
CV of route completion % and route mean X-factor). Utilisation CV is over tool families. Starved = tool
up, idle and its family queue empty, % of up time. End WIP = share of WIP by route-position quintile
(step index / route length) at the horizon.

| Horizon | Arm | Route on-time max−min (pt) | Route completed CV | Route X-factor CV | Util CV | Queue CV | Litho_FE_92 starved % | Litho_BE_110 starved % | End WIP Q1/Q2/Q3/Q4/Q5 % |
|---|---|---|---|---|---|---|---|---|---|
| 2 d closed | main | 78.7 | 0.539 | 0.446 | 0.320 | 2.80 | 5.0 | 0.65 | 15.6 / 19.6 / 26.1 / 19.9 / 18.9 |
| 2 d closed | dyn | 92.4 | 0.618 | 0.688 | 0.336 | 2.36 | 16.7 | 2.90 | 15.1 / 21.1 / 25.5 / 17.0 / 21.3 |
| 2 d closed | plan | 85.9 | 0.562 | 0.456 | 0.322 | 2.36 | 17.4 | 1.11 | 15.4 / 19.6 / 25.7 / 19.7 / 19.5 |
| 7 d closed | main | 22.2 | 0.388 | 0.227 | 0.358 | 3.00 | 1.9 | 0.59 | 11.1 / 18.3 / 29.2 / 24.8 / 16.6 |
| 7 d closed | dyn | 26.1 | 0.428 | 0.344 | 0.336 | 2.95 | 15.4 | 3.06 | 5.2 / 23.4 / 27.1 / 18.6 / 25.7 |
| 7 d closed | plan | 27.8 | 0.402 | 0.263 | 0.354 | 2.72 | 19.8 | 1.14 | 9.4 / 17.8 / 29.4 / 26.2 / 17.1 |
| 7 d + releases | main | 22.4 | 0.352 | 0.227 | 0.319 | 2.81 | 1.9 | 0.59 | 26.2 / 15.6 / 24.5 / 20.1 / 13.6 |
| 7 d + releases | dyn | 26.4 | 0.391 | 0.348 | 0.313 | 2.84 | 13.8 | 2.61 | 21.1 / 20.8 / 22.8 / 13.6 / 21.7 |
| 7 d + releases | plan | 28.1 | 0.363 | 0.263 | 0.317 | 2.59 | 14.6 | 1.12 | 23.3 / 17.5 / 24.1 / 21.1 / 14.0 |

EDD, branch code, 7 d closed: 15.6 / 0.374 / 0.254 / 0.447 / 2.98 / 23.8 / 0.63; 7 d + releases:
15.8 / 0.334 / 0.254 / 0.412 / 3.03 / 18.2 / 0.65.

What the balance KPIs say, honestly:

- **Product fairness: plan is worse than main.** At 7 d the route on-time spread is 27.8 vs 22.2 points,
  route X-factor CV 0.263 vs 0.227 and route completion CV 0.402 vs 0.388. dyn is worse again on
  completion and X-factor. EDD has the narrowest on-time spread (15.6).
- **Load levelling: plan is slightly better than main and not because it moves work.** Family-queue CV
  2.72 vs 3.00 (closed) and 2.59 vs 2.81 (releases); utilisation CV is the same (0.354 vs 0.358).
- **Bottleneck starvation: the constraint is not starved.** Litho_BE_110 runs at about 99 % and is
  starved 1.1 % (plan) vs 0.6 % (main) of up time. Litho_FE_92 is starved far more in plan (14.6–19.8 %)
  than in main (1.9 %), **but EDD under the same branch simulator code starves it as much (18.2–23.8 %)**,
  so most of that rise comes from the shared r2 simulator changes, not from the plan's dispatching.
  Litho_FE_92 is not the constraint (about 75 % utilised); no completion loss follows from it at 7 d.
- **WIP by route quintile: no front-loading.** Plan's end WIP is within 1.7 points of main per quintile
  (7 d closed) and slightly *later* in the route (Q4 +1.4, Q1 −1.7). With releases, Q1 rises for every
  arm because new lots enter at step 0. dyn is the arm that shifts WIP (Q1 5.2 %, Q5 25.7 %).

## Why plan regresses against main (2 d: 65.4 vs 69.7 % on-time, 108.9 vs 126.8 completed)

### Hypotheses checked and rejected

1. **WIP front-loading** by the plan order: rejected. End and time-mean WIP by quintile are within
   0.6 points of main at 2 d (end 15.4 / 19.6 / 25.7 / 19.7 / 19.5 vs 15.6 / 19.6 / 26.1 / 19.9 / 18.9;
   time mean 17.6 / 19.6 / 24.6 / 18.8 / 19.4 vs 17.6 / 19.5 / 24.9 / 19.0 / 19.0).
2. **Bottleneck starvation:** rejected as the cause. The Q-time counterfactual below keeps
   Litho_FE_92 starved at 15.7 % and still recovers main's completions; Litho_BE_110 starvation is
   ≤ 1.1 % in every plan run.
3. **Setups in the standard time:** rejected earlier (Table S1, `QTIME_R2.md`): no setups 65.3 % /
   109.0 vs with setups 65.4 % / 108.9.

### Counterfactuals (diagnosis harness only, not committed; plan arm, ResiliMES, 9 books × 5 seeds, 2 d)

| Variant | On-time % | Completed/run | True Q-time % | Litho_FE_92 starved % | xfactor_eta600 on-time % |
|---|---|---|---|---|---|
| main | 69.7 | 126.8 | 93.6 | 5.0 | 99.1 |
| plan as shipped | 65.4 | 108.9 | 94.9 | 17.4 | 80.9 |
| plan, Q-time term removed from `risk()` (noq) | 69.8 | 128.5 | 92.5 | 15.7 | 99.1 |
| plan, risk < 1 reported as 0 (gate: plan order decides below 1) | 61.0 | 71.6 | 95.0 | 21.1 | 74.0 |

Removing only the Q-time term from the risk max restores main's on-time and completions in every book
(published 118 → 139, xfactor_eta600 113 → 139 completed), at a cost of 2.4 points of Q-time rate.
Letting the plan's band/rank decide everything below risk 1 is much worse (71.6 completed): the plan
order by itself is a weak tie-break; most of the useful ordering comes from the risk ratio.

### Mechanism (instrumented runs, published and xfactor_eta600, seeds 1–3, 2 d; bit-identical to the study rows)

For every single-lot start with competitors, the harness also ranked the queue with the Q-time term
removed and recorded whether the winner changes ("flip").

| | published | xfactor_eta600 |
|---|---|---|
| Contested single starts | 66,103 | 68,588 |
| Flips caused by the Q-time term | 7,110 (10.8 %) | 7,170 (10.5 %) |
| Starts in the risk ≥ 1 ("expected to miss") branch that are there by Q-time alone | 84.2 % | 88.0 % |
| Flip winners with due/step-due risk < 1 (on plan for their due) | 99.9 % | 100 % |
| Displaced lots with due/step-due risk < 1 | 98.1 % | 97.3 % |
| Flip winner route quintile Q1..Q5 % | 2 / 6 / 21 / 39 / 32 | 3 / 6 / 19 / 39 / 33 |
| Displaced lot route quintile Q1..Q5 % | 3 / 7 / 16 / 18 / **55** | 1 / 7 / 18 / 18 / **57** |
| Median Q-risk / due-risk of the winner | 95× | 97× |

Top families where the flips happen: wet benches WE_BE_82, WE_BE_16, WE_FE_108, WE_BE_14, WE_FE_41,
Dielectric_BE_21/27/28, LithoTrack_FE_95/BE_117 (the clean → furnace / deposition / track CQT chains).

Decomposing the Q-risk / due-risk gap on every `risk()` call of a windowed lot (published seed 1,
41,338 samples): the **numerator** ratio (Q expected wait / wait here) has median 1.0 (p75 1.6); the
**denominator** ratio (step-due slack / Q-time slack) has median 74 (p25 41, p75 138). On that run
1,785 windows reached Q-risk ≥ 1 while the lot's due risk was < 1; the run missed 163 windows
(noq counterfactual: 249).

### Root cause

`risk()` takes the max of two ratios that are on different scales and sends anything ≥ 1 into the
"expected to miss" branch, ahead of setup avoidance and of every lot below 1:

1. The step due is a backward pass with **no queueing** (by design: master-data standard times), so
   step-due slack at any step equals the lot's whole remaining slack, hours to days. Due risk is almost
   always ≪ 1 until a lot is really late.
2. The Q-time slack is the minutes left in a CQT window. Its expected wait is the **family-average wait**
   (`fam_wait`), so whenever a wet bench or dielectric family's average queue is longer than the window
   slack, **every** windowed lot there crosses 1 at once, whether or not it would actually miss at its
   own position in the queue.
3. Those lots then outrank lots that are close to finishing (55 % of the displaced lots are in the last
   route quintile, against 32 % of the winners). Completions slip by hours: −18 per run at 2 d, fully
   caught up by 7 d (−0.7). Where a back-end backlog has to drain on time (the X-factor books, after the
   600-min focus-tool down), the slip turns into missed dues: xfactor_eta600 seeds 2 and 3 fall to 48 and
   51 of 87 due lots on time, against 87 and 83 in main.

Main avoids this because its Q-time term (PED) is exponential in the share of the window used, so it is
~0 until the window is nearly spent, and it sits after main's late band. The trade-off is real: the Q
jump does save windows (163 vs 249 misses on published seed 1), but about 1,785 window-level jumps
bought ~86 saved windows on that run.

### Proposed fix (one, principled, not implemented)

**Make "expected wait" in `risk()` the lot's own expected wait at its position in the queue, not the
family-average wait.** For a lot at family *f*, the expected wait is the process time of the lots ranked
ahead of it at *f* under the below-1 order (setup, risk, plan rank), divided by the qualified, up tools of
*f* (plus the time until the first of them frees). Apply it to both the Q-time and the due term, so
"risk ≥ 1" means "this lot misses at its current place in line", which is what the jump-the-queue branch
is meant to act on.

- No constant, weight or threshold is added; it replaces an estimate with a better-posed one from live
  state that the tick already holds (queue order, tool states, process times).
- It removes the whole-queue alarm of point 2 above: a windowed lot near the head of its queue stays
  below 1 and keeps its normal place; a windowed lot deep in a long queue still jumps.
- It keeps the master-data step targets unchanged (no queue allowance is spread into the plan).

Verification to pre-register before running it: same 9 books × 5 policies × 5 seeds, 2 d and 7 d,
closed and releases; report flip count and share of Q-only risk ≥ 1 starts, completions and on-time
(pooled and X-factor books), true Q-time rate, and every balance KPI above. It counts as a fix only if
2 d completions are within seed noise of main and the true Q-time rate stays at or above main's. No
weight, seed or due may be changed alongside it.

## Caveats

- The counterfactual and mechanism numbers come from a diagnosis harness that monkey-patches `_Sim`
  (not committed); the instrumented published seeds 1–3 reproduce the study rows exactly (133 / 93 / 107
  completed).
- The 7 d main arm needed the harness-only overflow guard above; at 48 h main is unchanged.
- One plan built at t = 0, no replan, and no MES actuals; litho is the only finite capacity in the plan.
- At 7 d most WIP lots that are due inside the horizon finish in every arm, so on-time at 7 d mainly
  separates arms on the X-factor and tight books.
