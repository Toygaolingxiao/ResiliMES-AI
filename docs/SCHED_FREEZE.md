# Frozen dispatch zone ("FIX") and the scheduling-tick log

Branch `sched-freeze`. Module `resilimes/smt/freeze.py`, hooks in
`resilimes/smt/simulate.py`, study `resilimes/smt/freeze_study.py`, tests
`tests/test_sched_freeze.py`, API `GET /api/sched/ticks`.

## The rule

This is the user's fab rule, not SMT2020 data. In the previous fab system each
tool's in-process lot and its next lots, within a fixed time or count, were
FIXED to that tool, so a lot that was already sent to a tool's port was not
transported a second time just because a later re-plan picked another tool.

At every scheduling tick (`REPLAN_SEC` = 300 s) each tool keeps the lot it is
processing plus its next loads, up to `max_lots` loads or `max_sec` of planned
start time, whichever comes first, fixed to that tool. Lots outside the zone
are re-planned at every tick and dispatched exactly as on main.

**Defaults: 2 loads or 30 min, whichever comes first.** These were fixed before
any run, from the user's description; they were not tuned and no other value
was tried in the study. A batch counts as one load.

### How the zone is planned

Per tool family, tools come free in order (now, end of the running piece, end
of a PM; a down tool or a tool holding a fix-3 reservation takes nothing). A
zone slot takes, among the first `LOOKAHEAD` feasible lots ready by then, the
one the policy's own per-tool rank puts first (so ResiliMES stays setup-aware
and EDD stays EDD); later (non-frozen) slots take the first feasible lot of the
family's cheap order. Feasible = tool eligible and the piece finishes before
the tool's next PM. Lots already frozen stay where they are (carried over).

The first version used the family's global order for zone slots too; on the
7-day study it raised ResiliMES setup time by ~40 % and cut utilisation by ~10
pp, so it was replaced before the results below. That is a bug fix of the
planner, not a tuning of the rule (defaults unchanged).

### Dispatch with the zone

A tool takes its frozen head when the head can start (eligibility, PM, Q-time
gate and batch rule as for any lot); a lot frozen to one tool is never taken by
another tool.

**Deadlock rule.** When the frozen head cannot start yet (not ready, batch
still filling, Q-time gate), the tool may run another ready lot only if that
lot finishes before the head can start, or if it is one of its own frozen lots
(`fill_starts`); otherwise the tool waits for the head (`frozen_waits`). Every
reason a frozen head cannot start either clears with time (arrival, batch,
gate) or is one of the logged exceptions below; `unfreeze: other` stayed 0 and
the simulator's stall detector did not fire in any run.

**Exceptions (the only ways a lot leaves the zone, each logged with reason):**

| reason | when |
|---|---|
| `tool_down` | the tool breaks down: every lot frozen there is released |
| `pm` | the lot can no longer finish before the tool's next scheduled PM, or the tool is in PM |
| `qtime_emergency` | the lot is inside an open CQT window, its frozen tool would start it after its latest start, and an idle sibling can start it now |
| `hot_lot` | a VIP/hot lot (SMT2020 PRIOR class) its frozen tool cannot start now while an idle sibling can |
| `hold` | Q-time hold or re-clean (the lot leaves the queue) |
| `eligibility` | the tool is no longer eligible (scanner dedication) |
| `other` | safety net: a frozen lot started on another tool by another path (0 in all runs) |

**Insertions (nothing is unfrozen or re-transported).** A lot that is not
frozen anywhere may run ahead of a tool's frozen head when the policy's own
choice at that tool puts it first and it is either a VIP/hot lot
(`hot_inserts`) or a Q-time emergency, i.e. inside an open CQT window whose
latest start falls before the tool would be through its frozen lots
(`qtime_inserts`). The frozen lots slip by one piece.

## Switches

Default OFF. With everything off no hook does anything and runs are
byte-identical to main (test: event-stream SHA-256 equals golden hashes
recorded on main `c75ff85`, both ResiliMES and EDD).

| switch | meaning |
|---|---|
| `run_policy(..., freeze=FreezeConfig(...))` | explicit config (wins over env) |
| `RESILIMES_SCHED_FREEZE=1` | enforce the zone |
| `RESILIMES_FREEZE_LOTS`, `RESILIMES_FREEZE_MIN` | limits (default 2, 30) |
| `RESILIMES_SCHED_TRACK=1` | shadow: compute zone + KPIs, do not enforce (dispatch unchanged; test: event stream equals main apart from the added `sched_tick` events) |
| `RESILIMES_TICK_LOG=path` | write the tick log (`.jsonl`, or `.jsonl.gz`) |
| `RESILIMES_TICK_LOG_DIR` | folder served by the API (default `out/sched_ticks`) |

