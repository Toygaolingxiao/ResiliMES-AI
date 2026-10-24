# Planning-r1 study: main / dyn / plan, 2 d and 7 d, closed fab and with releases

> **Default on main (default-plan PR).** ResiliMES runs with the plan (position gate) unless `RESILIMES_SCHED_MODE=strict_qtime` or `sched_mode="strict_qtime"` is set. It uses fixes 2+3, so fix 1 is off; the study arms below ran with fixes 1-3. Quick check, published book, 7 d closed, seeds 1-3: default 503.7 completed/run, 91.96% on-time, 94.63% true Q-time. Strict Q-time gives 362.7 / 91.85% / 97.19%, and EDD 520.0 / 91.96% / 89.24%. In the 9-book table below, EDD stays about 3 pp ahead on on-time (93.6 vs 90.2). See the README section "Default scheduling mode".

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

### Fix tried: position-in-queue wait at the risk-1 gate (commit 7e1ebee)

**What changed.** For plan runs, the "expected to miss" gate in `plain_rank` (risk ≥ 1 → ahead of setup
and of every lot below 1) now reads `place_risk`: the same max(Q-time, step-due) ratio, but with each
lot's **own** expected wait instead of the family-average wait. Wait at a place = time until a tool of
the family is back (none up) + (busy residual of the up tools + raw process time of the lots ahead) /
up tools. "Ahead" is the dispatch order below the gate without the tool-specific setup term:
(urgency band, class tier, −risk, plan band, plan rank, lot). The same place model is used for the
downstream measured Q-time steps (the lot is inserted into each downstream queue by the same key), and
for both terms, so each term is wait over its own slack and 1 means "misses at its place in line".
No constant, weight, threshold, seed or due was added or changed. `run_policy(plan_wait="family")`
(study arm `plan_famwait`) keeps the old behaviour; non-plan runs and `main` are unchanged.

**One deviation from the proposal, on design grounds.** The ordering *below* the gate (−risk after
setup) still uses the family-average risk. Using the position wait there too makes the order
self-referential: the lot ranked last gets the largest wait, hence the largest risk, hence goes first,
which reverses the plan order (it broke `test_schedule_head_is_the_rank_1_lot...`; on published seed 1,
2 d it gave 124 completed vs 133). With the family risk in the key, the place key does not depend on
the place it produces. The ~95× scale gap between the Q-time and step-due ratios *below* 1 is therefore
not normalised by this fix; I did not add a second normalisation because every candidate (scaling by
segment length or remaining cycle) is a flow-factor-like weight, i.e. tuning.

**Mechanism check (published seed 1, 2 d, ResiliMES plan):** `plain_rank` calls with risk ≥ 1 fell from
16,133 (family wait) to 10,117 (own place), −37 %; 1,987 of the remaining are windows already lost
(Q slack ≤ 0, risk = ∞).

### Result (same 9 books × 5 policies × 5 seeds, closed fab, 225 runs per arm)

