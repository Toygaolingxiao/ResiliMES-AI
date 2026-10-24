# Q-time r2: shortlist, graded urgency, tool reservation, full-queue batching, deadline rework

Branch `qtime-r2`, from `main` 641d988. Every number below was measured on this box (8 cores) with
`resilimes/smt/qtime_study.py` and `resilimes/smt/stress.py`. No weights, due dates or seeds were changed.
Q-time windows exist only on the 264 dataset CQT/STEP_CQT route steps (`route.cqt_limit > 0`); no
window was added anywhere else.

## Summary

- **Q-time:** ResiliMES met more of its own windows: 94.0 → 94.9 % on `published`, with 188 → 162
  missed windows per run. It also missed fewer of the 433 inherited windows (203 → 140). Lots no longer
  sit in a queue past their deadline: each window now ends as met, started late, recleaned or
  open-expired.
- **Throughput, on-time and X-factor:** ResiliMES regressed. Completed routes fell from 135.8 to 122.0
  per run on `published`. On-time fell from 99.1 to 63.9 % on `xfactor_eta600` and from 100 to 77.9 % on
  held-out X-factor. The ablation below traces the whole regression to **fix 1 (shortlist admission)**.
  Fixes 2 and 3 and the shared mechanics are close to neutral.
- **Stress:** with all five policies the branch has no hard stalls, no stranded lots, no frozen WIP and
  no invariant failures (50 runs). On `main` the same stress had stranded lots in all 50 runs and hard
  stalls under four of five policies. The cause was a pre-existing scanner-pin bug that this work found
  and fixed (see "Extra fix").