## KPIs (`SimResult.sched_freeze`)

* **second transports**: a lot that entered a tool's zone (sent to its port)
  and is then, at the same step, re-targeted to another tool by a later tick or
  started elsewhere. For the off arm this is the shadow zone, i.e. how many
  second transports the main dispatcher *would* cause under the user's
  transport rule; for the on arm only logged exceptions can cause one.
* **unfreezes by reason** (table above), `hot_inserts`, `qtime_inserts`,
  `frozen_starts`, `fill_starts`, `frozen_waits`.
* **plan stability**, diff of each tick against the previous one:
  `staged_tool_change_rate` (share of zone lots whose tool changed),
  `plan_tool_change_rate` (same over zone + planned lots),
  `kendall_tau_distance` (normalised discordant pairs of each family's queue
  order between ticks), `frozen_per_tick`, `replanned_per_tick`.

## Tick log

One JSON line per tick: `t`, `t_h`, `policy`, `freeze`, `queues` (family →
lot order), `tools` (tool → `running`, `frozen`, `planned`), `holds`
(fix-3 reservations, hold plan), `ai_decisions` (shift-lead log since the
previous tick, if any), `diff` (`tool_changes`, `compared`,
`staged_tool_changes`, `order_swaps`, `order_pairs`, `kendall_tau_distance`,
`frozen`, `new_frozen`, `replanned`, `unfreezes`, `second_transports`), and the
lists `tool_changes`, `second_transports`, `unfreezes` with lot/tool names.

The study writes `OUT.ticks/{book}_s1_{policy}_{arm}.jsonl.gz` for published
seed 1 when `RESILIMES_STUDY_TICKLOG=1` (~10 MB each for 7 days).

API: `GET /api/sched/ticks` lists runs in `RESILIMES_TICK_LOG_DIR`;
`GET /api/sched/ticks?run=NAME&offset=0&limit=50` pages one log (limit 1..500;
404 for an unknown run).

## Known simplifications

* Carried-over frozen lots are counted as lots, not loads, when the zone is
  refilled (a frozen batch counts once when it is planned).
* Transport itself is not simulated (SMT2020 has no AMHS); "second transport"
  is counted from the plan, as above.

## 7-day study: freeze off vs on

`RESILIMES_STUDY_WORKERS=3 RESILIMES_STUDY_TICKLOG=1 python -m resilimes.smt.freeze_study out/freeze_7d.json`,
then `--report out/freeze_7d.json`. Same books and seeds as the existing
studies (`qtime_study`: 9 books, published seeds 1-5, held-out books seeds
9-13; `tight_vip` keeps its own short horizon), 168 h, ResiliMES and EDD,
180 runs, code at the planner fix (`1d31cd5`; later commits are docs). The
off arm is main's dispatch with shadow tracking. Nothing was tuned: the
limits stayed at the a-priori 2 loads / 30 min, and seeds and due dates are the
studies' own. Run 2026-10-24 21:50-22:34 JST.

### all books, all seeds

| KPI | resilimes off | resilimes on | edd off | edd on |
|---|---|---|---|---|
| on-time % | 92.5 | 90.84 | 93.56 | 92.55 |
| completed | 14993 | 15034 | 20912 | 20688 |
| true Q-time % | 97.15 | 95.88 | 88.8 | 87.05 |
| Q-time holds | 8979 | 13105 | 34163 | 38611 |
| weighted tardiness (min) | 679656.4 | 895339.2 | 674339.9 | 915154.6 |
| fab util % (mean) | 58.5 | 60.5 | 49.58 | 49.75 |
| litho util % (mean) | 72.12 | 74.25 | 63.16 | 63.32 |
| plan stability: staged tool-change rate | 0.4278 | 0.0345 | 0.3261 | 0.0151 |
| plan stability: planned tool-change rate | 0.4738 | 0.3487 | 0.3533 | 0.298 |
| plan stability: Kendall-tau distance | 0.00229 | 0.00233 | 0.0 | 0.0 |
| second transports | 5131958 | 9088 | 3219028 | 5926 |
| unfreezes (total) | 0 | 22891 | 0 | 21028 |
| hot-lot insertions | 0 | 41199 | 0 | 11380 |
| Q-time insertions | 0 | 10137 | 0 | 2357 |
| unfreeze: tool_down | 0 | 6597 | 0 | 4175 |
| unfreeze: pm | 0 | 8571 | 0 | 8444 |
| unfreeze: qtime_emergency | 0 | 526 | 0 | 554 |
| unfreeze: hot_lot | 0 | 1167 | 0 | 940 |
| unfreeze: hold | 0 | 5946 | 0 | 6843 |
| unfreeze: eligibility | 0 | 84 | 0 | 72 |
| unfreeze: other | 0 | 0 | 0 | 0 |