`plan_famwait` on the fixed branch reproduces the old plan rows exactly (7 d: 90.6 / 455.6 / 94.6 /
16,897), so the old/new difference is the fix alone. "main current" = `main` 4f8461f + the PED overflow
fix (PR #27): it contains qtime-r2 (fix 1 off) and gives the same ResiliMES numbers as dyn to 0.1.

| Horizon | Arm | On-time % | Completed/run | True Q-time % | W. tardiness min/run | Mean X-factor | Route on-time max−min (pt) | Route completed CV | Route X-factor CV | Litho_FE_92 starved % | Litho_BE_110 starved % | Queue CV | End WIP Q1..Q5 % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 7 d closed | main 641d988 (pre-r2) | 93.5 | 456.3 | 92.8 | 15,189 | 2.18 | 22.2 | 0.388 | 0.227 | 1.9 | 0.59 | 3.00 | 11.1 / 18.3 / 29.2 / 24.8 / 16.6 |
| 7 d closed | main 4f8461f+ped (current) | 92.5 | 333.2 | 97.1 | 15,102 | 3.42 | 26.1 | 0.428 | 0.344 | 15.4 | 3.08 | 2.95 | 5.3 / 23.4 / 27.0 / 18.6 / 25.7 |
| 7 d closed | plan old (family wait) | 90.6 | 455.6 | 94.6 | 16,897 | 2.36 | 27.8 | 0.402 | 0.263 | 19.8 | 1.14 | 2.72 | 9.4 / 17.8 / 29.4 / 26.2 / 17.1 |
| 7 d closed | plan new (position gate) | 90.2 | 455.7 | 94.5 | 16,660 | 2.36 | 24.2 | 0.402 | 0.260 | 20.0 | 1.18 | 2.74 | 9.4 / 18.0 / 29.2 / 26.4 / 17.0 |
| 7 d closed | dyn (qtime-r2) | 92.5 | 333.2 | 97.1 | 15,103 | 3.42 | 26.1 | 0.428 | 0.344 | 15.4 | 3.06 | 2.95 | 5.2 / 23.4 / 27.1 / 18.6 / 25.7 |
| 7 d closed | EDD | 93.6 | 464.7 | 88.8 | 14,985 | 2.07 | 15.6 | 0.374 | 0.254 | 23.8 | 0.63 | 2.98 | 17.2 / 17.5 / 21.7 / 27.0 / 16.5 |
| 7 d closed | FIFO | 75.3 | 396.7 | 83.1 | 80,946 | 2.54 | 49.3 | 0.342 | 0.167 | 25.1 | 1.37 | 3.61 | 12.3 / 22.3 / 25.5 / 18.8 / 21.0 |
| 2 d closed | main 641d988 (pre-r2) | 69.7 | 126.8 | 93.6 | 14,421 | 2.27 | 78.7 | 0.539 | 0.446 | 5.0 | 0.65 | 2.80 | 15.6 / 19.6 / 26.1 / 19.9 / 18.9 |
| 2 d closed | main 4f8461f+ped (current) | 66.1 | 82.0 | 96.6 | 14,304 | 2.77 | 92.4 | 0.618 | 0.688 | 16.7 | 2.90 | 2.36 | 15.1 / 21.1 / 25.5 / 17.0 / 21.3 |
| 2 d closed | plan old (family wait) | 65.4 | 108.9 | 94.9 | 14,554 | 2.31 | 85.9 | 0.562 | 0.456 | 17.4 | 1.11 | 2.36 | 15.4 / 19.6 / 25.7 / 19.7 / 19.5 |
| 2 d closed | plan new (position gate) | 63.5 | 109.1 | 94.9 | 14,664 | 2.31 | 83.9 | 0.568 | 0.453 | 17.4 | 1.02 | 2.36 | 15.4 / 19.6 / 25.8 / 19.7 / 19.5 |
| 2 d closed | dyn (qtime-r2) | 66.1 | 82.0 | 96.6 | 14,304 | 2.77 | 92.4 | 0.618 | 0.688 | 16.7 | 2.90 | 2.36 | 15.1 / 21.1 / 25.5 / 17.0 / 21.3 |
| 2 d closed | EDD | 69.6 | 148.2 | 82.4 | 14,178 | 2.16 | 71.8 | 0.544 | 0.396 | 18.7 | 0.32 | 2.48 | 17.3 / 19.2 / 25.2 / 20.3 / 17.9 |
| 2 d closed | FIFO | 42.0 | 89.4 | 74.1 | 32,683 | 2.83 | 88.5 | 0.600 | 0.319 | 14.7 | 1.13 | 2.69 | 16.7 / 19.2 / 25.7 / 17.3 / 21.0 |

EDD and FIFO are the branch-code baselines (identical in every plan/dyn file).

Paired by book and seed (45 pairs), ResiliMES:

| Horizon | Pair (b − a) | n | Completed/run (sd) | Runs better / worse | On-time lots/run | W. tardiness min/run | Q windows met/run |
|---|---|---|---|---|---|---|---|
| 7 d | plan new − plan old | 45 | +0.1 (1.7) | 17 / 16 | -1.1 | -237 | -13.5 |
| 7 d | plan new − main 641d988 | 45 | -0.6 (3.5) | 18 / 16 | -9.6 | +1,472 | +353.6 |
| 7 d | plan new − main current | 45 | +122.6 (44.7) | 40 / 0 | -6.7 | +1,559 | -303.3 |
| 2 d | plan new − plan old | 45 | +0.2 (2.4) | 19 / 15 | -1.1 | +110 | -15.2 |
| 2 d | plan new − main 641d988 | 45 | -17.7 (9.2) | 1 / 40 | -3.6 | +243 | +93.4 |
| 2 d | plan new − main current | 45 | +27.1 (23.9) | 32 / 8 | -1.6 | +360 | -65.6 |

On-time % / completed per run by book where the arms differ (ResiliMES):

| Horizon | Book | main 641d988 | plan old | plan new |
|---|---|---|---|---|
| 7 d | heldout_xfactor | 100.0 / 514.0 | 86.5 / 515.8 | 84.2 / 516.2 |
| 7 d | xfactor_eta600 | 100.0 / 509.2 | 91.2 / 507.4 | 90.6 / 509.2 |
| 7 d | tight_vip | 25.7 / 26.6 | 24.8 / 27.0 | 27.6 / 27.0 |
| 2 d | heldout_xfactor | 100.0 / 140.8 | 93.6 / 113.0 | 88.3 / 111.6 |
| 2 d | xfactor_eta600 | 99.1 / 138.0 | 80.9 / 113.4 | 73.3 / 110.8 |
| 2 d | published | 57.1 / 135.8 | 56.8 / 118.0 | 56.4 / 118.4 |

**Verdict, honestly: the fix does not fix the regression.**

- Plan new vs plan old is within seed noise on every outcome KPI: completed +0.1 (7 d) / +0.2 (2 d)
  per run, on-time −0.4 / −1.9 points, Q-time −0.1 / 0.0, weighted tardiness −237 / +110 min per run.
  The only visible gain is the route on-time spread at 7 d (24.2 vs 27.8 points); route completed and
  X-factor CV are unchanged. On the X-factor books the new gate is slightly *worse* (2 d xfactor_eta600
  80.9 → 73.3 %).
- **Pre-registered criterion: fails.** 2 d completions are 17.7 per run below main 641d988 (1 / 40 runs
  better), not within seed noise. The Q-time rate does stay above main's (94.9 vs 93.6).
- Plan new vs current main (= dyn): +27 (2 d) and +123 (7 d) completions per run, 40 / 0 runs better
  at 7 d, but −2.6 / −2.3 points on-time, +360 / +1,559 min weighted tardiness and 1.7 / 2.6 points lower
  true Q-time rate.
- **EDD is still at least as good as every ResiliMES arm on on-time, completed and weighted tardiness**
  (7 d 93.6 % / 464.7 / 14,985), and has the narrowest route on-time spread (15.6); its Q-time rate is
  the worst of the non-FIFO arms (88.8 %).
- Litho_FE_92 starvation is unchanged by the fix (20.0 vs 19.8 %); EDD under the same simulator code
  starves it more (23.8 %).

Why it is not enough: cutting the whole-queue alarm removed 37 % of the risk ≥ 1 decisions, but the
remaining Q-time pressure works through the *below-1* order, where the Q-time ratio (minutes of window
slack) is still ~95× the step-due ratio (whole-lot slack), so windowed lots keep outranking near-finish
lots after setup. The earlier counterfactual (Q-time term removed: 69.8 % / 128.5 at 2 d) shows that is
where the loss sits. A real fix has to make the two terms commensurable below 1 (e.g. express both as
expected lateness cost in the same unit) and that needs a decision on the relative cost of a missed
window vs a minute of lateness; it is a modelling choice to make explicitly, not something to fit on
these results.

## Caveats

- The counterfactual and mechanism numbers come from a diagnosis harness that monkey-patches `_Sim`
  (not committed); the instrumented published seeds 1–3 reproduce the study rows exactly (133 / 93 / 107
  completed).
- The 7 d main 641d988 arm needed the harness-only overflow guard above; at 48 h main is unchanged. The
  overflow is now fixed in code (`PED_EXP_CAP`, PR #27, also on this branch); "main current" runs use it.
- The 2 d "old" rows (main 641d988, plan old, dyn, EDD, FIFO) are the earlier Table S1/K1 runs with the
  same books, seeds and settings; the 7 d plan-old row was rerun on this branch (`plan_famwait`).
- One plan built at t = 0, no replan, and no MES actuals; litho is the only finite capacity in the plan.
- At 7 d most WIP lots that are due inside the horizon finish in every arm, so on-time at 7 d mainly
  separates arms on the X-factor and tight books.
- The position-gate fix was run on the closed fab only (2 d and 7 d); the "7 d + releases" rows above
  are the pre-fix runs. Releases did not change any arm's ranking before the fix.