- **True Q-time KPI:** the rate now has every missed bucket in its denominator. The note for the UI
  branch (ui-r1, PR #19) is at the end.

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
| 1 | 66c33af | Every open-window lot is admitted to the capped ResiliMES shortlist, least time left first. | ResiliMES |
| 2 | 64a6e39 | Graded urgency `1 - slack/limit`, clipped to [0, 1], where slack = deadline − now − remaining process and transport time before the target. Continuous and monotonic; 1 at the latest start. | ResiliMES |
| 3 | 320ad4a | Bounded reservation: at most 1 tool per family for at most 15 min, never on a down tool or one with PM during the hold, no back-to-back chains. Released when used, used elsewhere, expired or cancelled. Every reservation is logged and counted (count and minutes). | ResiliMES |
| + | d6a300b | Scanner pin binds only the later steps of its own layer (see below). | shared |
| + | 78a1255 | Litho stress book and audit; added to `invariant_sweep`. | test |
| + | 42d78b7 | `qtime_study.py`: one event replay scores every arm the same way. | study |

### Extra fix found by the stress test (shared, changes every policy)

`dedicate_tool` from an earlier litho layer also bound the **root step of the next layer**, even when
that step is in another family. Such a lot was eligible only while its old scanner was down, so it stayed
stranded forever. Main has this bug in every policy: at the 24 h stress start, seed 1, main ResiliMES
ended with 30 stranded lots. `pin_for()` now returns the pin only for a later step of the same layer
whose family is the pinned tool's family. The dedication invariant was narrowed to match.
`tests/test_smt_dedication.py` covers both directions; the first test fails on main.

## Method

- **Arms:**
  - `before`: main 641d988, running the same study script from a /tmp copy.
  - `mech`: branch, `r2_policy=False`.
  - `after`: branch as shipped.
- **Policies:** resilimes, edd, fifo, cr, smt_rule. Only ResiliMES runs in `mech`, because the other
  four do not use the policy fixes.
- **Books** (mirroring `benchmark.py`):
  - `published`
  - `xfactor_eta600` (focus tool down 600 min, X-factor due dates)
  - `tight_vip` (24 h)
  - `pm_enforced`
  - `litho` (focus tool down for the litho MTTR)
  - `hot`
  - `heldout_published` and `heldout_xfactor` (seeds 9–13)
  - `litho_family_2h` (stress outage, below)
- **Seeds:** 1–5 except the held-out books. 495 runs in total.
- **Scoring:** Q-time buckets and batch fill come from the recorded events with one replay for every arm.
  On the branch the replay matched the simulator's own counters exactly (checked on three runs).
- **Q-time rate:** met / (met + started late + recleaned + open-expired). Live windows (deadline after
  the horizon) and skipped targets are not scored.

## Before / after

### Table 1. ResiliMES vs EDD on every book (seed mean; on-time pooled)

| Book | ResiliMES on-time before → mech → after | EDD on-time before → after | ResiliMES completed before → mech → after | EDD completed before → after | ResiliMES X-factor before → after | EDD X-factor before → after |
|---|---|---|---|---|---|---|
| published | 57.1 → 57.1 → **55.0** | 57.5 → 57.5 | 135.8 → 138.4 → **122.0** | 160.0 → 159.6 | 2.58 → 2.56 | 2.21 → 2.23 |
| xfactor_eta600 | 99.1 → 99.8 → **63.9** | 99.5 → 99.5 | 138.0 → 137.2 → **124.6** | 165.8 → 166.6 | 1.74 → 2.15 | 1.59 → 1.59 |
| tight_vip | 25.7 → 25.7 → **23.8** | 12.4 → 12.4 | 26.6 → 26.4 → **27.0** | 38.2 → 41.8 | 1.75 → 1.72 | 4.48 → 3.07 |
| pm_enforced | 57.1 → 56.8 → **55.0** | 57.9 → 57.5 | 139.6 → 139.6 → **124.0** | 156.4 → 156.8 | 2.65 → 2.53 | 2.27 → 2.25 |
| litho | 57.1 → 57.1 → **55.4** | 57.5 → 57.5 | 138.4 → 138.4 → **121.2** | 159.6 → 159.2 | 2.59 → 2.57 | 2.22 → 2.22 |
| hot | 56.1 → 56.1 → **54.4** | 57.5 → 57.5 | 138.4 → 137.4 → **122.2** | 160.0 → 159.6 | 2.51 → 2.57 | 2.21 → 2.23 |
| heldout_published | 57.1 → 57.1 → **55.4** | 57.1 → 57.5 | 144.4 → 147.4 → **130.8** | 165.2 → 164.6 | 2.37 → 2.39 | 2.09 → 2.08 |
| heldout_xfactor | 100.0 → 100.0 → **77.9** | 100.0 → 100.0 | 140.8 → 143.2 → **126.8** | 167.6 → 166.2 | 1.71 → 2.03 | 1.56 → 1.56 |
| litho_family_2h | 57.1 → 57.1 → **55.0** | 57.1 → 57.5 | 139.2 → 140.0 → **122.6** | 159.4 → 159.2 | 2.57 → 2.56 | 2.22 → 2.21 |

### Table 2. Q-time buckets, dispatcher windows (seed mean per run). Rate = met / (met + started late + recleaned + open-expired)

Started late = late + held. Main has no hold, so before-arm misses show up as late or expired. Inherited = misses among the 433 snapshot windows, reported separately.

| Book | Policy | Arm | Rate % | Met | Started late (late+held) | Recleaned | Open-expired | Inherited missed / 433 |
|---|---|---|---|---|---|---|---|---|
| published | resilimes | before | 94.0 | 2922 | 69 (69+0) | 40 | 79 | 203 |
| published | resilimes | mech | 93.6 | 2963 | 144 (0+144) | 59 | 0 | 143 |
| published | resilimes | after | 94.9 | 3031 | 99 (0+99) | 62 | 1 | 140 |
| published | edd | before | 86.0 | 2598 | 207 (207+0) | 53 | 161 | 184 |
| published | edd | after | 83.7 | 2608 | 411 (0+411) | 98 | 0 | 185 |
| xfactor_eta600 | resilimes | before | 92.6 | 2898 | 86 (86+0) | 44 | 101 | 195 |
| xfactor_eta600 | resilimes | mech | 92.5 | 2927 | 175 (0+175) | 61 | 1 | 150 |
| xfactor_eta600 | resilimes | after | 94.6 | 2991 | 110 (0+110) | 60 | 1 | 136 |
| xfactor_eta600 | edd | before | 84.3 | 2528 | 240 (240+0) | 55 | 175 | 190 |
| xfactor_eta600 | edd | after | 82.4 | 2540 | 445 (0+445) | 97 | 1 | 186 |
| tight_vip | resilimes | before | 95.4 | 1396 | 35 (35+0) | 5 | 28 | 211 |
| tight_vip | resilimes | mech | 93.0 | 1410 | 94 (0+94) | 12 | 1 | 166 |
| tight_vip | resilimes | after | 96.1 | 1476 | 51 (0+51) | 7 | 1 | 165 |
| tight_vip | edd | before | 65.1 | 943 | 401 (401+0) | 16 | 88 | 156 |
| tight_vip | edd | after | 71.6 | 1081 | 389 (0+389) | 40 | 0 | 153 |
| pm_enforced | resilimes | before | 93.4 | 2776 | 81 (81+0) | 36 | 78 | 209 |
| pm_enforced | resilimes | mech | 92.4 | 2814 | 164 (0+164) | 66 | 0 | 152 |
| pm_enforced | resilimes | after | 93.5 | 2904 | 134 (0+134) | 66 | 1 | 140 |
| pm_enforced | edd | before | 84.9 | 2447 | 213 (213+0) | 61 | 160 | 193 |
| pm_enforced | edd | after | 82.3 | 2473 | 422 (0+422) | 109 | 1 | 194 |
| litho | resilimes | before | 94.0 | 2918 | 70 (70+0) | 37 | 80 | 202 |
| litho | resilimes | mech | 93.7 | 2963 | 143 (0+143) | 55 | 0 | 143 |
| litho | resilimes | after | 95.0 | 3034 | 98 (0+98) | 60 | 1 | 139 |
| litho | edd | before | 85.9 | 2587 | 208 (208+0) | 55 | 162 | 184 |
| litho | edd | after | 83.6 | 2606 | 413 (0+413) | 99 | 0 | 184 |
| hot | resilimes | before | 93.9 | 2913 | 70 (70+0) | 39 | 81 | 202 |
| hot | resilimes | mech | 93.6 | 2958 | 145 (0+145) | 59 | 0 | 144 |
| hot | resilimes | after | 95.1 | 3031 | 96 (0+96) | 59 | 1 | 141 |
| hot | edd | before | 86.0 | 2598 | 207 (207+0) | 53 | 161 | 184 |
| hot | edd | after | 83.7 | 2608 | 411 (0+411) | 98 | 0 | 185 |
| heldout_published | resilimes | before | 94.0 | 2921 | 76 (76+0) | 43 | 69 | 202 |
| heldout_published | resilimes | mech | 93.9 | 2981 | 138 (0+138) | 55 | 0 | 143 |
| heldout_published | resilimes | after | 95.0 | 3033 | 100 (0+100) | 59 | 1 | 139 |
| heldout_published | edd | before | 85.6 | 2596 | 218 (218+0) | 61 | 155 | 187 |
| heldout_published | edd | after | 83.6 | 2622 | 415 (0+415) | 100 | 0 | 186 |
| heldout_xfactor | resilimes | before | 92.5 | 2897 | 97 (97+0) | 46 | 91 | 195 |
| heldout_xfactor | resilimes | mech | 92.3 | 2911 | 181 (0+181) | 61 | 1 | 148 |
| heldout_xfactor | resilimes | after | 95.1 | 3003 | 98 (0+98) | 56 | 0 | 136 |
| heldout_xfactor | edd | before | 83.8 | 2518 | 260 (260+0) | 53 | 174 | 189 |
| heldout_xfactor | edd | after | 81.9 | 2535 | 459 (0+459) | 98 | 2 | 186 |
| litho_family_2h | resilimes | before | 93.7 | 2898 | 76 (76+0) | 37 | 81 | 202 |
| litho_family_2h | resilimes | mech | 93.2 | 2947 | 155 (0+155) | 60 | 0 | 143 |
| litho_family_2h | resilimes | after | 94.6 | 3013 | 107 (0+107) | 64 | 0 | 140 |
| litho_family_2h | edd | before | 85.7 | 2597 | 209 (209+0) | 56 | 168 | 184 |
| litho_family_2h | edd | after | 83.2 | 2602 | 421 (0+421) | 105 | 0 | 184 |

### Table 3. All five policies, before → after (published and xfactor_eta600)

| Book | Policy | On-time % | Completed | X-factor | Q-time rate % | Batch fill % | Batch starts |
|---|---|---|---|---|---|---|---|
| published | resilimes | 57.1 → 55.0 | 135.8 → 122.0 | 2.58 → 2.56 | 94.0 → 94.9 | 68.9 → 71.1 | 478 → 476 |
| published | edd | 57.5 → 57.5 | 160.0 → 159.6 | 2.21 → 2.23 | 86.0 → 83.7 | 66.6 → 66.1 | 455 → 456 |
| published | fifo | 36.1 → 36.1 | 97.4 → 94.8 | 3.15 → 2.82 | 72.0 → 74.3 | 66.4 → 66.6 | 453 → 458 |
| published | cr | 57.1 → 55.7 | 64.4 → 63.0 | 3.67 → 3.70 | 87.3 → 84.6 | 69.7 → 69.7 | 458 → 457 |
| published | smt_rule | 57.1 → 55.7 | 61.2 → 60.4 | 3.66 → 3.60 | 87.6 → 85.5 | 73.4 → 73.2 | 478 → 479 |
| xfactor_eta600 | resilimes | 99.1 → 63.9 | 138.0 → 124.6 | 1.74 → 2.15 | 92.6 → 94.6 | 68.7 → 70.0 | 475 → 473 |
| xfactor_eta600 | edd | 99.5 → 99.5 | 165.8 → 166.6 | 1.59 → 1.59 | 84.3 → 82.4 | 67.5 → 67.7 | 448 → 445 |
| xfactor_eta600 | fifo | 45.3 → 54.0 | 98.2 → 96.4 | 2.94 → 2.65 | 72.0 → 74.1 | 66.5 → 66.7 | 451 → 454 |
| xfactor_eta600 | cr | 76.1 → 76.1 | 89.0 → 89.0 | 2.51 → 2.51 | 69.9 → 67.7 | 70.9 → 69.9 | 446 → 446 |
| xfactor_eta600 | smt_rule | 74.9 → 74.5 | 92.0 → 92.2 | 2.50 → 2.50 | 69.1 → 66.1 | 74.8 → 75.2 | 456 → 449 |
| heldout_published | resilimes | 57.1 → 55.4 | 144.4 → 130.8 | 2.37 → 2.39 | 94.0 → 95.0 | 68.2 → 70.5 | 477 → 476 |
| heldout_published | edd | 57.1 → 57.5 | 165.2 → 164.6 | 2.09 → 2.08 | 85.6 → 83.6 | 65.8 → 65.6 | 459 → 457 |
| heldout_published | fifo | 37.1 → 37.9 | 104.4 → 99.0 | 2.88 → 2.67 | 70.9 → 73.5 | 65.9 → 66.0 | 453 → 456 |
| heldout_published | cr | 56.8 → 55.0 | 62.2 → 62.6 | 3.58 → 3.59 | 88.0 → 84.9 | 69.1 → 68.4 | 457 → 456 |
| heldout_published | smt_rule | 57.1 → 55.7 | 62.2 → 61.6 | 3.54 → 3.56 | 87.4 → 85.6 | 73.1 → 72.1 | 479 → 479 |
| heldout_xfactor | resilimes | 100.0 → 77.9 | 140.8 → 126.8 | 1.71 → 2.03 | 92.5 → 95.1 | 67.9 → 69.6 | 478 → 472 |
| heldout_xfactor | edd | 100.0 → 100.0 | 167.6 → 166.2 | 1.56 → 1.56 | 83.8 → 81.9 | 66.9 → 66.7 | 450 → 449 |
| heldout_xfactor | fifo | 56.6 → 61.6 | 105.2 → 101.2 | 2.74 → 2.54 | 70.7 → 73.5 | 65.9 → 65.9 | 449 → 456 |
| heldout_xfactor | cr | 77.7 → 78.6 | 89.0 → 89.0 | 2.48 → 2.48 | 70.8 → 68.4 | 70.8 → 69.3 | 444 → 449 |
| heldout_xfactor | smt_rule | 81.4 → 81.1 | 91.4 → 92.0 | 2.45 → 2.44 | 70.4 → 67.5 | 75.2 → 75.1 | 453 → 445 |

### Table 4. Batch fill (lots / furnace lot capacity, mean over every book and seed)

| Policy | Before | After | Batch starts / run before → after |
|---|---|---|---|
| resilimes | 69.8 | 71.9 | 453 → 451 |
| edd | 68.0 | 67.9 | 433 → 432 |
| fifo | 67.8 | 68.1 | 430 → 433 |
| cr | 70.7 | 70.2 | 433 → 434 |
| smt_rule | 74.7 | 74.5 | 449 → 448 |

### Table 5. Re-cleans, holds, reservations, dispatch latency (ResiliMES after; EDD after for holds)

| Book | Recleans/run (own+inherited) before → after | Hold lot-min ResiliMES / EDD | Reservations / run | Minutes held / run | Dispatch p95 / busy-p95 ms before → after |
|---|---|---|---|---|---|
| published | 40 → 118 | 5490 / 15636 | 8.4 | 29 | 0.0065/0.148 → 0.0073/0.181 |
| xfactor_eta600 | 44 → 116 | 5711 / 16736 | 9.2 | 36 | 0.0067/0.141 → 0.0076/0.164 |
| tight_vip | 5 → 63 | 4706 / 14329 | 8.4 | 32 | 0.0063/0.134 → 0.0073/0.169 |
| pm_enforced | 36 → 122 | 6512 / 16184 | 12.8 | 41 | 0.0062/0.135 → 0.0071/0.169 |
| litho | 37 → 115 | 5447 / 15685 | 11.6 | 62 | 0.0063/0.146 → 0.0073/0.183 |
| hot | 39 → 115 | 5407 / 15636 | 11.0 | 58 | 0.0066/0.158 → 0.0074/0.193 |
| heldout_published | 43 → 115 | 5508 / 15730 | 12.4 | 50 | 0.0066/0.148 → 0.0073/0.189 |
| heldout_xfactor | 46 → 111 | 5345 / 17114 | 11.4 | 42 | 0.0069/0.146 → 0.0075/0.171 |
| litho_family_2h | 37 → 120 | 5724 / 15938 | 9.4 | 40 | 0.0064/0.145 → 0.0073/0.180 |

### Table 6. Ablation of the policy fixes (ResiliMES, seeds 1–5)

| Variant | published on-time % | published completed | xfactor_eta600 on-time % | xfactor completed | Q-time rate % (pub) |
|---|---|---|---|---|---|
| mech (no policy fixes) | 57.1 | 138.4 | 99.8 | 137.2 | 93.6 |
| fix 2 only | 57.1 | 136.8 | 98.6 | 136.6 | 93.6 |
| fix 3 only | 57.1 | 137.8 | 99.8 | 137.2 | 93.7 |
| fixes 2+3 | 57.1 | 136.6 | 98.9 | 137.8 | 93.7 |
| fix 1 only | 55.4 | 121.6 | 60.7 | 123.6 | 94.9 |
| fixes 1+2 | 55.4 | 120.8 | 64.4 | 125.4 | 94.9 |
| fixes 1+3 | 55.4 | 121.8 | 60.7 | 123.8 | 95.0 |
| after (1+2+3) | 55.0 | 122.0 | 63.9 | 124.6 | 94.9 |

## Stress: Litho_FE_92 family (26 scanners) down 2 h in the busy window

The outage starts at 0 h, where `busy_window` on main showed the deepest queue and the most starts. A
second outage start at 24 h is also run. Every policy uses seeds 1–5 at both starts.

The audit samples every 5 min and records:

- **Hard stall:** an idle, up tool with a startable lot and no pending event.
- **Stranded:** a lot that no tool of its family may ever start.
- **Frozen WIP:** no step completed fab-wide over a sample after the first hour.
- **Late start:** an idle tool waiting for a pending wake.

It also runs the full invariant checker. `make smt-invariants` (5 books × 5 policies × seeds 1–5, now with the stall, frozen-WIP and stranded checks) reports 0 failures on the branch.

| Arm | Runs | Hard-stall samples | Runs with stranded lots (max) | Frozen WIP | Invariant failures | Longest late wait |
|---|---|---|---|---|---|---|
| before (main) | 50 | 139 (resilimes 16, fifo 60, cr 43, smt_rule 20, edd 0) | 50 / 50 (max 52 lots) | 0 | 0 | 716 min |
| after | 50 | 0 | 0 / 50 | 0 | 0 | 29.7 min |

ResiliMES under stress after the fix: 55.0 % on-time and 121–123 completed routes, with 8–9
reservations and 35–40 held minutes per run. Fab throughput never dropped below 349 steps per hour in
the outage. **Verdict: no deadlock or starvation on the branch.** `make smt-invariants` now includes the
`litho_family_2h` book with the stall, frozen-WIP and stranded checks.

## Surprises, regressions and root causes

1. **Fix 1 costs ResiliMES throughput and on-time (largest effect).** Admitting every open-window lot
   made 10,753 extra shortlist admissions over one run (`xfactor_eta600`, seed 1).
   - **Mechanism:** these lots carry a positive PED from the moment the window opens. In the tiered key,
     PED comes before setup and slack, so an admitted windowed front-end lot outranks an on-time lot
     close to its due date. Earlier, the slack-ordered cut kept those due-date lots and dropped the
     windowed ones.
   - **Effect:** total starts stay the same but move from back-end steps to front-end windowed steps:
     LithoMet_BE_18 −33, DE_FE_86 −32, Litho_BE_93 −14. Routes finish later, and X-factor due lots go
     late.
   - **Result:** about 1 point better Q-time rate in exchange for 12 % fewer completed routes. No weight
     was tuned to hide this.
   - **Possible follow-ups (need a decision):**
     - admit only windowed lots whose graded urgency is at or near the latest start;
     - or rank admitted lots after the slack term until they become urgent (the PR #18 urgent band
       already covers that case).
2. **Holds replace late starts.** With fix 5, a missed window becomes a hold or a re-clean at its
   deadline instead of a late start. Counted re-cleans rise for every policy: ResiliMES 40 → 118 per run
   on `published`. Of those, about 56 are inherited snapshot windows that main never tracked; the rest
   are the new deadline re-cleans.
   - The Q-time rate of the four baselines drops by 2–3 points (for example EDD 86.0 → 83.7). Lots that
     main let start 5 min late are now held or recleaned.
   - Fix 5 changes the outcome for every policy (counting is the same in both arms), so compare
     policies within an arm.
3. **Full-queue batching barely moves the baselines.** Batch fill: EDD 68.0 → 67.9, ResiliMES
   69.8 → 71.9. Only ResiliMES has a capped shortlist, so for the baselines the queue was already full.
4. **Reservations are rare and short:** 8–13 per run and 29–62 held minutes per run.
5. **Dispatch latency:** busy-decision p95 rose from 0.145 to 0.178 ms (ResiliMES mean over every book)
   because of the larger shortlist and the reservation check. That is still far below a millisecond.
6. **Pre-existing stranded-lot bug on main:** see "Extra fix". It affected every policy, and the fix
   changes every baseline slightly.

## Caveats

- **Inherited windows:** the 433 inherited windows are taken to open at t=0 with their full limit. The
  snapshot has no time of the origin step's end.
- **Grade saturation:** the graded urgency saturates at 1 past the latest start, so late lots tie on
  PED and are ordered by setup and slack.
- **Late batch waits:** a furnace that set its batch wait before arrivals ended waits for the next
  pending wake (≤ 30 min seen after the fix). The audit reports these as late starts, not as stalls.
- **Stress window:** the stress outage starts at 0 h, because the snapshot WIP makes the start the
  busiest period. The 24 h start is run as well.
- **Scope:** results cover one snapshot, five training seeds and five held-out seeds.

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