### published seeds 1-5

| KPI | resilimes off | resilimes on | edd off | edd on |
|---|---|---|---|---|
| on-time % | 92.3 | 90.84 | 92.62 | 91.48 |
| completed | 11199 | 11246 | 15723 | 15562 |
| true Q-time % | 97.16 | 96.04 | 88.82 | 87.03 |
| Q-time holds | 6874 | 9631 | 25682 | 29387 |
| weighted tardiness (min) | 567995.9 | 738791.1 | 569033.1 | 771188.3 |
| fab util % (mean) | 58.8 | 60.53 | 50.0 | 50.19 |
| litho util % (mean) | 72.73 | 74.51 | 63.97 | 64.09 |
| plan stability: staged tool-change rate | 0.4353 | 0.0344 | 0.3174 | 0.0149 |
| plan stability: planned tool-change rate | 0.4776 | 0.3505 | 0.3436 | 0.2905 |
| plan stability: Kendall-tau distance | 0.00217 | 0.00219 | 0.0 | 0.0 |
| second transports | 3948788 | 7038 | 2420018 | 4715 |
| unfreezes (total) | 0 | 17907 | 0 | 17055 |
| hot-lot insertions | 0 | 30880 | 0 | 9144 |
| Q-time insertions | 0 | 7405 | 0 | 1779 |
| unfreeze: tool_down | 0 | 4947 | 0 | 3188 |
| unfreeze: pm | 0 | 7295 | 0 | 7208 |
| unfreeze: qtime_emergency | 0 | 378 | 0 | 429 |
| unfreeze: hot_lot | 0 | 877 | 0 | 759 |
| unfreeze: hold | 0 | 4343 | 0 | 5414 |
| unfreeze: eligibility | 0 | 67 | 0 | 57 |
| unfreeze: other | 0 | 0 | 0 | 0 |

### held-out seeds 9-13

| KPI | resilimes off | resilimes on | edd off | edd on |
|---|---|---|---|---|
| on-time % | 93.08 | 90.83 | 96.3 | 95.7 |
| completed | 3794 | 3788 | 5189 | 5126 |
| true Q-time % | 97.12 | 95.37 | 88.76 | 87.13 |
| Q-time holds | 2105 | 3474 | 8481 | 9224 |
| weighted tardiness (min) | 111660.5 | 156548.1 | 105306.8 | 143966.3 |
| fab util % (mean) | 57.47 | 60.39 | 48.11 | 48.21 |
| litho util % (mean) | 70.0 | 73.37 | 60.32 | 60.63 |
| plan stability: staged tool-change rate | 0.4016 | 0.0347 | 0.3566 | 0.0158 |
| plan stability: planned tool-change rate | 0.4605 | 0.3427 | 0.3873 | 0.3241 |
| plan stability: Kendall-tau distance | 0.00273 | 0.00284 | 0.0 | 0.0 |
| second transports | 1183170 | 2050 | 799010 | 1211 |
| unfreezes (total) | 0 | 4984 | 0 | 3973 |
| hot-lot insertions | 0 | 10319 | 0 | 2236 |
| Q-time insertions | 0 | 2732 | 0 | 578 |
| unfreeze: tool_down | 0 | 1650 | 0 | 987 |
| unfreeze: pm | 0 | 1276 | 0 | 1236 |
| unfreeze: qtime_emergency | 0 | 148 | 0 | 125 |
| unfreeze: hot_lot | 0 | 290 | 0 | 181 |
| unfreeze: hold | 0 | 1603 | 0 | 1429 |
| unfreeze: eligibility | 0 | 17 | 0 | 15 |
| unfreeze: other | 0 | 0 | 0 | 0 |

### on - off per book (pooled over seeds)

| book | policy | on-time pp | completed | true Q pp | WT min | second transports |
|---|---|---|---|---|---|---|
| heldout_published | resilimes | -1.14 | -20 | -2.08 | +30251.9 | 642603 -> 993 |
| heldout_published | edd | -1.14 | -25 | -1.52 | +38539.1 | 394764 -> 619 |
| heldout_xfactor | resilimes | -3.26 | +14 | -1.41 | +14635.7 | 540567 -> 1057 |
| heldout_xfactor | edd | -0.11 | -38 | -1.73 | +120.4 | 404246 -> 592 |
| hot | resilimes | -1.14 | +5 | -1.18 | +34602.1 | 652166 -> 986 |
| hot | edd | -1.2 | -27 | -1.72 | +39515 | 398816 -> 645 |
| litho | resilimes | -1.21 | +21 | -1.03 | +30684 | 650748 -> 980 |
| litho | edd | -1.01 | -21 | -1.71 | +38693.6 | 393885 -> 674 |
| litho_family_2h | resilimes | -0.89 | -3 | -0.74 | +29977.2 | 675149 -> 1004 |
| litho_family_2h | edd | -1.34 | -20 | -2.07 | +40548 | 404624 -> 699 |
| pm_enforced | resilimes | -1.14 | -17 | -0.68 | +30810.8 | 647520 -> 1806 |
| pm_enforced | edd | -1.46 | -29 | -1.76 | +34803 | 399692 -> 1184 |
| published | resilimes | -1.21 | +16 | -1.27 | +32486.9 | 653362 -> 1024 |
| published | edd | -1.2 | -27 | -1.72 | +39515 | 398816 -> 645 |
| tight_vip | resilimes | -12.38 | +0 | -3.14 | +7616.5 | 129245 -> 164 |
| tight_vip | edd | -12.38 | +0 | -0.01 | +9080.6 | 9888 -> 222 |
| xfactor_eta600 | resilimes | -2.34 | +25 | -1.5 | +4617.7 | 540598 -> 1074 |
| xfactor_eta600 | edd | +0 | -37 | -2.04 | +0 | 414297 -> 646 |

### runs where on is worse than off (same book, seed, policy)

- resilimes: 45 pairs; on worse in on-time 45, true Q 42, weighted tardiness 45, completed 16
- edd: 45 pairs; on worse in on-time 36, true Q 42, weighted tardiness 36, completed 38


## Verdict

At the default 2 loads / 30 min, the frozen zone does what the rule asks for. It
**costs delivery** for both policies, consistently across books and on the
held-out seeds.

* **Transport and plan stability: large gain.** Second transports drop
  ~99.8 % (ResiliMES 5.13 M → 9.1 k, EDD 3.22 M → 5.9 k over all runs). For
  the off arm this is the shadow count: how often main's re-planning would move
  a lot that was already sent to a port. The staged tool-change rate drops
  0.43 → 0.03 (ResiliMES) and 0.33 → 0.015 (EDD). Every remaining unfreeze is
  logged with its reason; `other` = 0.
* **Delivery: a regression, not noise.**
  * On-time falls 1.7 pp (ResiliMES) and 1.0 pp (EDD).
  * True Q-time falls 1.3 pp (ResiliMES) and 1.8 pp (EDD), with Q-time holds
    up 46 % and 13 %.
  * Weighted tardiness rises 32 % (ResiliMES) and 36 % (EDD).
  * Completed is flat for ResiliMES (+0.3 %) and down 1.1 % for EDD.
  * On held-out seeds ResiliMES loses 2.3 pp on-time and 1.8 pp Q-time.
  * Per pair, ON is worse in tardiness in 45/45 ResiliMES and 36/45 EDD runs,
    and worse in true Q-time in 42/45 for each policy.
  * `tight_vip` (short horizon, few due lots) loses 12 pp on-time for both
    policies.
* **Utilisation rises 2 pp under ResiliMES** (fab 58.5 → 60.5 %, litho
  72.1 → 74.3 %) and is flat under EDD. This is not higher throughput:
  completions are flat. It comes with more Q-time holds and re-cleans.
* **Why.** A frozen lot keeps its tool even when a later tick finds a better
  slot elsewhere. A tool waits for a frozen head that is still arriving
  (deadlock rule) rather than starting ready work. Lots outside the zone,
  especially those upstream inside multi-step CQT windows, are pushed back.
  The hot and Q-time insertions and the exceptions limit the damage but do
  not remove it.
* **Reading.** The rule removes almost every second transport, which SMT2020
  does not charge for (it has no AMHS model). The tardiness and Q-time cost is
  the price of that stability in this simulator. Whether the trade is worth it
  depends on the fab's real transport cost and risk. That cost is not modelled
  here, so this study does not settle it. Only the a-priori defaults were run;
  smaller zones were deliberately not swept, to avoid tuning to win.
* Main has since gained #27 (`ped_risk` exponent saturation, in
  `kernel/score.py`). The study ran on the branch base `c75ff85`. The
  off == main golden test also passes on the PR merge ref in CI.
